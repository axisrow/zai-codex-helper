"""Tests for the ``tui`` menu (``zai-codex-helper`` bare invocation).

Covers: key decoding, dispatch routing to the right service function, the
live-state labels (toggle On/Off), the macro-disable logic (Install disabled
when fully on; Uninstall when fully off), and the redraw pause. Service
functions are mocked via monkeypatch so NO real launchctl / doctor run fires.
"""

import argparse

import pytest

from zai_codex_helper.cli import tui


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
    # DOWN×5 → Quit (index 5), ENTER.
    keys = iter(("DOWN", "DOWN", "DOWN", "DOWN", "DOWN", "\r"))
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
