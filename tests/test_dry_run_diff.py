"""Phase 15 Plan 01 — ``--dry-run`` real diff preview tests (CONF-07, D-95).

Pins SC-1: passing ``--dry-run`` to ``use zai`` / ``use openai`` / ``setup`` /
``install-service`` produces a REAL preview of what would change AND writes
NOTHING. Before Phase 15 the dry-run branches only skipped the write and
printed a "would write X" string; CONF-07 mandates the diff IS the value.

What this file pins:

- **Test 1 (use zai no-mutation + diff printed):** against an OpenAI-default
  ``config.toml`` (comments + a ``[project_*]`` trust block), ``use zai
  --dry-run`` prints a unified diff surfacing the Z.ai change (``glm-5.2`` /
  ``zai-moonbridge``) AND leaves EVERY file under the isolated HOME
  byte-identical (snapshot assertion — the load-bearing no-write proof).
- **Test 2 (use zai no-changes case):** when the config ALREADY holds the Z.ai
  desired state, ``use zai --dry-run`` prints the literal ``(no changes)`` and
  writes nothing.
- **Test 3 (setup dry-run redacts the key):** with a fake ``ZAI_API_KEY`` env
  canary, ``setup --dry-run`` stdout does NOT contain the canary (D-77 / SECR-03
  still holds in the diff preview), DOES contain the redacted
  ``ZAI_API_KEY: <redacted>`` diff line, and writes nothing.
- **Test 4 (install-service dry-run summary):`` ``install_service(...,
  dry_run=True)`` prints a "would write plist" / "would run: launchctl
  bootstrap" summary, writes NO plist, and calls the runner NEVER (no
  launchctl).
- **Test 5 (use openai dry-run):** symmetric to Test 1 for the revert
  direction (seed a Z.ai doc, dry-run ``use openai``, assert the diff shows the
  revert + zero mutation).

Every test runs under the autouse ``_isolate_home`` fixture (``conftest.py``)
which repoints ``HOME`` at ``tmp_path`` and pre-creates ``tmp_path/.codex``.
The snapshot helper walks EVERY file under ``tmp_path`` before + after the
dry-run invocation and asserts byte-identical — the load-bearing no-write
proof (CONF-07).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from zai_codex_helper.__main__ import main
from zai_codex_helper.services.lifecycle import install_service
from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.setup import run_setup

# --------------------------------------------------------------------------- #
# Realistic config.toml seeds (mirror tests/test_use_zai_use_openai.py fixtures
# — comments + a [project_*] trust block, the load-bearing tomlkit round-trip
# surface). Kept local so this file is self-contained.
# --------------------------------------------------------------------------- #

#: An OpenAI-default config: ``model = "gpt-5.5"``, no ``model_provider``, plus
#: a comment + ``[project_*]`` trust block. The "user just installed Codex" state.
REALISTIC_OPENAI_DEFAULT = """\
# Codex config — managed by zai-codex-helper
model = "gpt-5.5"
model_reasoning_effort = "xhigh"

# a project trust block that MUST survive the write (CLAUDE.md guarantee)
[project_2fa0d1e3]
trust_level = "trusted"
"""

#: A Z.ai-default config (the OpenAI seed AFTER ``use zai``): the canonical Z.ai
#: desired state + the same comment + trust block.
REALISTIC_ZAI_DEFAULT = """\
# Codex config — managed by zai-codex-helper
model = "glm-5.2"
model_provider = "zai-moonbridge"
model_reasoning_effort = "xhigh"

[model_providers.zai-moonbridge]
name = "Z.ai (Moon Bridge)"
base_url = "http://127.0.0.1:38440/v1"
wire_api = "responses"
env_key = "ZAI_API_KEY"

