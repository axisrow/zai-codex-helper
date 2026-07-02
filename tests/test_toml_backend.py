"""Pin ROADMAP Phase 5 SC-1 (lossless round-trip) and SC-2 (upsert replace-not-append).

``TomlBackend`` is the first concrete :class:`ConfigBackend` (Phase 4 ABC) and
THE load-bearing piece of the project: if ``tomlkit`` ever drops a comment or a
``[project_*]`` trust block on a ``read → dumps`` cycle, every later ``use zai``
(Phase 7) silently corrupts the user's Codex ``config.toml``. Hence SC-1 is the
single highest-signal test in the project.

Style mirrors ``tests/test_config_backend_abc.py`` and ``tests/test_paths.py``:
``from __future__ import annotations``, ``@pytest.mark.unit`` (flat ``tests/``
layout, CONTEXT D-14 HOME isolation via the autouse ``_isolate_home`` fixture).
All backends are built from ``Paths.from_home(tmp_path)`` — never the real
``$HOME``.

What this file pins:

- **SC-1 (lossless round-trip):** a realistic Codex fixture seeded with EVERY
  comment style + a ``[project_*]`` trust block + nested provider tables
  round-trips byte-identical through ``read → dumps``.
- **SC-2 (upsert replace-not-append, D-36):** ``upsert_block`` re-assigns the
  leaf sub-table, yielding EXACTLY ONE block (never an appended duplicate);
  idempotent on repeat; creates when absent.
- **Backend contract (D-33 / D-34 / D-29):** ``read`` returns a live
  ``tomlkit.TOMLDocument``; ``write_canonical`` routes through
  ``_write_via_atomic`` (crash-safe, mode preserved); ``exists`` reflects disk;
  ``backup_once`` is inherited as-is (identity with the ABC).
- **Library discipline (D-37):** no ``tomllib`` / ``toml`` (uiri) imports in
  ``backends/toml.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import tomlkit
from tomlkit import TOMLDocument

from zai_codex_helper.backends.base import ConfigBackend
from zai_codex_helper.backends.toml import TomlBackend, upsert_block
from zai_codex_helper.services.paths import Paths

# --------------------------------------------------------------------------- #
# Fixture — a realistic Codex config.toml exercising every comment style.
# This is the SC-1 seed (D-35): top comment, blank line, inline comment,
# [project_*] trust block, nested [model_providers.zai], sibling
# [model_providers.openai]. Verified to round-trip BYTE-IDENTICAL through
# tomlkit 0.14+ (probe prior to writing the assertion).
# --------------------------------------------------------------------------- #
REALISTIC_FIXTURE = """\
# top comment
model = "gpt-5.1"
model_provider = "openai" # default provider

[model_providers.openai]
name = "OpenAI"

[model_providers.zai]
name = "Old"
base_url = "http://127.0.0.1:38440/v1"

