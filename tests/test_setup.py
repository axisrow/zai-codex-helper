"""Phase 12 Plan 01 — on-disk end-to-end tests for the ``setup`` onboarding capstone.

This file pins the three Phase 12 ROADMAP Success Criteria + the SECR-03
no-leak invariant + the D-78 no-launchctl boundary + the D-79 headless-env
contract, by exercising the REAL orchestrator
(:func:`zai_codex_helper.services.setup.run_setup`) and the REAL CLI dispatch
(``main(["--yes","setup"])``) against the autouse ``_isolate_home`` sandbox.

What this file pins:

- **SC-1 (SETUP-01, SECR-01):** the interactive full flow walks provider →
  API key → ``moonbridge-zai.yml``@0600 → Moon Bridge build → shell helpers →
  apply provider → LaunchAgent offer → summary. Pinned by
  :func:`test_setup_interactive_full_flow_sc1`.
- **SC-2 (SETUP-02):** ``--yes`` runs the SAME flow headless (zero prompts,
  same on-disk state). Pinned by :func:`test_setup_yes_flag_scriptable_sc2`.
- **SC-3 (SETUP-03, D-80):** running setup twice yields byte-identical
  ``config.toml`` + ``moonbridge-zai.yml`` + ``.zshrc`` (and exactly one
  ``.zshrc`` marker fence). Pinned by
  :func:`test_setup_twice_byte_identical_sc3`.
- **SECR-03 (no-leak canary):** a distinctive API key literal does NOT appear
  in captured stdout OR stderr across a full run. Pinned by
  :func:`test_setup_api_key_never_leaked_secr03`.
- **D-79 (headless env required):** ``--yes`` with ``ZAI_API_KEY`` UNSET
  surfaces via ``main()`` as exit 1 + one-line ``error:`` mentioning the env
  var, no traceback. Pinned by :func:`test_setup_no_input_requires_env_d79`.
- **D-78 (no launchctl):** a spy on ``subprocess.run`` asserts no call's argv
  contains ``launchctl`` across the whole flow; on LaunchAgent consent the
  captured stdout contains ``install-service``. Pinned by
  :func:`test_setup_no_launchctl_call_d78`.
- **Dispatch (unit):** ``setup`` resolves to the real ``_handle_setup`` and
  ``--no-input`` parses to ``True``.

Build-mock strategy (the plan's documented SIMPLEST FIX for testability
through ``main([...])``): the tests PRE-CREATE the ``moon-bridge`` binary as
owner-executable so :func:`build_moonbridge`'s idempotency skip
(:func:`zai_codex_helper.services.deps._is_executable_file`) fires BEFORE any
subprocess — ZERO real git/go/network runs, and the default-arg-binding gotcha
is sidestepped entirely (the bound default ``build_moonbridge`` is never
reached because the skip returns first).

Interactive test strategy: SC-1 drives :func:`run_setup` directly with
injected ``input_fn`` / ``confirm_fn`` (the real interactive path,
``yes=False``) rather than fighting Python's default-arg binding through
``main(["setup"])`` — this exercises the identical code path the handler
delegates to. The ``main(["--yes","setup"])`` end-to-end dispatch is covered
by SC-2 / SC-3 / SECR-03 / D-78.

Every test runs under the autouse ``_isolate_home`` fixture (``conftest.py``)
which repoints ``HOME`` at ``tmp_path`` and pre-creates ``tmp_path/.codex``.
``Paths.default()`` resolves under the sandbox — no real-HOME write.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
import tomlkit
import yaml

from zai_codex_helper.__main__ import ZaiCodexHelperError, main
from zai_codex_helper.cli.parser import build_parser
from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.setup import run_setup

# A recognizable API key literal used by the SECR-03 canary test. Distinctive
# so it would surface in ANY accidental print/log of the key.
_CANARY_KEY = "sk-LEAK-CANARY-1234567890"


def _write(path: Path, data: bytes | str) -> None:
    """Seed ``path`` with ``data`` (bytes or str), creating parents first.

    Mirrors ``tests/test_use_zai_use_openai.py::_write``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)


def _precreate_binary(tmp_path: Path) -> Path:
    """Pre-create the ``moon-bridge`` binary as owner-executable.

    This makes :func:`build_moonbridge`'s idempotency skip fire BEFORE any
    subprocess runs (the documented SIMPLEST FIX for testability through
    ``main([...])``). Returns the binary path.
    """
    binary = tmp_path / ".codex" / "moon-bridge"
    binary.write_bytes(b"#!/bin/sh\nexit 0\n")
    os.chmod(binary, 0o755)
    # Sanity: the skip predicate must see it as executable.
    assert binary.stat().st_mode & stat.S_IXUSR
    return binary