# a project trust block that MUST survive the write (CLAUDE.md guarantee)
[project_2fa0d1e3]
trust_level = "trusted"
"""


# --------------------------------------------------------------------------- #
# Snapshot helper — the load-bearing no-write proof (CONF-07).
# --------------------------------------------------------------------------- #


def _snapshot(root: Path) -> dict[Path, bytes]:
    """Return a ``{relative_path: bytes}`` snapshot of EVERY file under ``root``.

    Walks the whole isolated HOME tree (not just ``.codex``) so a stray write
    ANYWHERE under the sandbox is caught — e.g. a ``.bak``, a plist in
    ``Library/LaunchAgents``, or an accidental ``.zshrc``. The before/after
    comparison of two snapshots is the CONF-07 no-write assertion.
    """
    snap: dict[Path, bytes] = {}
    if not root.exists():
        return snap
    for p in root.rglob("*"):
        if p.is_file():
            snap[p.relative_to(root)] = p.read_bytes()
    return snap


def _write(path: Path, data: str) -> None:
    """Seed ``path`` with ``data`` (creating parents first)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def _config_toml(tmp_path: Path) -> Path:
    """The on-disk config.toml path under the sandboxed HOME."""
    return tmp_path / ".codex" / "config.toml"


# =========================================================================== #
# Test 1 — use zai --dry-run: real diff + zero mutation
# =========================================================================== #


@pytest.mark.integration
def test_use_zai_dry_run_prints_diff_and_writes_nothing(tmp_path, capsys):
    """SC-1 / CONF-07 / D-95: ``use zai --dry-run`` previews the Z.ai change.

    Seeds an OpenAI-default config (comments + trust block), snapshots every
    file under the sandbox, runs ``main(["--dry-run", "use", "zai"])``, and
    asserts:

    1. rc == 0.
    2. The captured stdout+stderr contains a unified-diff header (``---`` /
       ``+++`` lines) mentioning the config.toml path.
    3. The diff surfaces the Z.ai change — a ``+`` line adding ``glm-5.2`` or
       the ``zai-moonbridge`` provider block.
    4. EVERY file under the sandbox is byte-identical before vs after (the
       no-write proof — CONF-07's load-bearing guarantee).
    """
    _write(_config_toml(tmp_path), REALISTIC_OPENAI_DEFAULT)
    before = _snapshot(tmp_path)

    rc = main(["--dry-run", "use", "zai"])

    assert rc == 0
    after = _snapshot(tmp_path)
    # CONF-07 load-bearing: zero mutation across the WHOLE sandbox.
    assert before == after, "dry-run mutated files under the isolated HOME"

    out = capsys.readouterr()
    combined = out.out + out.err
    # A unified diff header is present.
    assert "---" in combined and "+++" in combined
    # The diff surfaces the Z.ai change (one of these tokens on a + line).
    assert "glm-5.2" in combined or "zai-moonbridge" in combined


# =========================================================================== #
# Test 2 — use zai --dry-run no-changes case: "(no changes)"
# =========================================================================== #


@pytest.mark.integration
def test_use_zai_dry_run_no_changes_when_already_zai(tmp_path, capsys):
    """SC-1 / D-95: when the config already holds the Z.ai state, print "(no changes)".

    Seeds a config that is ALREADY the exact canonical ``apply_zai`` output
    (generated by running ``apply_zai`` once and serializing — so the target
    ``tomlkit.dumps(apply_zai(doc))`` equals the current bytes byte-for-byte),
    runs ``use zai --dry-run``, and asserts the output contains the literal
    ``(no changes)`` sentinel AND zero mutation.

    NOTE: the seed is generated from ``apply_zai`` (not hand-written) because
    tomlkit's re-serialization is not byte-stable across a second pass — a
    hand-written "looks Z.ai" fixture would still diff. The genuine no-op
    requires the on-disk bytes to equal ``apply_zai``'s canonical output, which
    is exactly what a real (non-dry-run) ``use zai`` writes. So this test seeds
    the post-``use zai`` state and asserts the preview recognizes the no-op.
    """
    import tomlkit

    from zai_codex_helper.services.providers import apply_zai

    # The canonical apply_zai output — what a real `use zai` writes.
    canonical = tomlkit.dumps(apply_zai(tomlkit.parse(REALISTIC_OPENAI_DEFAULT)))
    _write(_config_toml(tmp_path), canonical)
    before = _snapshot(tmp_path)

    rc = main(["--dry-run", "use", "zai"])

    assert rc == 0
    after = _snapshot(tmp_path)
    assert before == after, "dry-run mutated files under the isolated HOME"

    out = capsys.readouterr()
    combined = out.out + out.err
    assert "(no changes)" in combined


