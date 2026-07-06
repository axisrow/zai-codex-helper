"""Tests for the ``tui`` menu (``zai-codex-helper`` bare invocation).

Covers: key decoding, dispatch routing to the right service function, the
live-state labels (toggle On/Off), the macro-disable logic (Install disabled
when fully on; Uninstall when fully off), and the redraw pause. Service
functions are mocked via monkeypatch so NO real launchctl / doctor run fires.
"""

import argparse

import pytest

from zai_codex_helper.cli import tui
from zai_codex_helper.services.aliases import AliasResult


class _FakeStdin:
    """A stdin that ``isatty()`` reports as a terminal (so the guard passes)."""

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return 0


def _ns():
    return argparse.Namespace(dry_run=False)


@pytest.mark.unit
def test_dispatch_quit_returns_true():
    """The Quit action signals the loop to exit."""
    assert (
        tui._dispatch("action-quit", argparse.Namespace(), _ns(), (False, False, ""))
        is True
    )


@pytest.mark.unit
def test_dispatch_doctor_calls_run_doctor(monkeypatch):
    """Doctor action routes to run_doctor."""
    import zai_codex_helper.services.doctor as doctor

    called = []
    monkeypatch.setattr(doctor, "run_doctor", lambda *a, **k: called.append(True) or 0)
    monkeypatch.setattr(tui, "_pause", lambda: None)
    paths = argparse.Namespace()
    assert tui._dispatch("action-doctor", paths, _ns(), (False, False, "")) is False
    assert called == [True]


@pytest.mark.unit
def test_dispatch_toggle_zai_flips_provider(monkeypatch):
    """Z.ai toggle calls apply_openai when currently Z.ai, else apply_zai."""
    from zai_codex_helper.services.provider_apply import ProviderApplyResult

    applied = []

    def fake_apply_provider(paths, transform, *, dry_run=False):
        applied.append(transform.__name__)
        return ProviderApplyResult(
            config_changed=True, dry_run_diff=None, desktop_restart_required=True
        )

    monkeypatch.setattr(
        "zai_codex_helper.services.provider_apply.apply_provider",
        fake_apply_provider,
    )
    monkeypatch.setattr(tui, "_pause", lambda: None)
    # state[0]=is_zai=True → flip to openai (state passed in, no _state call).
    tui._dispatch("toggle-zai", argparse.Namespace(), _ns(), (True, True, "Z.ai"))
    assert applied == ["apply_openai"]


#: A well-formed Z.ai key (``<32-hex>.<16-alnum>``) for the prompt mocks below.
_FAKE_KEY = "11111111111111111111111111111111.aaaaaaaaaaaaaaaa"


@pytest.mark.unit
def test_dispatch_install_prompts_key_when_env_unset(monkeypatch):
    """#11: env unset + real run → TUI prompts, key flows into install_macro's environ."""
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.setattr(tui, "_pause", lambda: None)

    prompts = []
    monkeypatch.setattr(
        "zai_codex_helper.services.setup._prompt_api_key",
        lambda _gp: prompts.append(True) or _FAKE_KEY,
    )
    seen = {}
    monkeypatch.setattr(
        "zai_codex_helper.services.install.install_macro",
        lambda paths, **kw: seen.update(kw),
    )

    tui._dispatch("macro-install", argparse.Namespace(), _ns(), (False, False, ""))

    assert prompts == [True]  # prompted exactly once
    assert seen["environ"] == {"ZAI_API_KEY": _FAKE_KEY}  # key reached install
    assert seen["headless"] is True


@pytest.mark.unit
def test_dispatch_install_no_prompt_when_env_set(monkeypatch):
    """Env already set → no prompt; install_macro gets environ=None (reads os.environ)."""
    monkeypatch.setenv("ZAI_API_KEY", _FAKE_KEY)
    monkeypatch.setattr(tui, "_pause", lambda: None)

    prompted = []
    monkeypatch.setattr(
        "zai_codex_helper.services.setup._prompt_api_key",
        lambda _gp: prompted.append(True) or _FAKE_KEY,
    )
    seen = {}
    monkeypatch.setattr(
        "zai_codex_helper.services.install.install_macro",
        lambda paths, **kw: seen.update(kw),
    )

    tui._dispatch("macro-install", argparse.Namespace(), _ns(), (False, False, ""))

    assert prompted == []  # env present → never prompted
    assert seen["environ"] is None  # run_setup falls back to os.environ


@pytest.mark.unit
def test_dispatch_install_dry_run_skips_prompt(monkeypatch):
    """--dry-run is a preview: never prompt for a secret, even with env unset."""
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.setattr(tui, "_pause", lambda: None)

    prompted = []
    monkeypatch.setattr(
        "zai_codex_helper.services.setup._prompt_api_key",
        lambda _gp: prompted.append(True) or _FAKE_KEY,
    )
    seen = {}
    monkeypatch.setattr(
        "zai_codex_helper.services.install.install_macro",
        lambda paths, **kw: seen.update(kw),
    )

    dry = argparse.Namespace(dry_run=True)
    tui._dispatch("macro-install", argparse.Namespace(), dry, (False, False, ""))

    assert prompted == []  # dry-run → no secret collected
    assert seen["environ"] is None
    assert seen["dry_run"] is True


