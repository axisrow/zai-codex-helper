"""Phase 7 Plan 01 — on-disk end-to-end tests for the Core Value.

This file pins the four ROADMAP Phase 7 Success Criteria by driving the REAL
``main(["use","zai"])`` / ``main(["use","openai"])`` path against a seeded
``tmp_path/.codex/config.toml`` and then reading the file BACK FROM DISK to
assert the on-disk state — not the in-memory transform. Phase 6 already
proved the transforms are correct in memory; Phase 7 proves they survive the
full ``read -> transform -> write_canonical`` round-trip through the real
backend, real atomic_write, and real BackupCoordinator gate.

What this file pins:

- **SC-1 (PROV-01):** ``use zai`` writes ``model="glm-5.2"``,
  ``model_provider="zai-moonbridge"``, ``model_reasoning_effort="xhigh"``,
  and the ``[model_providers.zai-moonbridge]`` block with
  ``wire_api="responses"`` + the Moon Bridge ``base_url`` — all read back
  from the REAL on-disk file.
- **SC-2 (PROV-02):** ``use openai`` reverts to ``model="gpt-5.5"``, REMOVES
  ``model_provider``, AND PRESERVES the ``[model_providers.zai-moonbridge]``
  block (reversible).
- **SC-3 (PROV-04):** every successful write emits the restart warning on
  STDERR (not stdout), conveying the three D-47 facts.
- **SC-4 (CONF-06, D-48):** ``use zai`` twice produces byte-identical
  ``config.toml`` (no duplicate provider blocks); same for ``use openai``.
- **D-45 step 3 (fresh install):** with NO ``config.toml`` present,
  ``use zai`` creates it and returns 0 (does NOT raise
  ``no config to back up``).
- **D-11 end-to-end:** a forced postcondition violation surfaces through
  ``main()`` as a one-line ``error: ...`` on stderr + exit 1, no traceback;
  ``--debug`` re-raises.
- **Comments + ``[project_*]`` trust blocks survive** the real write
  (CLAUDE.md load-bearing tomlkit guarantee, exercised through the pipeline).
- **Handler dispatch:** ``use zai`` / ``use openai`` resolve to real named
  handlers, not stub closures.

Every test runs under the autouse ``_isolate_home`` fixture (``conftest.py``)
which repoints ``HOME`` at ``tmp_path`` and pre-creates ``tmp_path/.codex``.
``Paths.default()`` calls ``Path.home()``, so it resolves under the sandbox —
no real-HOME write, no monkeypatching of ``Paths`` required (D-46). Tests
seed ``tmp_path / ".codex" / "config.toml"`` directly and read it back.

Style mirrors ``tests/test_restore.py`` (``main`` + ``ZaiCodexHelperError``
from ``zai_codex_helper.__main__``, ``build_parser`` from
``zai_codex_helper.cli.parser``, a module-level ``_write`` helper,
``capsys`` for stdout/stderr).
"""

from __future__ import annotations

import pytest
import tomlkit

from zai_codex_helper.__main__ import ZaiCodexHelperError, main
from zai_codex_helper.cli.parser import build_parser
from zai_codex_helper.services.providers import (
    OPENAI_MODEL,
    ZAI_MODEL,
    ZAI_PROVIDER_BLOCK,
    ZAI_PROVIDER_ID,
    ZAI_REASONING_EFFORT,
)

# --------------------------------------------------------------------------- #
# Realistic Codex config.toml seeds (with comments + a `[project_*]` trust
# block — the load-bearing tomlkit round-trip surface). These mirror the
# Phase 6 fixture style (tests/test_providers.py) so the same canonical shape
# is asserted at both the in-memory and on-disk tiers.
# --------------------------------------------------------------------------- #

#: An OpenAI-default config: top comment, ``model = "gpt-5.5"``, NO
#: ``model_provider``, NO ``[model_providers.*]``, and a ``[project_*]`` trust
#: block with a comment inside it. The "user just installed Codex" state.
REALISTIC_OPENAI_DEFAULT = """\
# Codex config — managed by zai-codex-helper
model = "gpt-5.5"
model_reasoning_effort = "xhigh"

# a project trust block that MUST survive the write (CLAUDE.md guarantee)
[project_2fa0d1e3]
trust_level = "trusted"
"""

#: A Z.ai-default config (the OpenAI seed AFTER ``use zai``): the canonical
#: Z.ai desired state plus the same comment + ``[project_*]`` trust block. Used
#: as the seed for the ``use openai`` revert tests so the "block survives" and
#: "comments survive" assertions run against a realistic post-``use zai`` file.
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