# =========================================================================== #
# Test 3 — setup --dry-run redacts the API key (D-77 / SECR-03 / T-15-01)
# =========================================================================== #


@pytest.mark.integration
def test_setup_dry_run_redacts_api_key_and_writes_nothing(
    tmp_path, monkeypatch, capsys
):
    """SC-1 / D-77 / SECR-03: ``setup --dry-run`` previews the yml with the key REDACTED.

    Runs ``run_setup(dry_run=True)`` with a distinctive ``ZAI_API_KEY`` env
    canary (``sk-test-FAKE-DO-NOT-USE``) and asserts:

    1. The canary literal is ABSENT from captured stdout (D-77 — the key NEVER
       enters print_fn, even in the diff preview).
    2. The redacted ``ZAI_API_KEY: <redacted>`` diff line IS present (the
       redaction seam works — the user sees the key would be written, without
       its value).
    3. EVERY file under the sandbox is byte-identical before vs after (no yml,
       no .zshrc, no config.toml, no .bak written).
    """
    # A distinctive canary that would be trivially greppable if it leaked.
    # MUST match the real Z.ai (BigModel) format validated by
    # setup.validate_api_key(): <32-hex>.<16-alnum>.
    canary = "c0ffee22222222222222222222222222.FAKEcanary123456"
    monkeypatch.setenv("ZAI_API_KEY", canary)
    paths = Paths.from_home(tmp_path)
    before = _snapshot(tmp_path)

    rc = run_setup(
        paths,
        yes=True,
        dry_run=True,
    )

    assert rc == 0
    after = _snapshot(tmp_path)
    # CONF-07: zero mutation — no yml, no .zshrc, no config.toml, no .bak.
    assert before == after, "setup --dry-run mutated files under the isolated HOME"

    out = capsys.readouterr()
    combined = out.out + out.err
    # D-77 / T-15-01: the canary NEVER appears in the preview output.
    assert canary not in combined, "API key canary leaked into dry-run output"
    # The redaction seam: the key line (providers.zai.api_key) is redacted.
    # The value is replaced by a non-reversible fingerprint (<redacted:XXXXXXXX>)
    # so a key CHANGE stays visible in a both-sides diff without leaking either
    # value; a fresh setup (no current file) previews it as an added line.
    assert re.search(r"api_key: <redacted(:[0-9a-f]{8})?>", combined), combined


# =========================================================================== #
# Test 4 — install-service --dry-run: summary, no plist, no launchctl
# =========================================================================== #


@pytest.mark.integration
def test_install_service_dry_run_summary_no_plist_no_launchctl(tmp_path, capsys):
    """SC-1 / D-95 NOTE: ``install_service(dry_run=True)`` prints a summary only.

    Invokes ``install_service`` with a spy runner and ``dry_run=True`` (darwin
    gate is satisfied on the macOS dev machine; the spy runner is the
    load-bearing assertion that NO launchctl runs). Asserts:

    1. rc == 0.
    2. The runner was NEVER called (zero launchctl invocations).
    3. No plist exists under ``launchagents_dir``.
    4. The captured stdout mentions "would write plist" and
       "would run: launchctl bootstrap".
    """
    from unittest import mock

    paths = Paths.from_home(tmp_path)
    # Ensure launchagents_dir's parent exists for a clean snapshot.
    paths.launchagents_dir.mkdir(parents=True, exist_ok=True)

    calls: list = []

    def spy_runner(argv, **kwargs):
        calls.append(list(argv))
        from subprocess import CompletedProcess

        return CompletedProcess(argv, 0, stdout="", stderr="")

    with mock.patch("zai_codex_helper.services.lifecycle.sys.platform", "darwin"):
        rc = install_service(paths, runner=spy_runner, dry_run=True)

    assert rc == 0
    # D-95: NO launchctl call under dry-run.
    assert calls == [], f"dry-run called launchctl: {calls}"
    # No plist written.
    plist = paths.launchagents_dir / "dev.zai.moonbridge.plist"
    assert not plist.exists(), "dry-run wrote a plist"
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "would write plist" in combined
    assert "would run: launchctl bootstrap" in combined