[project_2fa0]
trust_level = "trusted"
"""


def _seed_config(paths: Paths, content: str = REALISTIC_FIXTURE) -> Path:
    """Write ``content`` to ``paths.config_toml`` and return the path.

    Uses a plain ``write_text`` — the SC-1 seed is a fixed string; the point is
    to read it back via ``TomlBackend.read`` and assert the round-trip, not to
    exercise ``write_canonical`` here (that has its own tests below).
    """
    paths.config_toml.parent.mkdir(parents=True, exist_ok=True)
    paths.config_toml.write_text(content, encoding="utf-8")
    return paths.config_toml


# --------------------------------------------------------------------------- #
# SC-1 — lossless round-trip (highest-signal test in the project)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_read_returns_tomlkit_document(tmp_path):
    """``read`` returns a live ``tomlkit.TOMLDocument`` (D-34).

    Phase 6/7 transforms mutate this document style-preservingly before
    ``write_canonical`` dumps it back; the type must be ``TOMLDocument``.
    """
    paths = Paths.from_home(tmp_path)
    _seed_config(paths)
    backend = TomlBackend(paths)
    doc = backend.read()
    assert isinstance(doc, TOMLDocument)


@pytest.mark.unit
def test_round_trip_preserves_comments_blank_lines_key_order_and_trust_block(tmp_path):
    """SC-1 (load-bearing): a no-op ``read → dumps`` cycle reproduces the
    fixture byte-for-byte.

    The fixture carries ALL of:

    - a top-level ``# top comment`` before any key;
    - a blank line between top-level keys;
    - an inline trailing comment (``model_provider = "openai" # default provider``);
    - a Codex ``[project_2fa0]`` trust block (D-35 calls this out explicitly);
    - a nested ``[model_providers.zai]`` block;
    - a sibling ``[model_providers.openai]`` so key order across siblings is
      observable.

    If this ever regresses, every ``use zai`` corrupts the user's Codex config.
    """
    paths = Paths.from_home(tmp_path)
    _seed_config(paths)
    backend = TomlBackend(paths)

    doc = backend.read()
    dumped = tomlkit.dumps(doc)
    assert dumped == REALISTIC_FIXTURE  # byte-identical (D-35)


# --------------------------------------------------------------------------- #
# SC-2 — upsert replace-not-append (D-36)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_upsert_replaces_existing_block_not_appends(tmp_path):
    """SC-2 (load-bearing): upsert over an existing ``[model_providers.zai]``
    yields EXACTLY ONE block in the dumped output — never an appended duplicate.

    A duplicate block would silently break Codex's provider resolution (it
    would pick the first or last occurrence, not the "replaced" one). The
    ``count == 1`` assertion is the load-bearing guard.
    """
    paths = Paths.from_home(tmp_path)
    _seed_config(paths)
    backend = TomlBackend(paths)
    doc = backend.read()

    upsert_block(
        doc,
        "model_providers.zai",
        {
            "name": "New",
            "base_url": "http://127.0.0.1:38440/v1",
            "wire_api": "responses",
        },
    )

    dumped = tomlkit.dumps(doc)
    assert dumped.count("[model_providers.zai]") == 1
    assert 'name = "New"' in dumped
    assert 'name = "Old"' not in dumped
    assert 'wire_api = "responses"' in dumped
    # Sibling block + trust block survive untouched (D-36 — no collateral).
    assert "[model_providers.openai]" in dumped
    assert "[project_2fa0]" in dumped


@pytest.mark.unit
def test_upsert_creates_when_absent(tmp_path):
    """SC-2: upserting into a document with NO ``model_providers`` table
    creates the parent + leaf, yielding exactly one block."""
    paths = Paths.from_home(tmp_path)
    _seed_config(paths, content='model = "gpt-5.1"\n')
    backend = TomlBackend(paths)
    doc = backend.read()

    assert "model_providers" not in doc
    upsert_block(
        doc,
        "model_providers.zai",
        {"name": "Created", "base_url": "http://127.0.0.1:38440/v1"},
    )

    dumped = tomlkit.dumps(doc)
    assert dumped.count("[model_providers.zai]") == 1
    assert 'name = "Created"' in dumped


@pytest.mark.unit
def test_upsert_idempotent_on_repeat(tmp_path):
    """SC-2 / CONF-06 primitive: calling ``upsert_block`` twice with the same
    args yields identical output — exactly one block, same values both times.

    Phase 7's ``use zai`` runs twice (the user toggles away and back) must not
    accumulate duplicate blocks.
    """
    paths = Paths.from_home(tmp_path)
    _seed_config(paths)
    backend = TomlBackend(paths)
    doc = backend.read()

    block = {"name": "New", "base_url": "http://127.0.0.1:38440/v1"}
    upsert_block(doc, "model_providers.zai", block)
    dumped_once = tomlkit.dumps(doc)

    upsert_block(doc, "model_providers.zai", block)
    dumped_twice = tomlkit.dumps(doc)

    assert dumped_once == dumped_twice
    assert dumped_twice.count("[model_providers.zai]") == 1


# --------------------------------------------------------------------------- #
# Backend contract (D-33 / D-34 / D-29 carry-forward)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_path_resolved_via_injected_paths(tmp_path):
    """D-33: TomlBackend resolves its target through the injected ``Paths`` —
    no hard-coded ``~/.codex/config.toml`` literal."""
    paths = Paths.from_home(tmp_path)
    backend = TomlBackend(paths)
    assert backend.path == paths.config_toml
    assert backend.path == tmp_path / ".codex" / "config.toml"


@pytest.mark.unit
def test_write_canonical_round_trips_through_atomic_write(tmp_path):
    """D-29 / D-34: ``write_canonical`` lands the file at ``paths.config_toml``
    via ``_write_via_atomic`` (crash-safe). Re-reading the dumped document
    yields equivalent content."""
    paths = Paths.from_home(tmp_path)
    _seed_config(paths)
    backend = TomlBackend(paths)
    doc = backend.read()

    # Mutate and write back through the canonical surface.
    doc["model"] = "glm-5.2"
    backend.write_canonical(tomlkit.dumps(doc))

    # Re-read and confirm the mutation landed + round-trips.
    reread = backend.read()
    assert reread["model"] == "glm-5.2"
    # The surviving structure is still lossless (SC-1 invariant holds post-write).
    assert tomlkit.dumps(reread).count("[model_providers.zai]") == 1
    assert "[project_2fa0]" in tomlkit.dumps(reread)


@pytest.mark.unit
def test_write_canonical_accepts_tomlkit_document(tmp_path):
    """D-34: ``write_canonical`` accepts either a ``TOMLDocument`` or a ``str``.
    Passing a document directly must serialize it via ``tomlkit.dumps``."""
    paths = Paths.from_home(tmp_path)
    _seed_config(paths)
    backend = TomlBackend(paths)
    doc = backend.read()
    doc["model"] = "claude"
    # Pass the live TOMLDocument, not a pre-dumped string.
    backend.write_canonical(doc)
    assert backend.read()["model"] == "claude"


@pytest.mark.unit
def test_write_canonical_preserves_existing_mode(tmp_path):
    """T-05-04 / D-34 (#27): ``write_canonical(mode=None)`` PRESERVES config.toml's mode.

    CLAUDE.md: config.toml → "preserve existing mode; respect the user's existing
    mode". A user's typical ``0644`` config must survive a patch as ``0644`` — NOT
    be narrowed to the atomic-write temp default. (This previously asserted the
    buggy "always 0o600" behavior; #27 fixed atomic_write to restore the prior
    mode on overwrite, so the contract is now "mode unchanged".)
    """
    paths = Paths.from_home(tmp_path)
    _seed_config(paths)
    os.chmod(paths.config_toml, 0o644)  # typical umask-produced config.toml mode
    assert (os.stat(paths.config_toml).st_mode & 0o777) == 0o644

    backend = TomlBackend(paths)
    doc = backend.read()
    backend.write_canonical(tomlkit.dumps(doc), mode=None)

    final_mode = os.stat(paths.config_toml).st_mode & 0o777
    assert final_mode == 0o644, (
        f"mode=None must preserve the user's 0644, got {oct(final_mode)}"
    )


@pytest.mark.unit
def test_exists_true_and_false(tmp_path):
    """D-34: ``exists()`` reflects whether ``paths.config_toml`` is on disk."""
    paths = Paths.from_home(tmp_path)
    backend = TomlBackend(paths)
    assert backend.exists() is False  # nothing seeded

    _seed_config(paths)
    assert backend.exists() is True


@pytest.mark.unit
def test_read_propagates_filenotfound_when_absent(tmp_path):
    """D-38: TomlBackend is generic — it does NOT invent a default document
    when the file is missing; ``FileNotFoundError`` propagates so Phase 6/7
    callers own the "no config yet" branch."""
    paths = Paths.from_home(tmp_path)
    backend = TomlBackend(paths)
    assert not paths.config_toml.exists()
    with pytest.raises(FileNotFoundError):
        backend.read()


@pytest.mark.unit
def test_backup_once_inherited_not_overridden():
    """D-30 carry-forward: ``TomlBackend`` has NO ``backup_once`` of its own —
    the inherited concrete-on-ABC method is what runs (identity check).
    The coordinator's behavior is already covered in Phase 4; this test only
    pins inheritance."""
    assert TomlBackend.backup_once is ConfigBackend.backup_once
    assert "backup_once" not in TomlBackend.__dict__  # no override in the subclass


# --------------------------------------------------------------------------- #
# Library discipline (D-37) — static source guard
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_no_tomllib_or_toml_import_for_mutation():
    """D-37 / CLAUDE.md "What NOT to Use": ``backends/toml.py`` MUST NOT import
    ``tomllib`` (read-only, destroys formatting) or ``toml`` (uiri/toml —
    abandoned, pre-1.0, destroys comments). ``tomlkit`` is the ONLY mutation
    library. Comment-filtered (a commented-out reference in a docstring is
    not an import).
    """
    import zai_codex_helper.backends.toml as toml_mod

    source = Path(toml_mod.__file__).read_text(encoding="utf-8")
    import_lines = [
        line
        for line in source.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    forbidden = []
    for line in import_lines:
        stripped = line.strip()
        if (stripped.startswith("import ") or stripped.startswith("from ")) and (
            "tomllib" in stripped or " toml " in f" {stripped} "
        ):
            forbidden.append(line)
    assert not forbidden, f"D-37 violation: forbidden TOML imports: {forbidden}"