def _write(path, data: bytes | str) -> None:
    """Seed ``path`` with ``data`` (bytes or str), creating parents first.

    Mirrors ``tests/test_restore.py::_write``: ``parent.mkdir(parents=True)``
    then ``write_bytes`` (encoding the str to UTF-8 if a str is passed, since
    the fixtures above are ``str``).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)


def _config_toml(tmp_path):
    """The on-disk config.toml path under the sandboxed HOME."""
    return tmp_path / ".codex" / "config.toml"


def _read_back(path) -> tomlkit.TOMLDocument:
    """Read ``config.toml`` back from disk into a live TOMLDocument.

    The on-disk read is the load-bearing assertion primitive for SC-1/SC-2/SC-4:
    it proves the file's bytes (not an in-memory doc) hold the expected state.
    """
    return tomlkit.parse(path.read_text(encoding="utf-8"))


# =========================================================================== #
# SC-1 (PROV-01) — `use zai` makes Z.ai the default ON DISK
# =========================================================================== #


@pytest.mark.integration
def test_use_zai_makes_zai_default_on_disk_sc1(tmp_path):
    """SC-1 / PROV-01: `use zai` writes the canonical Z.ai state to the REAL file."""
    cfg = _config_toml(tmp_path)
    _write(cfg, REALISTIC_OPENAI_DEFAULT)

    rc = main(["use", "zai"])

    assert rc == 0
    # Read the file BACK FROM DISK and assert the canonical Z.ai state — this
    # pins PROV-01 against the real on-disk bytes, not an in-memory transform.
    doc = _read_back(cfg)
    assert doc["model"] == ZAI_MODEL  # "glm-5.2"
    assert doc["model_provider"] == ZAI_PROVIDER_ID  # "zai-moonbridge"
    assert doc["model_reasoning_effort"] == ZAI_REASONING_EFFORT  # "xhigh"
    # The provider block on disk — wire_api="responses" is LOAD-BEARING (PROV-03).
    block = doc["model_providers"][ZAI_PROVIDER_ID]
    assert block["wire_api"] == "responses"
    assert block["base_url"] == ZAI_PROVIDER_BLOCK["base_url"]
    assert block["env_key"] == ZAI_PROVIDER_BLOCK["env_key"]


@pytest.mark.integration
def test_use_zai_preserves_config_toml_0644_mode(tmp_path):
    """#27: `use zai` over a 0644 config.toml keeps it 0644 (does not narrow to 0600).

    config.toml holds no secret; CLAUDE.md says preserve the user's existing mode.
    Before the atomic_write fix, the patched file inherited the temp's ~0600.
    """
    import os
    import stat

    cfg = _config_toml(tmp_path)
    _write(cfg, REALISTIC_OPENAI_DEFAULT)
    os.chmod(cfg, 0o644)
    assert stat.S_IMODE(os.stat(cfg).st_mode) == 0o644

    assert main(["use", "zai"]) == 0

    assert stat.S_IMODE(os.stat(cfg).st_mode) == 0o644, (
        "use zai must preserve the user's 0644 config.toml, not narrow it"
    )


# =========================================================================== #
# SC-2 (PROV-02) — `use openai` reverts AND preserves the Z.ai block (reversible)
# =========================================================================== #


@pytest.mark.integration
def test_use_openai_reverts_and_preserves_zai_block_sc2(tmp_path):
    """SC-2 / PROV-02: `use openai` reverts to OpenAI default + Z.ai block survives."""
    cfg = _config_toml(tmp_path)
    _write(cfg, REALISTIC_ZAI_DEFAULT)

    rc = main(["use", "openai"])

    assert rc == 0
    doc = _read_back(cfg)
    assert doc["model"] == OPENAI_MODEL  # "gpt-5.5"
    # model_provider key is REMOVED — Codex falls back to its builtin OpenAI.
    assert "model_provider" not in doc
    # The Z.ai block is STILL PRESENT on disk (reversible — a later `use zai`
    # does not need to recreate it).
    assert ZAI_PROVIDER_ID in doc["model_providers"]
    assert doc["model_providers"][ZAI_PROVIDER_ID]["wire_api"] == "responses"


@pytest.mark.integration
def test_use_then_round_trip_zai_openai_zai(tmp_path):
    """End-to-end reversibility: use zai -> use openai -> use zai on disk."""
    cfg = _config_toml(tmp_path)
    _write(cfg, REALISTIC_OPENAI_DEFAULT)

    # 1. use zai -> Z.ai default on disk
    assert main(["use", "zai"]) == 0
    doc = _read_back(cfg)
    assert doc["model"] == ZAI_MODEL
    assert doc["model_provider"] == ZAI_PROVIDER_ID

    # 2. use openai -> OpenAI default + Z.ai block survives
    assert main(["use", "openai"]) == 0
    doc = _read_back(cfg)
    assert doc["model"] == OPENAI_MODEL
    assert "model_provider" not in doc
    assert ZAI_PROVIDER_ID in doc["model_providers"]

    # 3. use zai again -> Z.ai default on disk (block was preserved, reused)
    assert main(["use", "zai"]) == 0
    doc = _read_back(cfg)
    assert doc["model"] == ZAI_MODEL
    assert doc["model_provider"] == ZAI_PROVIDER_ID
    assert doc["model_providers"][ZAI_PROVIDER_ID]["wire_api"] == "responses"


# =========================================================================== #
# SC-3 (PROV-04) — restart warning on STDERR, NOT stdout
# =========================================================================== #


@pytest.mark.integration
def test_restart_warning_on_stderr_after_use_zai_sc3(tmp_path, capsys):
    """SC-3 / PROV-04: `use zai` writes the restart warning to STDERR (not stdout)."""
    _write(_config_toml(tmp_path), REALISTIC_OPENAI_DEFAULT)

    rc = main(["use", "zai"])

    assert rc == 0
    out, err = capsys.readouterr()
    # The three D-47 facts are substrings of STDERR.
    # (a) the config was written
    assert "written" in err.lower()
    # (b) the Desktop App does NOT live-reload
    assert "does not live-reload" in err.lower()
    # (c) a restart is required
    assert "restart" in err.lower()
    # The warning is NOT on stdout (so a `... | grep` over stdout stays clean).
    assert "restart" not in out.lower()
    assert "written" not in out.lower()


@pytest.mark.integration
def test_restart_warning_on_stderr_after_use_openai(tmp_path, capsys):
    """SC-3 / PROV-04 (companion): `use openai` ALSO warns on stderr."""
    _write(_config_toml(tmp_path), REALISTIC_ZAI_DEFAULT)

    assert main(["use", "openai"]) == 0
    out, err = capsys.readouterr()
    assert "restart" in err.lower()
    assert "does not live-reload" in err.lower()
    assert "restart" not in out.lower()


# =========================================================================== #
# SC-4 (CONF-06, D-48) — byte-identical double-write (idempotence on disk)
# =========================================================================== #


@pytest.mark.integration
def test_use_zai_twice_byte_identical_sc4(tmp_path):
    """SC-4 / CONF-06 / D-48: `use zai` twice -> byte-identical config.toml."""
    cfg = _config_toml(tmp_path)
    _write(cfg, REALISTIC_OPENAI_DEFAULT)

    assert main(["use", "zai"]) == 0
    first = cfg.read_bytes()

    assert main(["use", "zai"]) == 0
    second = cfg.read_bytes()

    # Byte-identical — the upsert replace-not-append + pure idempotent
    # transform means the second write changes nothing.
    assert first == second
    # And exactly ONE [model_providers.zai-moonbridge] header in the raw text
    # (no duplicate blocks accumulate — the replace-not-append chokepoint).
    text = second.decode("utf-8")
    assert text.count("[model_providers.zai-moonbridge]") == 1


@pytest.mark.integration
def test_use_openai_twice_byte_identical(tmp_path):
    """SC-4 / CONF-06 / D-48 (companion): `use openai` twice -> byte-identical."""
    cfg = _config_toml(tmp_path)
    _write(cfg, REALISTIC_ZAI_DEFAULT)

    assert main(["use", "openai"]) == 0
    first = cfg.read_bytes()

    assert main(["use", "openai"]) == 0
    second = cfg.read_bytes()

    assert first == second
    # The Z.ai block survives BOTH writes (still exactly one).
    text = second.decode("utf-8")
    assert text.count("[model_providers.zai-moonbridge]") == 1


# =========================================================================== #
# D-45 step 3 — fresh install: missing config.toml is seeded, not an error
# =========================================================================== #


@pytest.mark.integration
def test_use_zai_seeds_missing_config_then_writes(tmp_path):
    """D-45 step 3: no config.toml -> `use zai` creates it, returns 0 (no raise).

    BackupCoordinator.backup_once raises ``no config to back up`` when the
    source is absent; the pipeline MUST seed-if-missing BEFORE backup_once.
    This test proves that ordering: on a fresh install (no config), `use zai`
    succeeds and writes the Z.ai default.
    """
    cfg = _config_toml(tmp_path)
    # No config.toml present (the .codex dir is pre-created by _isolate_home).
    assert not cfg.exists()

    rc = main(["use", "zai"])

    assert rc == 0
    # The file now exists with the Z.ai default on disk.
    assert cfg.exists()
    doc = _read_back(cfg)
    assert doc["model"] == ZAI_MODEL
    assert doc["model_provider"] == ZAI_PROVIDER_ID
    assert doc["model_reasoning_effort"] == ZAI_REASONING_EFFORT
    # The sentinel-gated one-shot backup fired against the freshly-seeded empty
    # doc, so a sibling .bak now exists (idempotency token for future runs).
    assert (cfg.parent / (cfg.name + ".zai-codex-helper.bak")).exists()


# =========================================================================== #
# CLAUDE.md load-bearing tomlkit guarantee — comments + trust blocks survive
# =========================================================================== #


@pytest.mark.integration
def test_comments_and_trust_block_survive_use_zai(tmp_path):
    """Comments + `[project_*]` trust blocks survive the real write pipeline.

    This is the CLAUDE.md load-bearing tomlkit guarantee exercised end-to-end
    through the REAL pipeline (read -> transform -> write_canonical), not a
    Phase 5 backend unit test. A user's ``[project_*]`` trust blocks and
    comments MUST survive a ``use zai`` round-trip verbatim — corrupting them
    would silently break Codex's project-trust resolution.
    """
    cfg = _config_toml(tmp_path)
    _write(cfg, REALISTIC_OPENAI_DEFAULT)

    assert main(["use", "zai"]) == 0

    raw = cfg.read_text(encoding="utf-8")
    # The original top comment survives.
    assert "# Codex config — managed by zai-codex-helper" in raw
    # The [project_*] trust block header survives.
    assert "[project_2fa0d1e3]" in raw
    assert 'trust_level = "trusted"' in raw
    # And the on-disk doc still parses + carries the trust block.
    doc = _read_back(cfg)
    assert doc["project_2fa0d1e3"]["trust_level"] == "trusted"


# =========================================================================== #
# D-11 — error contract end-to-end through the new handlers
# =========================================================================== #


@pytest.mark.integration
def test_postcondition_violation_surfaces_via_main_d11(tmp_path, capsys):
    """D-11: a postcondition violation -> `main()` returns 1 + one-line `error:` on stderr, no traceback.

    Seeds a config that redefines the reserved ``openai`` provider id —
    ``apply_zai`` does NOT remove it (it only owns the ``zai-moonbridge``
    block + top-level keys), so it survives into the post-write doc and
    ``check_postconditions`` raises on the reserved-id redefinition. The
    handler does NOT catch it (D-11/D-45); ``main()`` formats the one-line
    error.
    """
    cfg = _config_toml(tmp_path)
    _write(
        cfg,
        # A config with a reserved-id block that apply_zai will NOT remove.
        'model = "gpt-5.5"\n\n[model_providers.openai]\nname = "shadow"\n',
    )

    rc = main(["use", "zai"])

    assert rc == 1
    out, err = capsys.readouterr()
    # stdout empty on the error path.
    assert out == ""
    # Exactly one non-empty stderr line starting with `error:`.
    non_empty = [line for line in err.splitlines() if line.strip()]
    assert len(non_empty) == 1
    assert non_empty[0].startswith("error:")
    # No traceback / no exception class name leaks without --debug.
    assert "Traceback" not in err
    assert "ZaiCodexHelperError" not in err


@pytest.mark.integration
def test_debug_reraises_postcondition_violation(tmp_path):
    """D-11 --debug: a postcondition violation re-raises ZaiCodexHelperError."""
    cfg = _config_toml(tmp_path)
    _write(
        cfg,
        'model = "gpt-5.5"\n\n[model_providers.openai]\nname = "shadow"\n',
    )

    with pytest.raises(ZaiCodexHelperError):
        main(["--debug", "use", "zai"])


# =========================================================================== #
# Handler dispatch (unit — no disk IO beyond parse)
# =========================================================================== #


@pytest.mark.unit
def test_use_zai_is_real_handler_not_stub():
    """`use zai` dispatches to the real _handle_use_zai (not a stub closure).

    A stub closure is named ``handler``; the real handler is a named module
    function. This is the D-03 swap (Phase 1 stub -> Phase 7 real).
    """
    args = build_parser().parse_args(["use", "zai"])
    assert args.cmd == "use"
    assert args.provider == "zai"
    assert args.func.__name__ == "_handle_use_zai"


@pytest.mark.unit
def test_use_openai_is_real_handler_not_stub():
    """`use openai` dispatches to the real _handle_use_openai (not a stub closure)."""
    args = build_parser().parse_args(["use", "openai"])
    assert args.cmd == "use"
    assert args.provider == "openai"
    assert args.func.__name__ == "_handle_use_openai"


@pytest.mark.unit
def test_use_help_exits_zero(capsys):
    """`use --help` and top-level `--help` exit 0; `use` is listed in top help."""
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["use", "--help"])
    assert exc.value.code == 0

    with pytest.raises(SystemExit) as exc2:
        build_parser().parse_args(["--help"])
    assert exc2.value.code == 0
    out, _ = capsys.readouterr()
    # Top-level --help lists the `use` command.
    assert "use" in out