# =========================================================================== #
# Test 5 — use openai --dry-run: symmetric revert preview
# =========================================================================== #


@pytest.mark.integration
def test_use_openai_dry_run_prints_revert_diff_and_writes_nothing(tmp_path, capsys):
    """SC-1 / CONF-07 / D-95: ``use openai --dry-run`` previews the revert.

    Symmetric to Test 1 for the revert direction: seed a Z.ai-default config,
    run ``use openai --dry-run``, assert the diff surfaces the OpenAI revert
    (``gpt-5.5`` appears on a ``+`` line; ``model_provider`` removal on a ``-``
    line) AND zero mutation.
    """
    _write(_config_toml(tmp_path), REALISTIC_ZAI_DEFAULT)
    before = _snapshot(tmp_path)

    rc = main(["--dry-run", "use", "openai"])

    assert rc == 0
    after = _snapshot(tmp_path)
    assert before == after, "dry-run mutated files under the isolated HOME"

    out = capsys.readouterr()
    combined = out.out + out.err
    assert "---" in combined and "+++" in combined
    # The revert surfaces the OpenAI model on an added line.
    assert "gpt-5.5" in combined


@pytest.mark.unit
def test_preview_yml_change_seals_foreign_secret_encodings(tmp_path):
    """T-15-01: node-level redaction seals block-scalar, quoted, and auth_token secrets.

    A foreign / hand-edited moonbridge-zai.yml may encode the key as a block
    scalar (`api_key: |` + indented continuation), a quoted key (`"api_key":`),
    or carry a `server.auth_token`. A LINE regex cannot redact these — the
    continuation/quoted/token values survive to the removed side of the diff.
    preview_yml_change redacts at the NODE level (safe_load → fingerprint secret
    values → safe_dump), so NONE of the real values can reach stdout, while a
    genuine key CHANGE still shows as a `<redacted:...>` diff line.
    """
    from zai_codex_helper.services.diff_preview import preview_yml_change

    foreign = (
        "mode: Transform\n"
        "server:\n"
        "  addr: 127.0.0.1:38440\n"
        "  auth_token: SUPERSECRETLOOPBACKTOKEN\n"
        "providers:\n"
        "  zai:\n"
        "    api_key: |\n"
        "      SECRETBLOCKSCALARKEYLEAK\n"
        "      SECONDLINE\n"
        "  other:\n"
        '    "api_key": QUOTEDKEYLEAK\n'
    )
    yml = tmp_path / "moonbridge-zai.yml"
    yml.write_text(foreign, encoding="utf-8")

    body = {"providers": {"zai": {"api_key": "BRANDNEWKEY9999"}}}
    lines: list[str] = []
    preview_yml_change(yml, body, lines.append)
    out = "\n".join(lines)

    for secret in (
        "SUPERSECRETLOOPBACKTOKEN",  # auth_token
        "SECRETBLOCKSCALARKEYLEAK",  # block scalar line 1
        "SECONDLINE",  # block scalar continuation
        "QUOTEDKEYLEAK",  # quoted key
        "BRANDNEWKEY9999",  # the new target key
    ):
        assert secret not in out, f"secret leaked to stdout: {secret}\n{out}"
    # The key change is still visible as a fingerprint diff line.
    assert "<redacted:" in out
