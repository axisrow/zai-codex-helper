"""``YamlBackend`` — the concrete :class:`ConfigBackend` for the secrets file
(Phase 9, plan 09-01; decisions D-56, D-61, D-62).

``~/.codex/moonbridge-zai.yml`` is the ONE file this tool manages that holds the
user's ``ZAI_API_KEY``. CLAUDE.md §"File Permissions & Backup Conventions"
mandates that ANY file holding the key lands at ``0600``; SECR-02 turns that
mandate into a requirement. This backend is the single place that guarantee is
enforced for the YAML file type: ``write_canonical`` defaults its ``mode``
argument to the explicit ``0o600`` (D-56 — LOAD-BEARING) so a caller cannot
forget to restrict the file. The restriction is structural, not conventional.

Why the explicit ``0o600`` (not ``mode=None``):

- ``atomic_write(mode=None)`` inherits the temp file's mode. That happens to be
  ``0o600`` today (``mkstemp`` is umask-independent), but relying on that default
  for a SECRETS file is fragile — a future tempfile/impl change could widen it to
  a world-readable key. So the secrets path does NOT lean on the default.
- The secrets path therefore passes an EXPLICIT ``0o600``. Verified empirically
  that ``atomic_write(mode=0o600)`` correctly chmods the destination to
  ``0o600`` after the atomic replace. The explicit arg is both safe and
  self-documenting (D-56).

Library discipline (CLAUDE.md §"What NOT to Use"; D-61): this module calls
``yaml.safe_load`` and ``yaml.safe_dump`` ONLY. NEVER ``yaml.load`` or
``yaml.dump`` — bare ``load``/``dump`` permit arbitrary Python object
construction (a deserialization / RCE risk). ``ruamel.yaml`` is not used: the
helper writes the YAML fresh from a canonical shape, so PyYAML's lighter
footprint wins (no comment-preservation needed). This discipline is pinned by
``test_yaml_uses_safe_load_and_safe_dump_only``.

Structural delegation (D-29): ``write_canonical`` serializes then routes the
payload through ``self._write_via_atomic`` (the ABC's private helper that calls
``atomic_write``). It NEVER calls ``atomic_write`` directly — mirroring
``TomlBackend``. ``backup_once`` is inherited VERBATIM from
:class:`ConfigBackend` (D-30); this class does NOT override it, so the
coordinator's sentinel-gated idempotency gate cannot be bypassed.

Scope discipline (D-38 analog): this module is a GENERIC IO primitive — it
parses YAML, writes YAML, and restricts the file mode. It does NOT know what
``ZAI_API_KEY`` / ``base_url`` / Moon Bridge mean semantically. Phase 12
``setup`` calls this backend; Phase 9 delivers only the backend + its proof. No
``setup`` / ``use`` / ``doctor`` / Moon-Bridge-build logic lives here.
"""

from __future__ import annotations

from typing import Any

import yaml

from zai_codex_helper.backends.base import ConfigBackend
from zai_codex_helper.services.paths import Paths

__all__ = ["YamlBackend"]


class YamlBackend(ConfigBackend):
    """Concrete :class:`ConfigBackend` for ``~/.codex/moonbridge-zai.yml`` (D-56).

    The secrets backend: this is the file that holds ``ZAI_API_KEY``, so
    ``write_canonical`` defaults to the restricted mode ``0o600`` (CLAUDE.md
    §"File Permissions", SECR-02). The subclass hard-codes the ``Paths`` field
    name (``"moonbridge_yml"``) so callers only pass the :class:`Paths`
    instance — no ``~/.codex`` literal is ever hard-coded here (D-33 analog /
    T-09 path-tampering surface). The path is resolved by the ABC constructor.

    - ``read`` returns the parsed YAML object via ``yaml.safe_load`` (a ``dict``
      for the canonical moonbridge-zai.yml shape).
    - ``write_canonical`` serializes via ``yaml.safe_dump`` (CLAUDE.md-canonical
      args: ``sort_keys=False``, ``default_flow_style=False``,
      ``allow_unicode=True``) then routes through ``_write_via_atomic`` at the
      explicit ``0o600`` (D-56 LOAD-BEARING; D-29 structural delegation).
    - ``backup_once`` is inherited as-is from :class:`ConfigBackend` (D-30 —
      no override; the coordinator gate cannot be bypassed).
    """

    def __init__(self, paths: Paths) -> None:
        """Bind to ``paths.moonbridge_yml`` via the ABC constructor (D-56, D-62).

        Args:
            paths: The injected :class:`Paths` bundle (frozen, D-22). Resolved
                to ``paths.moonbridge_yml`` by the inherited constructor; a
                misnamed field would fail fast there, not deep in a later write.
        """
        super().__init__(paths, "moonbridge_yml")

    def read(self) -> Any:
        """Parse ``moonbridge-zai.yml`` via ``yaml.safe_load`` (D-56, D-61).

        Returns the parsed YAML object — a ``dict`` for the canonical
        moonbridge-zai.yml shape, or ``None`` if the file is empty. Phase 12
        ``setup`` reads this to inspect the stored key / base_url.

        If the file does not exist, ``FileNotFoundError`` propagates (D-38
        analog — generic backend; the "no config yet" branch is the caller's
        job). ``yaml.safe_load`` is the ONLY load path: bare ``yaml.load`` is
        forbidden (CLAUDE.md §"What NOT to Use"; arbitrary-object-construction
        risk).
        """
        return yaml.safe_load(self._path.read_text(encoding="utf-8"))

    def exists(self) -> bool:
        """Return ``True`` iff ``moonbridge-zai.yml`` exists on disk (D-56)."""
        return self._path.exists()

    def write_canonical(
        self,
        content: Any,
        mode: int | None = 0o600,
    ) -> None:
        """Write ``content`` to ``moonbridge-zai.yml`` at ``0o600`` (D-56, SECR-02).

        Serializes ``content`` via ``yaml.safe_dump`` with the CLAUDE.md-canonical
        args (``sort_keys=False``, ``default_flow_style=False``,
        ``allow_unicode=True``) then routes the payload through
        ``self._write_via_atomic`` — the ABC's private helper that calls
        ``atomic_write(self._path, ..., mode)`` (D-29 structural delegation;
        never call ``atomic_write`` directly here).

        ``mode`` defaults to ``0o600`` — NOT ``None`` — because this file holds
        the API key (D-56 LOAD-BEARING, SECR-02, CLAUDE.md §"File Permissions").
        The default enforces the secret posture without relying on the caller
        to remember. A caller MAY pass an explicit mode to override, but the
        default is already the restricted mode. NOTE on D-DEFERRED-01:
        ``atomic_write(mode=None)`` does NOT preserve an existing destination
        mode (it inherits the temp's ``0o600``); the secrets path sidesteps
        that fragility by passing the explicit ``0o600``.

        ``yaml.safe_dump`` returns a ``str`` (UTF-8 when ``allow_unicode=True``);
        ``_write_via_atomic`` encodes ``str`` to UTF-8 bytes (see
        ``_atomic.py``). ``yaml.safe_dump`` is the ONLY dump path: bare
        ``yaml.dump`` is forbidden (CLAUDE.md §"What NOT to Use").

        This method does NOT call ``backup_once``: the ABC surface gates backup
        at a higher layer (D-38 analog — primitives only).
        """
        serialized = yaml.safe_dump(
            content,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        )
        self._write_via_atomic(serialized, mode)