def _read_back_toml(path: Path) -> tomlkit.TOMLDocument:
    """Read ``config.toml`` back from disk into a live TOMLDocument."""
    return tomlkit.parse(path.read_text(encoding="utf-8"))


# =========================================================================== #
# SC-1 (SETUP-01, SECR-01) — interactive full onboarding flow
# =========================================================================== #


@pytest.mark.integration
def test_setup_interactive_full_flow_sc1(tmp_path, monkeypatch):
    """SC-1 / SETUP-01 / SECR-01: the interactive flow walks every step in order.

    Drives :func:`run_setup` directly with injected ``input_fn`` /
    ``confirm_fn`` (``yes=False`` — the real interactive path the handler
    delegates to). Asserts the full D-76 step sequence produces the expected
    on-disk state: ``moonbridge-zai.yml``@0600 with the canonical body, the
    ``.zshrc`` marker fence, and ``config.toml`` with Z.ai applied.
    """
    _precreate_binary(tmp_path)
    paths = Paths.from_home(tmp_path)
    monkeypatch.setenv("ZAI_API_KEY", "sk-test-SETUP-01")

    # Injected seams simulate the interactive user: provider choice + consent.
    inputs = iter(["zai"])

    def input_fn(_prompt: str) -> str:
        return next(inputs)

    confirmed: list[str] = []

    def confirm_fn(prompt: str, **_kw) -> bool:
        confirmed.append(prompt)
        return True

    # getpass_fn should NOT be called (env key wins). If it were, fail loudly.
    def getpass_fn(_prompt: str) -> str:
        raise AssertionError("getpass must not be called when ZAI_API_KEY env is set")

    rc = run_setup(
        paths,
        yes=False,
        dry_run=False,
        input_fn=input_fn,
        getpass_fn=getpass_fn,
        confirm_fn=confirm_fn,
    )

    assert rc == 0
    # moonbridge-zai.yml @ 0600 with the canonical body.
    yml = tmp_path / ".codex" / "moonbridge-zai.yml"
    assert yml.exists()
    assert (yml.stat().st_mode & 0o777) == 0o600
    data = yaml.safe_load(yml.read_text())
    assert data["ZAI_API_KEY"] == "sk-test-SETUP-01"
    assert data["model"] == "glm-5.2"
    assert data["server"] == {"host": "127.0.0.1", "port": 38440}
    # .zshrc marker fence written.
    zshrc = tmp_path / ".zshrc"
    assert zshrc.exists()
    assert "# >>> zai-codex-helper >>>" in zshrc.read_text()
    # config.toml has Z.ai applied (provider pipeline ran inline).
    doc = _read_back_toml(tmp_path / ".codex" / "config.toml")
    assert doc["model"] == "glm-5.2"
    assert doc["model_provider"] == "zai-moonbridge"
    assert doc["model_reasoning_effort"] == "xhigh"
    # Both consent prompts were reached (shell helpers + LaunchAgent offer).
    assert any("shell helpers" in p.lower() for p in confirmed)
    assert any("launchagent" in p.lower() for p in confirmed)


# =========================================================================== #
# SC-2 (SETUP-02) — --yes runs headless, same on-disk state
# =========================================================================== #


@pytest.mark.integration
def test_setup_yes_flag_scriptable_sc2(tmp_path, monkeypatch, capsys):
    """SC-2 / SETUP-02: ``main(['--yes','setup'])`` runs headless, zero prompts.

    Asserts rc==0; the same on-disk state as SC-1 (Z.ai applied, yml@0600,
    .zshrc marker); AND that the interactive seams (input/getpass/confirm)
    are NEVER invoked by the orchestrator in headless mode (proven by
    supplying raising fakes — if the headless path ever prompted, the test
    would raise instead of passing).
    """
    _precreate_binary(tmp_path)
    monkeypatch.setenv("ZAI_API_KEY", "sk-test-SETUP-02")

    # The headless path must NOT call any of these. Supply raising fakes via
    # direct run_setup injection to prove the headless bypass; the main([...])
    # call below proves the handler wiring end-to-end.
    def raising_input(_p: str) -> str:
        raise AssertionError("input must not be called under --yes")

    def raising_getpass(_p: str) -> str:
        raise AssertionError("getpass must not be called when env key is set")

    def raising_confirm(_p: str, **_k) -> bool:
        raise AssertionError("confirm must not be called under --yes")

    # 1. Direct run_setup proves the headless bypass of every interactive seam.
    paths = Paths.from_home(tmp_path)
    rc_direct = run_setup(
        paths,
        yes=True,
        dry_run=False,
        input_fn=raising_input,
        getpass_fn=raising_getpass,
        confirm_fn=raising_confirm,
    )
    assert rc_direct == 0
    capsys.readouterr()  # drain the direct-call output

    # Reset the on-disk state so the main([...]) call is a clean run.
    for p in (
        paths.config_toml,
        paths.moonbridge_yml,
        paths.zshrc,
        paths.config_toml.parent / (paths.config_toml.name + ".zai-codex-helper.bak"),
        paths.config_toml.parent / ".zai-codex-helper.backed-up",
    ):
        if p.exists():
            p.unlink()

    # 2. main(['--yes','setup']) proves the handler wiring end-to-end.
    rc = main(["--yes", "setup"])
    assert rc == 0

    # Same on-disk state as SC-1.
    yml = tmp_path / ".codex" / "moonbridge-zai.yml"
    assert (yml.stat().st_mode & 0o777) == 0o600
    data = yaml.safe_load(yml.read_text())
    assert data["ZAI_API_KEY"] == "sk-test-SETUP-02"
    assert data["model"] == "glm-5.2"
    zshrc = tmp_path / ".zshrc"
    assert "# >>> zai-codex-helper >>>" in zshrc.read_text()
    doc = _read_back_toml(tmp_path / ".codex" / "config.toml")
    assert doc["model"] == "glm-5.2"
    assert doc["model_provider"] == "zai-moonbridge"


