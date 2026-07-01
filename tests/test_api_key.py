"""Tests for ``zai-codex-helper set-key`` (``services/api_key.py: set_key``).

set_key replaces ONLY ``ZAI_API_KEY`` in ``moonbridge-zai.yml`` via a
read-modify-write (YamlBackend writes the whole file atomically — no in-place
field update). Pins: the new key is written; ``model``/``server`` survive; a
missing yml raises "run setup first"; ``--dry-run`` redacts the key and writes
nothing.
"""

from __future__ import annotations

import os

import pytest
import yaml

from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services import api_key
from zai_codex_helper.services.paths import Paths

_OLD = "11111111111111111111111111111111.aaaaaaaaaaaaaaaa"
_NEW = "22222222222222222222222222222222.bbbbbbbbbbbbbbbb"


def _seed_yml(paths: Paths, key: str = _OLD) -> None:
    """Write a canonical moonbridge-zai.yml via the real backend (mode 0600).

    Uses the helper's canonical Moon Bridge schema (providers.zai.api_key) so
    the seed is a valid config Moon Bridge would accept.
    """
    from zai_codex_helper.backends.yaml import YamlBackend
    from zai_codex_helper.services.setup import canonical_moonbridge_yml

    YamlBackend(paths).write_canonical(canonical_moonbridge_yml(key))


@pytest.mark.unit
def test_set_key_replaces_only_key_env(tmp_path, monkeypatch):
    """ZAI_API_KEY env → only the key changes; model/server untouched."""
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)
    monkeypatch.setenv("ZAI_API_KEY", _NEW)

    rc = api_key.set_key(paths, environ=dict(os.environ))

    assert rc == 0
    data = yaml.safe_load(paths.moonbridge_yml.read_text())
    # set-key updated providers.zai.api_key; rest of the canonical body preserved.
    assert data["providers"]["zai"]["api_key"] == _NEW
    assert data["mode"] == "Transform"
    assert "ZAI_API_KEY" not in data  # no legacy top-level key


@pytest.mark.unit
def test_set_key_missing_yml_raises(tmp_path, monkeypatch):
    """No moonbridge-zai.yml → actionable "run setup first", never writes."""
    paths = Paths.from_home(tmp_path)
    monkeypatch.setenv("ZAI_API_KEY", _NEW)
    assert not paths.moonbridge_yml.exists()

    with pytest.raises(ZaiCodexHelperError, match="setup"):
        api_key.set_key(paths, environ=dict(os.environ))

    assert not paths.moonbridge_yml.exists()


@pytest.mark.unit
def test_set_key_rejects_malformed_env_key(tmp_path, monkeypatch):
    """A malformed ZAI_API_KEY env value fails fast — yml is NOT modified."""
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)
    monkeypatch.setenv("ZAI_API_KEY", "garbage")

    with pytest.raises(ZaiCodexHelperError, match="malformed"):
        api_key.set_key(paths, environ=dict(os.environ))

    data = yaml.safe_load(paths.moonbridge_yml.read_text())
    assert data["providers"]["zai"]["api_key"] == _OLD  # unchanged


@pytest.mark.unit
def test_set_key_interactive_input(tmp_path, monkeypatch):
    """Without env, the key is read via the echoed prompt (valid value)."""
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)

    rc = api_key.set_key(paths, environ=dict(os.environ), input_fn=lambda _p: _NEW)

    assert rc == 0
    data = yaml.safe_load(paths.moonbridge_yml.read_text())
    assert data["providers"]["zai"]["api_key"] == _NEW


@pytest.mark.unit
def test_set_key_dry_run_redacts_and_writes_nothing(tmp_path, monkeypatch, capsys):
    """--dry-run prints a redacted diff and leaves the file unchanged."""
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)
    monkeypatch.setenv("ZAI_API_KEY", _NEW)

    rc = api_key.set_key(paths, dry_run=True, environ=dict(os.environ))

    assert rc == 0
    out = capsys.readouterr().out
    assert _NEW not in out  # new key never reaches stdout
    assert _OLD not in out  # existing key never leaks via the removed diff line
    assert "redacted" in out.lower()
    data = yaml.safe_load(paths.moonbridge_yml.read_text())
    assert data["providers"]["zai"]["api_key"] == _OLD  # file unchanged
    # --dry-run = ZERO writes: no .bak, no backup sentinel (regression — the
    # old backup_once() ran before the dry_run guard and poisoned the gate).
    files = {p.name for p in paths.codex_dir.iterdir()}
    assert not any(name.endswith("backed-up") for name in files), files
    assert not any(name.endswith(".bak") for name in files), files