@pytest.mark.unit
def test_dispatch_install_never_echoes_key(monkeypatch, capsys):
    """SECR-01/03: the collected key must not appear in stdout/stderr."""
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.setattr(tui, "_pause", lambda: None)
    monkeypatch.setattr(
        "zai_codex_helper.services.setup._prompt_api_key",
        lambda _gp: _FAKE_KEY,
    )
    monkeypatch.setattr(
        "zai_codex_helper.services.install.install_macro",
        lambda paths, **kw: None,
    )

    tui._dispatch("macro-install", argparse.Namespace(), _ns(), (False, False, ""))

    out = capsys.readouterr()
    assert _FAKE_KEY not in out.out
    assert _FAKE_KEY not in out.err


@pytest.mark.unit
def test_is_disabled_install_when_fully_on():
    """Install disabled iff Z.ai active AND Moon Bridge loaded."""
    assert tui._is_disabled("macro-install", (True, True, "Z.ai")) is True
    assert tui._is_disabled("macro-install", (True, False, "Z.ai")) is False
    assert tui._is_disabled("macro-install", (False, True, "OpenAI")) is False


@pytest.mark.unit
def test_is_disabled_uninstall_when_fully_off():
    """Uninstall disabled iff neither Z.ai active nor Moon Bridge loaded."""
    assert tui._is_disabled("macro-uninstall", (False, False, "OpenAI")) is True
    assert tui._is_disabled("macro-uninstall", (True, False, "Z.ai")) is False
    assert tui._is_disabled("macro-uninstall", (False, True, "OpenAI")) is False


@pytest.mark.unit
def test_render_label_toggle_shows_state():
    """The Z.ai toggle label reflects live On/Off state."""
    assert "On" in tui._render_label("Z.ai", "toggle-zai", (True, True, "Z.ai"))
    assert "Off" in tui._render_label("Z.ai", "toggle-zai", (False, False, "OpenAI"))


@pytest.mark.unit
def test_run_non_tty_exits_with_error(capsys):
    """Piped stdin → ``error: tui requires a terminal`` + exit 1, no cbreak."""
    rc = tui.run(_ns())
    assert rc == 1
    assert "tui requires a terminal" in capsys.readouterr().err


@pytest.mark.unit
def test_run_arrow_keys_and_quit(monkeypatch):
    """End-to-end loop: ↓ to Quit, Enter → exit 0."""
    monkeypatch.setattr(tui.sys, "stdin", _FakeStdin())
    monkeypatch.setattr(tui.termios, "tcgetattr", lambda fd: None)
    monkeypatch.setattr(tui.termios, "tcsetattr", lambda *a, **k: None)
    monkeypatch.setattr(tui.tty, "setcbreak", lambda fd: None)
    monkeypatch.setattr(tui, "_state", lambda paths: (False, False, "OpenAI"))
    # DOWN×6 → Quit (last index), ENTER.
    keys = iter(("DOWN", "DOWN", "DOWN", "DOWN", "DOWN", "DOWN", "\r"))
    monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
    monkeypatch.setattr(
        tui, "_dispatch", lambda kind, paths, args, state: kind == "action-quit"
    )
    assert tui.run(_ns()) == 0


@pytest.mark.unit
def test_run_disabled_macro_shows_message_and_pauses(monkeypatch, capsys):
    """Enter on a disabled macro prints 'already in this state' + pauses (no dispatch)."""
    monkeypatch.setattr(tui.sys, "stdin", _FakeStdin())
    monkeypatch.setattr(tui.termios, "tcgetattr", lambda fd: None)
    monkeypatch.setattr(tui.termios, "tcsetattr", lambda *a, **k: None)
    monkeypatch.setattr(tui.tty, "setcbreak", lambda fd: None)
    # Fully-on state → Install (index 0) disabled.
    monkeypatch.setattr(tui, "_state", lambda paths: (True, True, "Z.ai"))
    dispatched = []
    monkeypatch.setattr(
        tui, "_dispatch", lambda *a, **k: dispatched.append(True) or False
    )
    paused = []
    monkeypatch.setattr(tui, "_pause", lambda: paused.append(True))
    keys = iter(("\r", "q"))  # ENTER on disabled Install, then q to quit.
    monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
    tui.run(_ns())
    assert dispatched == []  # disabled → NOT dispatched
    assert paused == [True]
    assert "already" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Aliases submenu (menu-aliases): dispatch routes to it, and it toggles
# zai/glm via the existing apply_aliases/remove_aliases service functions.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_dispatch_menu_aliases_runs_submenu(monkeypatch):
    """`menu-aliases` invokes the submenu (and signals no-quit)."""
    monkeypatch.setattr(tui, "_pause", lambda: None)
    called = []
    monkeypatch.setattr(
        tui, "_aliases_submenu", lambda paths, args: called.append(True)
    )
    rc = tui._dispatch("menu-aliases", argparse.Namespace(), _ns(), (False, False, ""))
    assert rc is False  # does not quit
    assert called == [True]


