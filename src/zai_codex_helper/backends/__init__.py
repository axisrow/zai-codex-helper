"""File-IO boundary layer.

Every disk mutation lives behind a ``ConfigBackend`` ABC
(read / exists / write_canonical / backup_once), arriving in Phase 4.
Concrete backends — ``TomlBackend``, ``YamlBackend``, ``JsonBackend``,
``ShellBackend``, ``PlistBackend`` — arrive in their own phases
(5 / 9 / …). Centralising all IO behind this boundary is what makes HOME
isolation (tests) and idempotent setup possible.

Phase 1: intentionally empty.
"""