@pytest.mark.unit
def test_set_key_preserves_file_mode(tmp_path, monkeypatch):
    """The rewritten yml stays at 0600 (it still holds the key)."""
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)
    monkeypatch.setenv("ZAI_API_KEY", _NEW)

    api_key.set_key(paths, environ=dict(os.environ))

    mode = paths.moonbridge_yml.stat().st_mode & 0o777
    assert mode == 0o600


@pytest.mark.unit
def test_parser_routes_set_key_to_handler():
    """``set-key`` subcommand resolves to ``_handle_set_key``."""
    from zai_codex_helper.cli.parser import build_parser

    args = build_parser().parse_args(["set-key"])
    assert args.func.__name__ == "_handle_set_key"


# ---------------------------------------------------------------------------
# yml_has_auth_token + auth_token removal (Yes/No)
# ---------------------------------------------------------------------------

_TOKEN = "sk-moonbridge-zai-local"


def _seed_foreign_yml(paths: Paths, key: str = _OLD) -> None:
    """Seed a FOREIGN Moon Bridge yml (hand-rolled, with server.auth_token)."""
    paths.moonbridge_yml.parent.mkdir(parents=True, exist_ok=True)
    paths.moonbridge_yml.write_text(
        f"ZAI_API_KEY: {key}\n"
        "mode: Transform\n"
        "server:\n"
        "  addr: 127.0.0.1:38440\n"
        f"  auth_token: {_TOKEN}\n"
        "providers:\n"
        "  zai:\n"
        f"    api_key: {key}\n"
        "    base_url: https://api.z.ai/api/coding/paas/v4/chat/completions\n"
    )
    os.chmod(paths.moonbridge_yml, 0o600)


@pytest.mark.unit
def test_yml_has_auth_token_detects_token():
    """server.auth_token present → True."""
    assert api_key.yml_has_auth_token({"server": {"auth_token": "x"}}) is True


@pytest.mark.unit
def test_yml_has_auth_token_absent():
    """Canonical yml (no auth_token) → False; non-dict → False."""
    assert api_key.yml_has_auth_token({"server": {"host": "127.0.0.1"}}) is False
    assert api_key.yml_has_auth_token({"ZAI_API_KEY": "k"}) is False
    assert api_key.yml_has_auth_token(None) is False
    assert api_key.yml_has_auth_token("not a dict") is False


@pytest.mark.unit
def test_set_key_removes_auth_token_on_yes(tmp_path, monkeypatch):
    """Yes → token dropped, key updated, rest of the structure preserved, .bak created."""
    paths = Paths.from_home(tmp_path)
    _seed_foreign_yml(paths)
    monkeypatch.setenv("ZAI_API_KEY", _NEW)

    rc = api_key.set_key(
        paths, environ=dict(os.environ), confirm_fn=lambda *_a, **_k: True
    )

    assert rc == 0
    data = yaml.safe_load(paths.moonbridge_yml.read_text())
    assert data["providers"]["zai"]["api_key"] == _NEW
    assert "auth_token" not in data["server"]  # token removed
    assert "ZAI_API_KEY" not in data  # legacy top-level key removed
    # Structure preserved (not canonicalized to helper shape).
    assert data["mode"] == "Transform"
    assert "providers" in data
    # One-shot backup of the original foreign yml exists.
    bak = paths.moonbridge_yml.with_name(
        paths.moonbridge_yml.name + ".zai-codex-helper.bak"
    )
    assert bak.exists()


@pytest.mark.unit
def test_set_key_skips_on_no_with_warning(tmp_path, monkeypatch, capsys):
    """No → yml untouched, warning printed (auth_token left → Codex 401)."""
    paths = Paths.from_home(tmp_path)
    _seed_foreign_yml(paths)
    monkeypatch.setenv("ZAI_API_KEY", _NEW)

    rc = api_key.set_key(
        paths, environ=dict(os.environ), confirm_fn=lambda *_a, **_k: False
    )

    assert rc == 0
    data = yaml.safe_load(paths.moonbridge_yml.read_text())
    assert data["providers"]["zai"]["api_key"] == _OLD  # untouched
    assert data["server"]["auth_token"] == _TOKEN  # token left
    assert "401" in capsys.readouterr().out


@pytest.mark.unit
def test_set_key_no_auth_token_does_not_ask(tmp_path, monkeypatch):
    """Canonical yml (no auth_token) → confirm is never called, key updated."""
    paths = Paths.from_home(tmp_path)
    _seed_yml(paths)  # canonical, no auth_token
    monkeypatch.setenv("ZAI_API_KEY", _NEW)

    def fail_confirm(*_a, **_k):
        raise AssertionError("confirm must not be called when there is no auth_token")

    rc = api_key.set_key(paths, environ=dict(os.environ), confirm_fn=fail_confirm)
    assert rc == 0
    data = yaml.safe_load(paths.moonbridge_yml.read_text())
    assert data["providers"]["zai"]["api_key"] == _NEW
