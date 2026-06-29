"""File-IO boundary layer.

Every disk mutation lives behind a ``ConfigBackend`` ABC
(read / exists / write_canonical / backup_once), delivered in Phase 4
(see ``base.py`` for :class:`ConfigBackend`, ``_backup.py`` for
:class:`BackupCoordinator`). ``TomlBackend`` is delivered in Phase 5 (see ``toml.py`` for the first
concrete backend — ``config.toml`` read/write/upsert via ``tomlkit``);
the remaining concrete backends — ``YamlBackend``, ``JsonBackend``,
``ShellBackend``, ``PlistBackend`` — arrive in their own phases (9 / …). Centralising all IO behind this
boundary is what makes HOME isolation (tests) and idempotent setup
possible.
"""
