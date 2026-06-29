"""Phase 8 Plan 01 — on-disk tests for the read-only ``status`` command.

This file pins the two ROADMAP Phase 8 Success Criteria by driving the REAL
``main(["status"])`` path against seeded ``tmp_path/.codex/config.toml`` states
and asserting on stdout/stderr + exit codes:

- **SC-1 (PROV-05, D-50):** ``status`` prints three glanceable plain-text
  sections — Provider (the active default: Z.ai vs OpenAI builtin, with
  ``model`` + ``model_reasoning_effort`` values), Config paths (every
  ``Paths.default()``-resolved location with ``[exists]``/``[missing]``
  markers), and Version (the package name + ``__version__``).
- **SC-2 (D-51, D-52):** ``status`` is STRICTLY read-only. It provably writes
  nothing — the tmp HOME's contents (file list + every file's sha256) are
  byte-identical before/after ``status`` across three seed states (Z.ai
  present, OpenAI present, config absent). It exits 0 on a parseable config
  AND on a missing config (missing != broken), and exits 1 on a broken
  (malformed-TOML) config via main()'s D-11 one-line ``error:`` contract with
  no traceback unless ``--debug``.

Provider detection follows D-53 (``model_provider`` key truth, NOT ``model``
inference). A static AST guard (mirroring the ``test_providers.py`` purity
guard) asserts the status code path references NO mutator names
(``write_canonical``, ``backup_once``, ``atomic_write``, ``os.replace``,
``os.chmod``, ``unlink``, ``mkdir``, ``rename``) — the load-bearing read-only
invariant (T-08-01, D-51).

Every test runs under the autouse ``_isolate_home`` fixture (``conftest.py``)
which repoints ``HOME`` at ``tmp_path`` and pre-creates ``tmp_path/.codex``.
``Paths.default()`` calls ``Path.home()``, so it resolves under the sandbox —
no real-HOME read or write, no monkeypatching of ``Paths`` required (D-46).

Style mirrors ``tests/test_use_zai_use_openai.py`` (``main`` +
``ZaiCodexHelperError`` from ``zai_codex_helper.__main__``, ``build_parser``
from ``zai_codex_helper.cli.parser``, a module-level ``_write`` helper,
``capsys`` for stdout/stderr).
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from zai_codex_helper import __version__
from zai_codex_helper.__main__ import ZaiCodexHelperError, main
from zai_codex_helper.cli.parser import build_parser
from zai_codex_helper.services.paths import Paths
from zai_codex_helper.services.providers import (
    OPENAI_MODEL,
    ZAI_MODEL,
    ZAI_PROVIDER_ID,
    ZAI_REASONING_EFFORT,
)

# --------------------------------------------------------------------------- #
# Realistic Codex config.toml seeds (the same canonical shapes Phase 7 uses).
# --------------------------------------------------------------------------- #

#: A Z.ai-active config: the post-``use zai`` state. ``model_provider`` truth
#: is what detection keys on (D-53).
ZAI_ACTIVE_CONFIG = """\
# Codex config — managed by zai-codex-helper
model = "glm-5.2"
model_provider = "zai-moonbridge"
model_reasoning_effort = "xhigh"

[model_providers.zai-moonbridge]
name = "Z.ai (Moon Bridge)"
base_url = "http://127.0.0.1:38440/v1"
wire_api = "responses"
env_key = "ZAI_API_KEY"
"""

#: An OpenAI-default config: NO ``model_provider`` key. Codex falls back to its
#: builtin OpenAI provider — this is the "user just installed Codex" state and
#: the post-``use openai`` state. Detection reports OpenAI builtin default.
OPENAI_DEFAULT_CONFIG = """\
# Codex config — managed by zai-codex-helper
model = "gpt-5.5"
model_reasoning_effort = "xhigh"
"""

#: A misconfig (D-53): carries a Z.ai model value but NO ``model_provider``
#: pointer. Detection must report OpenAI builtin default (do NOT infer provider
#: from ``model`` alone).
MISCONFIG_MODEL_WITHOUT_PROVIDER = """\
model = "glm-5.2"
"""

#: Broken (malformed) TOML — an unterminated string. ``tomlkit.parse`` raises;
#: the read boundary translates it to ``ZaiCodexHelperError`` so main()'s D-11
#: formatter owns the one-line ``error:`` + exit 1 (D-52, T-08-02).
BROKEN_CONFIG = 'model = "glm-5.2\n'


def _write(path, data: bytes | str) -> None:
    """Seed ``path`` with ``data`` (bytes or str), creating parents first.

    Mirrors ``tests/test_use_zai_use_openai.py::_write``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)