# =========================================================================== #
# SC-3 (SETUP-03, D-80) — idempotent double-setup (byte-identical)
# =========================================================================== #


@pytest.mark.integration
def test_setup_twice_byte_identical_sc3(tmp_path, monkeypatch):
    """SC-3 / SETUP-03 / D-80: setup twice -> byte-identical files, one fence.

    Snapshots ``config.toml`` + ``moonbridge-zai.yml`` + ``.zshrc`` bytes
    after run #1; re-runs; asserts all three are byte-identical after run #2
    AND ``.zshrc`` contains EXACTLY ONE marker fence (no append/dup).
    """
    _precreate_binary(tmp_path)
    monkeypatch.setenv("ZAI_API_KEY", "sk-test-SETUP-03-idempotent")

    assert main(["--yes", "setup"]) == 0
    cfg = tmp_path / ".codex" / "config.toml"
    yml = tmp_path / ".codex" / "moonbridge-zai.yml"
    zshrc = tmp_path / ".zshrc"
    cfg_1 = cfg.read_bytes()
    yml_1 = yml.read_bytes()
    zshrc_1 = zshrc.read_bytes()

    assert main(["--yes", "setup"]) == 0
    cfg_2 = cfg.read_bytes()
    yml_2 = yml.read_bytes()
    zshrc_2 = zshrc.read_bytes()

    # Byte-identical (D-80 idempotence by composition).
    assert cfg_1 == cfg_2, "config.toml differs across setup runs"
    assert yml_1 == yml_2, "moonbridge-zai.yml differs across setup runs"
    assert zshrc_1 == zshrc_2, ".zshrc differs across setup runs"
    # Exactly ONE marker fence (no duplicate append).
    text = zshrc_2.decode("utf-8")
    assert text.count("# >>> zai-codex-helper >>>") == 1


# =========================================================================== #
# SECR-03 — API key never leaked (canary spy on stdout + stderr)
# =========================================================================== #


@pytest.mark.integration
def test_setup_api_key_never_leaked_secr03(tmp_path, monkeypatch, capsys):
    """SECR-03: the API key literal NEVER appears in captured stdout OR stderr.

    Uses a distinctive canary literal via ``ZAI_API_KEY`` env. After a full
    ``main(['--yes','setup'])`` run, asserts the canary is absent from BOTH
    stdout and stderr. This is the highest-signal SECR-03 test — the canary
    would surface in ANY accidental print/log of the key.
    """
    _precreate_binary(tmp_path)
    monkeypatch.setenv("ZAI_API_KEY", _CANARY_KEY)

    rc = main(["--yes", "setup"])
    assert rc == 0

    out, err = capsys.readouterr()
    assert _CANARY_KEY not in out, (
        f"API key leaked to stdout: {_CANARY_KEY!r} present in {out!r}"
    )
    assert _CANARY_KEY not in err, (
        f"API key leaked to stderr: {_CANARY_KEY!r} present in {err!r}"
    )


# =========================================================================== #
# D-79 — --yes without ZAI_API_KEY env -> exit 1 + one-line error
# =========================================================================== #


@pytest.mark.integration
def test_setup_no_input_requires_env_d79(tmp_path, monkeypatch, capsys):
    """D-79: ``--yes`` with ``ZAI_API_KEY`` UNSET -> exit 1 + actionable error.

    Headless mode has no stdin to fall back to, so the orchestrator MUST raise
    ``ZaiCodexHelperError`` naming the env var. Surfaces via ``main()`` as
    exit 1 + one-line ``error:`` mentioning ``ZAI_API_KEY``, no traceback.
    """
    _precreate_binary(tmp_path)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)

    rc = main(["--yes", "setup"])

    assert rc == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert "error:" in err
    assert "ZAI_API_KEY" in err
    assert "Traceback" not in err
    assert "ZaiCodexHelperError" not in err


