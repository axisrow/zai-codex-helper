"""``TomlBackend`` — the first concrete :class:`ConfigBackend` and the
load-bearing piece of the entire project (Phase 5; decisions D-33..D-38).

``~/.codex/config.toml`` can be parsed with ``tomlkit``, mutated through a
replace-not-append upsert (:func:`upsert_block`), and written back
losslessly: comments, blank lines, key order, and Codex ``[project_*]`` trust
blocks survive a no-op ``read → dumps`` round-trip (ROADMAP SC-1). This is
where ``Paths`` (Phase 2) + ``atomic_write`` (Phase 3) + ``ConfigBackend``
(Phase 4) + ``tomlkit`` (Phase 1 dep, first runtime import) all meet for the
``.toml`` file type.

Library discipline (CLAUDE.md "What NOT to Use"; D-37): ``tomlkit`` is the
ONLY TOML library this module imports for mutation. NEVER ``tomllib`` (stdlib,
read-only — round-trip destroys comments and project trust blocks) and NEVER
``toml`` (uiri/toml — abandoned, pre-1.0, destroys comments). Read-only
``tomllib`` MAY be used in ``doctor`` (Phase 14) for parse-validation, but
this is a mutation path — ``tomlkit`` only.

Scope discipline (D-38): this module delivers read/write/upsert PRIMITIVES
only. It does NOT know what "zai" means — no ``apply_zai`` / ``apply_openai``
/ ``use`` / ``status`` logic. Phase 6/7 transforms call these primitives to
build the desired state.
"""

from __future__ import annotations

from collections.abc import Mapping

import tomlkit
from tomlkit import TOMLDocument

from zai_codex_helper.backends.base import ConfigBackend
from zai_codex_helper.services.paths import Paths

__all__ = ["TomlBackend", "upsert_block"]


class TomlBackend(ConfigBackend):
    """Concrete :class:`ConfigBackend` for ``~/.codex/config.toml`` (D-33, D-34).

    A purpose-built TOML backend: the subclass hard-codes the ``Paths`` field
    name (``"config_toml"``) so callers only pass the :class:`Paths` instance.
    The path is resolved by the ABC constructor — this class NEVER hard-codes
    a ``~/.codex/config.toml`` literal (D-33 / T-05-05). ``read`` returns a
    live, mutable, style-preserving ``tomlkit.TOMLDocument`` (D-34); ``write``
    goes through ``_write_via_atomic`` (D-29 structural — no backend bypasses
    ``atomic_write``); ``backup_once`` is inherited as-is (D-30 — no override).

    The backend is GENERIC (D-38): it parses, mutates through
    :func:`upsert_block`, and writes back whatever TOML is there. Semantic
    correctness ("is this a valid Codex config?", "what keys make Z.ai the
    default?") is Phase 6/7's job, not the backend's.
    """

    def __init__(self, paths: Paths) -> None:
        """Bind to ``paths.config_toml`` via the ABC constructor (D-33).

        Args:
            paths: The injected :class:`Paths` bundle (frozen, D-22). Resolved
                to ``paths.config_toml`` by the inherited constructor; a
                misnamed field would fail fast there, not deep in a later
                write.
        """
        super().__init__(paths, "config_toml")

    def read(self) -> TOMLDocument:
        """Parse ``config.toml`` into a live ``tomlkit.TOMLDocument`` (D-34).

        ``tomlkit.parse`` returns a style-preserving container — comments,
        whitespace, key order, and ``[project_*]`` trust blocks are retained
        on a subsequent ``tomlkit.dumps`` (SC-1). Phase 6/7 transforms mutate
        this document in place before writing it back.

        If the file does not exist, ``FileNotFoundError`` propagates (D-38 —
        generic backend; the "no config yet" branch is the caller's job).
        """
        return tomlkit.parse(self._path.read_text(encoding="utf-8"))

    def exists(self) -> bool:
        """Return ``True`` iff ``config.toml`` exists on disk (D-34)."""
        return self._path.exists()

    def write_canonical(
        self,
        content: TOMLDocument | str,
        mode: int | None = None,
    ) -> None:
        """Write ``content`` back to ``config.toml`` crash-safely (D-29, D-34).

        Accepts either a live ``TOMLDocument`` (serialized via
        ``tomlkit.dumps``) or a pre-dumped ``str``. Either way the payload is
        routed through ``self._write_via_atomic`` — the ABC's private helper
        that calls ``atomic_write(self._path, ..., mode)`` (D-29 structural
        delegation; never call ``atomic_write`` directly here).

        ``mode`` defaults to ``None``, passed verbatim to ``atomic_write``,
        which PRESERVES an existing ``config.toml``'s mode on overwrite (e.g.
        keeps the user's 0644) and uses the temp default (``0o600``) only on a
        first write — matching the CLAUDE.md "preserve existing mode; respect
        the user's existing mode" contract (T-05-04, disposition ``accept``).
        A caller MAY pass an explicit ``mode`` to force a specific permission.

        This method does NOT call ``backup_once``: the ABC surface gates
        backup at a higher layer (D-38 — primitives only).
        """
        if isinstance(content, TOMLDocument):
            serialized: str = tomlkit.dumps(content)
        else:
            serialized = content
        self._write_via_atomic(serialized, mode)