@pytest.mark.unit
def test_aliases_submenu_install_zai_toggles_on(monkeypatch, tmp_path):
    """Selecting 'Install zai' when absent → apply_aliases(names=['zai'])."""
    from zai_codex_helper.services.paths import Paths

    paths = Paths.from_home(tmp_path)
    # zai absent (no fence) → selecting it installs.
    applied = []
    monkeypatch.setattr(
        tui,
        "apply_aliases",
        lambda p, *, names=None, dry_run=False: (
            applied.append(names) or AliasResult(changed=True)
        ),
    )
    monkeypatch.setattr(
        tui, "remove_aliases", lambda *a, **k: AliasResult(changed=False)
    )
    monkeypatch.setattr(tui, "_pause", lambda: None)
    # DOWN → Install zai (index 0 is first item; submenu lists zai first), ENTER, ESC to leave.
    keys = iter(("\r", "ESC"))
    monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
    tui._aliases_submenu(paths, _ns())
    assert applied == [["zai"]]


@pytest.mark.unit
def test_aliases_submenu_install_glm_toggles_on(monkeypatch, tmp_path):
    """Selecting 'Install glm' routes to apply_aliases(names=['glm']) (→ install_glm)."""
    from zai_codex_helper.services.paths import Paths

    paths = Paths.from_home(tmp_path)
    applied = []
    monkeypatch.setattr(
        tui,
        "apply_aliases",
        lambda p, *, names=None, dry_run=False: (
            applied.append(names) or AliasResult(changed=True)
        ),
    )
    monkeypatch.setattr(
        tui, "remove_aliases", lambda *a, **k: AliasResult(changed=False)
    )
    monkeypatch.setattr(tui, "_pause", lambda: None)
    # DOWN once → Install glm (second item), ENTER, ESC.
    keys = iter(("DOWN", "\r", "ESC"))
    monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
    tui._aliases_submenu(paths, _ns())
    assert applied == [["glm"]]


@pytest.mark.unit
def test_aliases_submenu_glm_error_does_not_crash(monkeypatch, tmp_path, capsys):
    """A ZaiCodexHelperError (e.g. glm without yml) is caught — submenu stays up."""
    from zai_codex_helper.errors import ZaiCodexHelperError
    from zai_codex_helper.services.paths import Paths

    paths = Paths.from_home(tmp_path)
    monkeypatch.setattr(
        tui,
        "apply_aliases",
        lambda *a, **k: (_ for _ in ()).throw(ZaiCodexHelperError("no yml key")),
    )
    monkeypatch.setattr(
        tui, "remove_aliases", lambda *a, **k: AliasResult(changed=False)
    )
    monkeypatch.setattr(tui, "_pause", lambda: None)
    # DOWN → glm, ENTER (raises, caught), ESC.
    keys = iter(("DOWN", "\r", "ESC"))
    monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
    tui._aliases_submenu(paths, _ns())  # must not raise
    assert "error:" in capsys.readouterr().err


@pytest.mark.unit
def test_aliases_submenu_shows_not_installed_and_install_hint(
    monkeypatch, tmp_path, capsys
):
    """Absent alias renders '[not installed]' and the footer says 'Enter to install'."""
    from zai_codex_helper.services.paths import Paths

    paths = Paths.from_home(tmp_path)
    monkeypatch.setattr(tui, "_alias_installed", lambda p, name: False)
    monkeypatch.setattr(tui, "apply_aliases", lambda *a, **k: AliasResult(changed=True))
    monkeypatch.setattr(
        tui, "remove_aliases", lambda *a, **k: AliasResult(changed=False)
    )
    monkeypatch.setattr(tui, "_pause", lambda: None)
    keys = iter(("\r", "ESC"))  # ENTER on zai (absent) → install, then leave
    monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
    tui._aliases_submenu(paths, _ns())
    out = capsys.readouterr().out
    assert "[not installed]" in out
    assert "Enter to install" in out


@pytest.mark.unit
def test_aliases_submenu_shows_installed_and_uninstall_hint(
    monkeypatch, tmp_path, capsys
):
    """Installed alias renders '[installed]' and the footer says 'Enter to uninstall'."""
    from zai_codex_helper.services.paths import Paths

    paths = Paths.from_home(tmp_path)
    monkeypatch.setattr(tui, "_alias_installed", lambda p, name: True)
    monkeypatch.setattr(
        tui, "apply_aliases", lambda *a, **k: AliasResult(changed=False)
    )
    monkeypatch.setattr(
        tui, "remove_aliases", lambda *a, **k: AliasResult(changed=True)
    )
    monkeypatch.setattr(tui, "_pause", lambda: None)
    keys = iter(("\r", "ESC"))  # ENTER on zai (installed) → uninstall, then leave
    monkeypatch.setattr(tui, "_read_key", lambda: next(keys))
    tui._aliases_submenu(paths, _ns())
    out = capsys.readouterr().out
    assert "[installed]" in out
    assert "Enter to uninstall" in out