def test_setup_no_input_raises_directly_d79(tmp_path):
    """D-79 (unit-tier): ``run_setup(yes=True)`` with no env key raises directly.

    Proves the orchestrator raises ``ZaiCodexHelperError`` (not some other
    error) when headless mode lacks the env key — the precise contract the
    handler lets propagate to ``main()``.
    """
    paths = Paths.from_home(tmp_path)
    with pytest.raises(ZaiCodexHelperError) as exc_info:
        run_setup(paths, yes=True, dry_run=False, environ={})
    assert "ZAI_API_KEY" in str(exc_info.value)


# =========================================================================== #
# D-78 — no launchctl call; install-service printed on consent
# =========================================================================== #


@pytest.mark.integration
def test_setup_no_launchctl_call_d78(tmp_path, monkeypatch, capsys):
    """D-78: setup NEVER calls launchctl; on consent it prints install-service.

    Installs a recording spy on ``zai_codex_helper.services.moonbridge.subprocess.run``
    (the only subprocess seam in the composed primitives — build_moonbridge's
    runner). The binary is pre-created so the build skips (no subprocess at
    all), but the spy is the authoritative assertion that NO launchctl call
    occurs anywhere in the flow. Under ``--yes`` the LaunchAgent is consented,
    so captured stdout MUST contain ``install-service``.
    """
    _precreate_binary(tmp_path)
    monkeypatch.setenv("ZAI_API_KEY", "sk-test-D-78")

    captured_argv: list[list[str]] = []

    def fake_runner(argv, **_kwargs):
        captured_argv.append(list(argv))
        # Emulate subprocess.run's no-op success for any unexpected call. The
        # build should skip entirely (binary pre-created), so this should not
        # fire; if it does, the launchctl assertion below catches it.
        return None

    monkeypatch.setattr(
        "zai_codex_helper.services.moonbridge.subprocess.run", fake_runner
    )

    rc = main(["--yes", "setup"])
    assert rc == 0

    # No captured call's argv contains "launchctl" (D-78 — Phase 13's boundary).
    for argv in captured_argv:
        assert "launchctl" not in argv, f"launchctl invoked: {argv!r}"

    out, _err = capsys.readouterr()
    # Under --yes the LaunchAgent is consented → the install-service hint prints.
    assert "install-service" in out


# =========================================================================== #
# Dispatch checks (unit — no disk IO beyond parse)
# =========================================================================== #


@pytest.mark.unit
def test_setup_is_real_handler_not_stub():
    """``setup`` dispatches to the real ``_handle_setup`` (not a stub closure).

    A stub closure is named ``handler``; the real handler is a named module
    function. This is the D-02 stub → Phase 12 real swap.
    """
    args = build_parser().parse_args(["setup"])
    assert args.cmd == "setup"
    assert args.func.__name__ == "_handle_setup"


@pytest.mark.unit
def test_no_input_flag_parsed():
    """``--no-input`` parses to ``args.no_input is True`` (D-79)."""
    args = build_parser().parse_args(["--no-input", "setup"])
    assert args.no_input is True
    assert args.cmd == "setup"


@pytest.mark.unit
def test_yes_flag_still_parsed():
    """``--yes`` still parses to ``args.yes is True`` (unchanged by --no-input)."""
    args = build_parser().parse_args(["--yes", "setup"])
    assert args.yes is True


@pytest.mark.unit
def test_doctor_is_real_handler_install_uninstall_are_real():
    """install/uninstall/doctor are all real handlers (no stubs remain).

    D-82: Phase 12 swapped ``setup``; Phase 13 (D-87) swapped
    ``install-service``/``uninstall-service``; Phase 14 (D-89) swapped
    ``doctor`` — the LAST Phase 1 stub. The Phase 1 stub set is now EMPTY.
    """
    # install-service / uninstall-service → real Phase 13 handlers.
    for name, expected in (
        ("install-service", "_handle_install_service"),
        ("uninstall-service", "_handle_uninstall_service"),
    ):
        args = build_parser().parse_args([name])
        assert args.func.__name__ == expected, (
            f"{name} should resolve to {expected}, got {args.func.__name__}"
        )

    # doctor → real Phase 14 handler (no longer a stub closure).
    args = build_parser().parse_args(["doctor"])
    assert args.func.__name__ == "_handle_doctor", (
        f"doctor should resolve to _handle_doctor, got {args.func.__name__}"
    )