def upsert_block(
    doc: TOMLDocument,
    dotted_path: str,
    block: Mapping[str, object],
) -> None:
    """Replace-or-create a nested ``[parent.leaf]`` sub-table in ``doc`` (D-36).

    Given a dotted table path (e.g. ``"model_providers.zai"``) and a ``block``
    mapping, this helper REPLACES the existing sub-table's contents if present
    (no duplicate ``[model_providers.zai]`` blocks) or CREATES it if absent.
    The single leaf assignment is the replace-not-append chokepoint — a
    duplicate block would silently break Codex's provider resolution (it
    would pick the first or last occurrence, not the "replaced" one).

    Load-bearing invariant: ONE block per path, not appended duplicates. This
    is the CONF-06 idempotency primitive Phase 7's ``use zai`` calls (twice
    running it yields identical output).

    Args:
        doc: The live :class:`tomlkit.TOMLDocument` to mutate in place.
        dotted_path: Dotted table path (``"parent.sub.leaf"``). The parent
            containers are created (as empty tomlkit tables) if absent.
        block: Mapping of key → value for the leaf sub-table. A FRESH
            ``tomlkit.table()`` is built from this mapping; the input is not
            mutated, and any prior contents of the leaf sub-table are
            discarded (replace semantics).

    Known tomlkit normalization (D-35): ``tomlkit`` drops comments that were
    attached to a *replaced* sub-table — the old table object is discarded
    wholesale. Comments on surviving keys, top-level comments, blank lines,
    sibling tables, and ``[project_*]`` trust blocks ARE preserved (proven by
    the SC-1 round-trip test). The replace is necessary for the
    replace-not-append invariant; per-block comment preservation on a
    replaced block is out of scope (the caller-owned block carries its own
    canonical shape).
    """
    segments = dotted_path.split(".")
    if not segments or any(not seg for seg in segments):
        raise ValueError(
            f"dotted_path must be a non-empty dotted path: {dotted_path!r}"
        )

    # Walk/create the parent container down to (but not including) the leaf.
    container: object = doc
    for seg in segments[:-1]:
        assert isinstance(container, TOMLDocument) or hasattr(container, "__contains__")
        if seg not in container:  # type: ignore[operator]
            container[seg] = tomlkit.table()  # type: ignore[index]
        container = container[seg]  # type: ignore[index]

    leaf = segments[-1]
    # Build a FRESH tomlkit table from block (do not mutate the input mapping).
    new_table = tomlkit.table()
    for key, value in block.items():
        new_table[key] = value

    # Single replace-not-append assignment: if `leaf` already exists it is
    # replaced in place (position preserved, exactly one block in output);
    # otherwise it is created.
    container[leaf] = new_table  # type: ignore[index]
