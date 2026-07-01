"""Pure-domain ``Paths`` object: the root configuration object of the project.

Every filesystem path the tool touches is resolved from a single injected
``home`` through ``Paths.from_home`` — ``~/.codex/config.toml``,
``~/.codex/moonbridge-zai.yml``, ``~/.codex/models_cache.json``, ``~/.zshrc``,
``~/Library/LaunchAgents/``, and the dedicated backup directory. This is the
single source of truth (D-16 analog) for resolved paths: no other module may
hard-code ``~/.codex/...`` literals.

This module lives in the ``services/`` layer (D-09: pure domain services, no
side effects). ``from_home`` is PURE path arithmetic — it performs no IO at
all and no existence checks (D-22 purity contract); directory creation is
deferred to the write boundary in later phases (Phase 3 atomic-write helper /
Phase 4 backends).

Usage contract (D-23):
- **Tests** inject a tmp home: ``Paths.from_home(tmp_path)``. This is the
  primary isolation mechanism (D-14) — a test never resolves the developer's
  real ``$HOME``.
- **Production code** calls ``Paths.default()``, a one-line wrapper over
  ``from_home(Path.home())``. The naming split is what makes SC-2 provable:
  tests always inject, never call ``default()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    """Frozen bundle of every resolved filesystem path the tool touches.

    Frozen (D-22) so a ``Paths`` instance handed to a handler/backend cannot
    be mutated to silently redirect writes — a tampering guard (T-02-01).
    All fields are ``pathlib.Path``; they are set exclusively by
    :meth:`from_home`, so an instance can never be half-resolved.
    """

    codex_dir: Path
    config_toml: Path
    moonbridge_yml: Path
    moonbridge_binary: Path
    models_cache: Path
    zshrc: Path
    launchagents_dir: Path
    backup_dir: Path

    @classmethod
    def from_home(cls, home: str | Path) -> Paths:
        """Resolve all paths off ``home`` via pure arithmetic (no IO).

        Accepts ``str | Path`` and coerces to ``pathlib.Path``. Does NOT
        validate existence, create directories, or read anything — it
        succeeds on a non-existent home (D-23: "no existence validation",
        D-22 purity). Symlinks are left as-is (no ``.resolve()``).

        The 7 resolved paths (D-22 / D-25):

        - ``codex_dir``          = ``home / ".codex"``
        - ``config_toml``        = ``home / ".codex" / "config.toml"``
        - ``moonbridge_yml``     = ``home / ".codex" / "moonbridge-zai.yml"``
        - ``moonbridge_binary``  = ``home / ".codex" / "bin" / "moonbridge``
          (the built Moon Bridge executable; matches the canonical install
          path. Historically ``~/.codex/moon-bridge`` was used and the plist
          ended up pointing at the git-clone DIRECTORY, not the binary.)
        - ``models_cache``       = ``home / ".codex" / "models_cache.json"``
        - ``zshrc``              = ``home / ".zshrc"``
        - ``launchagents_dir``   = ``home / "Library" / "LaunchAgents"``
        - ``backup_dir``         = ``home / ".codex" / ".zai-codex-helper" / "backups"``
        """
        h = Path(home)
        codex_dir = h / ".codex"
        return cls(
            codex_dir=codex_dir,
            config_toml=codex_dir / "config.toml",
            moonbridge_yml=codex_dir / "moonbridge-zai.yml",
            moonbridge_binary=codex_dir / "bin" / "moonbridge",
            models_cache=codex_dir / "models_cache.json",
            zshrc=h / ".zshrc",
            launchagents_dir=h / "Library" / "LaunchAgents",
            backup_dir=codex_dir / ".zai-codex-helper" / "backups",
        )

    @classmethod
    def default(cls) -> Paths:
        """Production entry point: ``from_home(Path.home())``.

        A one-line thin wrapper with no alternate resolution path (D-23).
        Tests never call this — they inject ``tmp_path`` via :meth:`from_home`
        directly; that naming split is what makes SC-2 provable.
        """
        return cls.from_home(Path.home())
