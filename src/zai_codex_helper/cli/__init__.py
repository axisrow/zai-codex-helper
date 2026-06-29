"""Presentation / command layer.

This layer is the user-facing surface of the CLI: it parses ``argv`` via
``argparse``, dispatches to per-command handlers, and formats user-facing
output. It contains NO business logic (that lives in :mod:`zai_codex_helper.services`)
and performs NO direct file IO (that lives in :mod:`zai_codex_helper.backends`).

Phase 1 holds only :mod:`zai_codex_helper.cli.parser` (the argparse builder)
plus stub handlers; real command implementations arrive in later phases
(``use`` → 7, ``status`` → 8, ``doctor`` → 14, ``setup`` → 12,
``install-service`` / ``uninstall-service`` → 13).
"""