def _config_toml(tmp_path) -> Path:
    """The on-disk config.toml path under the sandboxed HOME."""
    return tmp_path / ".codex" / "config.toml"


def _snapshot(root: Path) -> tuple[set[str], dict[str, str]]:
    """Walk ``root`` recursively and return ``(rel-paths, rel-path -> sha256)``.

    The read-only proof primitive (SC-2 / D-51). Captures BOTH the set of
    relative paths (posix, so a create/delete shows up as a set delta) AND the
    sha256 of every file's bytes (so an in-place mutation shows up as a hash
    delta). Two equal snapshots mean nothing was created, modified, or deleted.
    """
    rel_paths: set[str] = set()
    hashes: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            rel_paths.add(rel)
            hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return rel_paths, hashes


# =========================================================================== #
# SC-1 (PROV-05, D-50) — provider section
# =========================================================================== #


@pytest.mark.integration
def test_status_zai_active_prints_provider_section_sc1(tmp_path, capsys):
    """SC-1 / D-50 / D-53: Z.ai-active config -> stdout names Z.ai as default."""
    _write(_config_toml(tmp_path), ZAI_ACTIVE_CONFIG)

    rc = main(["status"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Z.ai" in out
    assert ZAI_MODEL in out  # "glm-5.2"
    assert ZAI_REASONING_EFFORT in out  # "xhigh"


@pytest.mark.integration
def test_status_openai_default_prints_provider_section(tmp_path, capsys):
    """SC-1 / D-50 / D-53: no model_provider -> OpenAI builtin default."""
    _write(_config_toml(tmp_path), OPENAI_DEFAULT_CONFIG)

    rc = main(["status"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "OpenAI" in out
    assert OPENAI_MODEL in out  # "gpt-5.5"


@pytest.mark.integration
def test_status_detection_by_model_provider_not_model_sc53(tmp_path, capsys):
    """D-53: a config with model="glm-5.2" but NO model_provider is OpenAI default.

    Detection is by ``model_provider`` truth, NOT by inferring from ``model``.
    """
    _write(_config_toml(tmp_path), MISCONFIG_MODEL_WITHOUT_PROVIDER)

    rc = main(["status"])

    assert rc == 0
    out = capsys.readouterr().out
    # OpenAI builtin default — do NOT infer Z.ai from the glm-5.2 model value.
    assert "OpenAI" in out


# =========================================================================== #
# SC-1 (PROV-05, D-50) — config paths section
# =========================================================================== #


@pytest.mark.integration
def test_status_prints_every_resolved_path_with_markers_sc1(tmp_path, capsys):
    """SC-1 / D-50: every Paths.default() path appears, each marked exists/missing."""
    # Seed config.toml (exists) and a moonbridge_yml (exists) so both markers
    # are exercised; the other three paths remain missing.
    paths = Paths.default()
    _write(paths.config_toml, ZAI_ACTIVE_CONFIG)
    _write(paths.moonbridge_yml, "api_key: test\n")

    rc = main(["status"])

    assert rc == 0
    out = capsys.readouterr().out
    # Every D-50 path field's resolved string appears in output (compare against
    # Paths.default() so the test is robust to HOME changes).
    for field in ("config_toml", "moonbridge_yml", "models_cache", "zshrc", "launchagents_dir"):
        assert str(getattr(paths, field)) in out, f"missing path for {field}"
    # config.toml + moonbridge_yml are present -> marked exists.
    assert "[exists]" in out
    # models_cache / zshrc / launchagents_dir are absent -> at least one missing.
    assert "[missing]" in out


# =========================================================================== #
# SC-1 (PROV-05, D-50, D-16) — version section
# =========================================================================== #


@pytest.mark.integration
def test_status_prints_package_name_and_version_sc1(tmp_path, capsys):
    """SC-1 / D-50 / D-16: stdout includes `zai-codex-helper` + __version__."""
    _write(_config_toml(tmp_path), OPENAI_DEFAULT_CONFIG)

    rc = main(["status"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "zai-codex-helper" in out
    # Read __version__ from the module (do NOT hard-code "0.1.0").
    assert __version__ in out


# =========================================================================== #
# SC-2 (D-52) — missing config is NOT broken (exit 0)
# =========================================================================== #


@pytest.mark.integration
def test_status_missing_config_is_openai_default_exit_0_sc2(tmp_path, capsys):
    """SC-2 / D-52: no config.toml -> OpenAI builtin default, exit 0 (missing != broken)."""
    cfg = _config_toml(tmp_path)
    assert not cfg.exists()  # fresh install

    rc = main(["status"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "OpenAI" in out
    # The output notes config.toml is not yet created.
    assert "not yet created" in out.lower() or "config.toml" in out


# =========================================================================== #
# SC-2 (D-52, T-08-02) — broken config -> D-11 one-line error + exit 1
# =========================================================================== #


@pytest.mark.integration
def test_status_broken_config_is_one_line_error_exit_1_sc2(tmp_path, capsys):
    """SC-2 / D-52: malformed TOML -> `error:` on stderr, exit 1, no traceback."""
    _write(_config_toml(tmp_path), BROKEN_CONFIG)

    rc = main(["status"])

    assert rc == 1
    out, err = capsys.readouterr()
    # stdout has no provider summary on the error path.
    assert out == ""
    # Exactly one non-empty stderr line starting with `error:`.
    non_empty = [line for line in err.splitlines() if line.strip()]
    assert len(non_empty) == 1
    assert non_empty[0].startswith("error:")
    # No traceback / no exception class name leaks without --debug.
    assert "Traceback" not in err
    assert "ZaiCodexHelperError" not in err


@pytest.mark.integration
def test_status_broken_config_debug_reraises_sc2(tmp_path):
    """SC-2 / D-52: --debug re-raises the (translated) ZaiCodexHelperError."""
    _write(_config_toml(tmp_path), BROKEN_CONFIG)

    with pytest.raises(ZaiCodexHelperError):
        main(["--debug", "status"])


# =========================================================================== #
# SC-2 (D-51) — read-only byte-identical proof (the highest-signal test)
# =========================================================================== #


@pytest.mark.integration
def test_status_readonly_zai_active_byte_identical_sc2(tmp_path):
    """SC-2 / D-51: Z.ai-active config -> tmp HOME byte-identical before/after."""
    _write(_config_toml(tmp_path), ZAI_ACTIVE_CONFIG)

    before_paths, before_hashes = _snapshot(tmp_path)
    rc = main(["status"])
    after_paths, after_hashes = _snapshot(tmp_path)

    assert rc == 0
    assert before_paths == after_paths  # no creates/deletes
    assert before_hashes == after_hashes  # no in-place mutations


@pytest.mark.integration
def test_status_readonly_openai_default_byte_identical_sc2(tmp_path):
    """SC-2 / D-51: OpenAI-default config -> tmp HOME byte-identical before/after."""
    _write(_config_toml(tmp_path), OPENAI_DEFAULT_CONFIG)

    before_paths, before_hashes = _snapshot(tmp_path)
    rc = main(["status"])
    after_paths, after_hashes = _snapshot(tmp_path)

    assert rc == 0
    assert before_paths == after_paths
    assert before_hashes == after_hashes


@pytest.mark.integration
def test_status_readonly_missing_config_byte_identical_sc2(tmp_path):
    """SC-2 / D-51: missing config -> tmp HOME byte-identical before/after."""
    assert not _config_toml(tmp_path).exists()

    before_paths, before_hashes = _snapshot(tmp_path)
    rc = main(["status"])
    after_paths, after_hashes = _snapshot(tmp_path)

    assert rc == 0
    assert before_paths == after_paths
    assert before_hashes == after_hashes


# =========================================================================== #
# Static read-only guard (D-51, T-08-01) — no mutator names in the status path
# =========================================================================== #


def _status_module_paths() -> list[Path]:
    """The source files that make up the ``status`` code path.

    ``_handle_status`` lives in ``cli/parser.py``; the pure detection helper +
    read-boundary translator live in ``services/status.py`` (created in Task 2).
    If ``services/status.py`` does not yet exist (RED state), it is skipped —
    the ``cli/parser.py`` scan still runs.
    """
    root = Path(__file__).resolve().parent.parent / "src" / "zai_codex_helper"
    files = [root / "cli" / "parser.py"]
    status_service = root / "services" / "status.py"
    if status_service.exists():
        files.append(status_service)
    return files


@pytest.mark.unit
class TestStatusReadOnlyGuard:
    """D-51 / T-08-01: the status code path references NO mutator names.

    Static AST scan (mirrors ``tests/test_providers.py::TestPurityGuard``).
    The status path must never CALL or reference: ``write_canonical``,
    ``backup_once``, ``atomic_write``, ``os.replace``, ``os.chmod``,
    ``unlink``, ``mkdir``, ``rename``. A future edit that accidentally pulls a
    mutator into the read-only status path fails this test.

    NOTE: this guards the WHOLE module (``cli/parser.py`` contains the mutating
    ``_apply_provider_pipeline`` for ``use zai``/``use openai``). To keep the
    guard meaningful for ``status`` specifically, we scope it to the body of
    ``_handle_status`` — see ``test_handle_status_body_has_no_mutator_calls``.
    The module-level scan below is a secondary belt-and-braces check against
    mutator names appearing in ``services/status.py`` (which MUST be pure).
    """

    @pytest.fixture(autouse=True)
    def _load_status_sources(self):
        self.sources: dict[str, str] = {}
        self.trees: dict[str, ast.AST] = {}
        for f in _status_module_paths():
            text = f.read_text(encoding="utf-8")
            self.sources[str(f)] = text
            self.trees[str(f)] = ast.parse(text)

    def test_services_status_has_no_mutator_references(self):
        """``services/status.py`` (pure helper) references no mutator names."""
        forbidden_attrs = {
            "replace",
            "chmod",
            "unlink",
            "mkdir",
            "rename",
        }
        forbidden_names = {
            "write_canonical",
            "backup_once",
            "atomic_write",
        }
        status_key = next(
            (k for k in self.trees if k.endswith("services/status.py")), None
        )
        if status_key is None:
            pytest.skip("services/status.py not yet created (RED state)")
        tree = self.trees[status_key]
        for node in ast.walk(tree):
            # No `os.replace` / `os.chmod` / `.unlink()` / `.mkdir()` / `.rename()`.
            if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
                pytest.fail(
                    f"forbidden mutating attribute {node.attr!r} in services/status.py"
                )
            # No bare-name call/reference to write_canonical/backup_once/atomic_write.
            if isinstance(node, ast.Name) and node.id in forbidden_names:
                pytest.fail(
                    f"forbidden mutator name {node.id!r} in services/status.py"
                )

    def test_handle_status_body_has_no_mutator_calls(self):
        """The body of ``_handle_status`` calls/refs no mutator (D-51, load-bearing).

        Scans ONLY the ``_handle_status`` function body in ``cli/parser.py`` —
        not the whole module (which legitimately contains the mutating
        ``_apply_provider_pipeline`` for ``use zai``/``use openai``). If
        ``_handle_status`` is not yet defined (RED), the test fails — that is
        the intended TDD starting state.
        """
        forbidden_attrs = {
            "replace",
            "chmod",
            "unlink",
            "mkdir",
            "rename",
        }
        forbidden_names = {
            "write_canonical",
            "backup_once",
            "atomic_write",
        }
        parser_key = next(
            k for k in self.trees if k.endswith("cli/parser.py")
        )
        tree = self.trees[parser_key]
        # Find the _handle_status function definition.
        handler = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_handle_status"
            ):
                handler = node
                break
        assert handler is not None, (
            "_handle_status not yet defined in cli/parser.py (RED state)"
        )
        for node in ast.walk(handler):
            if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
                pytest.fail(
                    f"forbidden mutating attribute {node.attr!r} "
                    f"in _handle_status body"
                )
            if isinstance(node, ast.Name) and node.id in forbidden_names:
                pytest.fail(
                    f"forbidden mutator name {node.id!r} "
                    f"in _handle_status body"
                )


# =========================================================================== #
# Handler dispatch (unit — no disk IO beyond parse)
# =========================================================================== #


@pytest.mark.unit
def test_status_is_real_handler_not_stub():
    """`status` dispatches to the real _handle_status (not a stub closure).

    A stub closure is named ``handler``; the real handler is a named module
    function. This is the D-02 swap (Phase 1 stub -> Phase 8 real).
    """
    args = build_parser().parse_args(["status"])
    assert args.cmd == "status"
    assert args.func.__name__ == "_handle_status"


@pytest.mark.unit
def test_status_help_exits_zero(capsys):
    """`status --help` exits 0 and top-level `--help` lists `status`."""
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["status", "--help"])
    assert exc.value.code == 0

    with pytest.raises(SystemExit) as exc2:
        build_parser().parse_args(["--help"])
    assert exc2.value.code == 0
    out, _ = capsys.readouterr()
    assert "status" in out
