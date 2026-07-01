"""Argparse parser builder for the ``zai-codex-helper`` CLI.

The dispatch contract: each subcommand registers a handler via
``set_defaults(func=...)``, and :func:`zai_codex_helper.__main__.main` calls
``args.func(args)``. Handlers are THIN SHELLS — resolve ``Paths.default()``,
delegate to a service, return its int. They do NOT catch/print/exit (D-11): a
:class:`ZaiCodexHelperError` propagates to :func:`main`, which formats it as
one-line stderr + exit 1 (full traceback under ``--debug``). Bare
``zai-codex-helper`` (no subcommand) opens the interactive TUI.

The subcommands: ``use zai`` / ``use openai`` (the Core Value — switch the
config.toml provider via the shared services primitive
:func:`~zai_codex_helper.services.provider_apply.apply_provider`, then render the
restart warning once via :func:`_render_apply_result`), ``restore``
(roll config.toml back to its one-shot ``.bak``), ``status`` (read-only
provider/paths/version), ``setup`` (the onboarding orchestrator),
``set-key`` (rotate the Z.ai key), ``install-service`` / ``uninstall-service``
(the Moon Bridge LaunchAgent), and ``doctor`` (the read-only chain diagnostic).

Root flags (``--debug`` / ``--yes`` / ``--no-input`` / ``--dry-run``) attach
via a single shared parent parser so they parse BOTH before and after the
subcommand.
"""

import argparse
import sys

# The restart-warning + result-render helpers now live in the services layer
# (services.provider_apply) so the ``uninstall`` macro can surface them without a
# services→cli import. Re-exported here under their historical private names so
# the ``use`` handlers, the TUI, and existing tests keep resolving them.
from zai_codex_helper.services.provider_apply import (  # noqa: E402, F401
    render_apply_result as _render_apply_result,
)
from zai_codex_helper.services.provider_apply import (  # noqa: E402, F401
    render_restart_warning as _emit_restart_warning,
)


def _handle_use_zai(args: argparse.Namespace) -> int:
    """Make Z.ai (``glm-5.2``, ``xhigh``) the Codex default (D-45, PROV-01)."""
    # Lazy imports (mirrors `_handle_restore`'s discipline so parser.py stays
    # import-light at module load).
    from zai_codex_helper.services.paths import Paths
    from zai_codex_helper.services.provider_apply import apply_provider
    from zai_codex_helper.services.providers import apply_zai

    # Phase 15 (D-95): forward the root --dry-run flag so `use zai --dry-run`
    # previews the would-be config.toml change as a diff and writes nothing.
    result = apply_provider(
        Paths.default(), apply_zai, dry_run=getattr(args, "dry_run", False)
    )
    _render_apply_result(result, sys.stderr)
    return 0


def _handle_use_openai(args: argparse.Namespace) -> int:
    """Revert to OpenAI (``gpt-5.5``) — PROV-02."""
    from zai_codex_helper.services.paths import Paths
    from zai_codex_helper.services.provider_apply import apply_provider
    from zai_codex_helper.services.providers import apply_openai

    # Phase 15 (D-95): forward the root --dry-run flag so `use openai --dry-run`
    # previews the would-be config.toml change as a diff and writes nothing.
    result = apply_provider(
        Paths.default(), apply_openai, dry_run=getattr(args, "dry_run", False)
    )
    _render_apply_result(result, sys.stderr)
    return 0


def _handle_restore(args: argparse.Namespace) -> int:
    """Roll config back to the one-time ``.bak`` (D-31, SC-2)."""
    # Lazy imports keep `parser.py` import-light and side-effect-free at
    # module load (avoids walking _backup -> __main__ -> parser on import).
    from zai_codex_helper.backends._backup import BackupCoordinator
    from zai_codex_helper.backends.toml import TomlBackend
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    # Pass the REAL TomlBackend (not a path-only stand-in) so the coordinator
    # sees a full ConfigBackend — including its declared backup_mode.
    backend = TomlBackend(paths)
    BackupCoordinator.restore(paths, backend)
    print(f"restored {paths.config_toml}")
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    """Print provider, config paths, and version — READ-ONLY (D-50..D-55, PROV-05)."""
    # Lazy imports keep `parser.py` import-light at module load (mirrors the
    # `_handle_restore` / `_handle_use_zai` discipline).
    from zai_codex_helper import __version__
    from zai_codex_helper.backends.toml import TomlBackend
    from zai_codex_helper.services.paths import Paths
    from zai_codex_helper.services.status import detect_provider, read_for_status

    # a. Resolve paths via the production entry point (D-46). In tests the
    #    autouse `_isolate_home` fixture repoints HOME at tmp_path, so
    #    Paths.default() resolves under the sandbox — no real-HOME read.
    paths = Paths.default()
    # b. Concrete TOML backend (Phase 5) bound to paths.config_toml.
    backend = TomlBackend(paths)

    # c. Read the config read-only via the Phase 8 read boundary. Returns None
    #    when the config is missing (D-52: missing != broken). Raises
    #    ZaiCodexHelperError on malformed TOML — let it propagate (D-11).
    doc = read_for_status(backend)

    # d. Pure provider detection (D-53, D-54 — no IO in services.status).
    descriptor = detect_provider(doc)

    # e. Render the three D-50 sections as plain text + minimal ANSI markers
    #    (CLAUDE.md D-04/D-05 — no Rich). Glanceable: a user runs `status` to
    #    confirm, not to study.
    lines: list[str] = []
    lines.append("Provider:")
    lines.append(f"  {descriptor.provider_label}")
    if descriptor.config_present:
        # Report the observed model/effort values (None -> "unset").
        model_str = descriptor.model if descriptor.model is not None else "unset"
        lines.append(f"  model: {model_str}")
        effort_str = (
            descriptor.model_reasoning_effort
            if descriptor.model_reasoning_effort is not None
            else "unset"
        )
        lines.append(f"  model_reasoning_effort: {effort_str}")
    else:
        # D-52 missing-config note: OpenAI builtin default, config not yet created.
        lines.append("  config.toml not yet created")

    lines.append("")
    lines.append("Config paths:")
    # D-50 lists these five paths. backup_dir / codex_dir are NOT in D-50's
    # paths section — do not report them.
    for field in (
        "config_toml",
        "moonbridge_yml",
        "models_cache",
        "zshrc",
        "launchagents_dir",
    ):
        resolved = getattr(paths, field)
        # Read-only existence marker (D-51).
        marker = "[exists]" if resolved.exists() else "[missing]"
        lines.append(f"  {field}: {resolved} {marker}")

    lines.append("")
    lines.append("Version:")
    lines.append(f"  zai-codex-helper {__version__}")

    print("\n".join(lines))
    return 0


def _handle_install_service(args: argparse.Namespace) -> int:
    """Install the Moon Bridge LaunchAgent (SERV-01/SERV-04, D-83/D-86)."""
    from zai_codex_helper.services.lifecycle import install_service
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    # Phase 15 (D-95): forward the root --dry-run flag so
    # `install-service --dry-run` prints a "would write plist + bootstrap"
    # summary and writes/calls nothing.
    return install_service(
        paths,
        dry_run=getattr(args, "dry_run", False),
        force=getattr(args, "force", False),
    )


def _handle_uninstall_service(args: argparse.Namespace) -> int:
    """Uninstall the Moon Bridge LaunchAgent (SERV-02/SERV-03, D-84/D-85)."""
    from zai_codex_helper.services.lifecycle import uninstall_service
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    # Phase 15 (D-95): forward the root --dry-run flag (symmetric with
    # install-service) so `uninstall-service --dry-run` prints a summary and
    # does NOT really bootout the agent + delete the plist.
    return uninstall_service(paths, dry_run=getattr(args, "dry_run", False))


def _handle_setup(args: argparse.Namespace) -> int:
    """Run guided end-to-end onboarding (D-76..D-82, SETUP-01/02/03)."""
    # Lazy imports keep `parser.py` import-light at module load (mirrors the
    # `_handle_restore` / `_handle_use_zai` discipline). The orchestrator owns
    # ALL step logic; the handler is a thin arg-forwarding shell (D-81).
    from zai_codex_helper.services.paths import Paths
    from zai_codex_helper.services.setup import run_setup

    paths = Paths.default()
    return run_setup(
        paths,
        yes=getattr(args, "yes", False) or getattr(args, "no_input", False),
        dry_run=getattr(args, "dry_run", False),
    )


def _handle_install(args: argparse.Namespace) -> int:
    """Macro: turn Z.ai ON end-to-end."""
    from zai_codex_helper.services.install import install_macro
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    install_macro(
        paths,
        dry_run=getattr(args, "dry_run", False),
        headless=getattr(args, "yes", False) or getattr(args, "no_input", False),
        force=getattr(args, "force", False),
    )
    return 0


def _handle_uninstall(args: argparse.Namespace) -> int:
    """Macro: turn Z.ai OFF end-to-end."""
    from zai_codex_helper.services.install import uninstall_macro
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    uninstall_macro(
        paths,
        dry_run=getattr(args, "dry_run", False),
    )
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    """Diagnose the Codex ⇄ Moon Bridge ⇄ Z.ai chain (DIAG-01..04, D-89..D-94)."""
    from zai_codex_helper.services.doctor import run_doctor, run_with_spinner
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    # The POST probe is slow (3–20s upstream); run it in a background thread
    # with a spinner, abortable via Ctrl-C (SIGINT) — the standard interrupt
    # for a non-interactive CLI command (no cbreak/Esc here).
    import signal

    aborted = {"yes": False}
    prev_int = signal.getsignal(signal.SIGINT)

    def _on_sigint(_signum, _frame):
        aborted["yes"] = True

    def _cli_post_runner(call):
        signal.signal(signal.SIGINT, _on_sigint)
        try:
            return run_with_spinner(call, should_abort=lambda: aborted["yes"])
        finally:
            signal.signal(signal.SIGINT, prev_int)

    return run_doctor(paths, post_check_runner=_cli_post_runner)


def _handle_tui(args: argparse.Namespace) -> int:
    """Open the interactive arrow-key menu (bare ``zai-codex-helper`` default)."""
    from zai_codex_helper.cli import tui

    return tui.run(args)


def _handle_set_key(args: argparse.Namespace) -> int:
    """Replace the Z.ai API key in ``moonbridge-zai.yml``."""
    from zai_codex_helper.services.api_key import set_key
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    return set_key(paths, dry_run=getattr(args, "dry_run", False))


def build_parser() -> argparse.ArgumentParser:
    """Build the root ``zai-codex-helper`` argparse parser.

    The root parser owns the global flags (``--debug`` / ``--yes`` /
    ``--dry-run``) and the subcommand dispatch table. Invoking the CLI with NO
    subcommand opens the interactive TUI (the root's default ``func``); every
    subcommand overrides it via its own ``set_defaults``.
    """
    # Global flags (B-2 fix): work BOTH before AND after the subcommand. ONE
    # shared parent parser (SUPPRESS defaults) is attached to the root parser AND
    # every subparser via parents=[sub_flags], so `--debug`/`--yes`/`--no-input`/
    # `--dry-run` parse in either position. SUPPRESS means a subparser copy does
    # not override a value the root already parsed (argparse subparser quirk).
    sub_flags = argparse.ArgumentParser(add_help=False)
    sub_flags.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show full traceback on error",
    )
    sub_flags.add_argument(
        "--yes",
        "-y",
        action="store_true",
        default=argparse.SUPPRESS,
        help="answer yes to all prompts",
    )
    sub_flags.add_argument(
        "--no-input",
        action="store_true",
        default=argparse.SUPPRESS,
        help="non-interactive",
    )
    sub_flags.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="preview without writing",
    )

    parser = argparse.ArgumentParser(
        prog="zai-codex-helper",
        description="Manage the Codex ⇄ Moon Bridge ⇄ Z.ai link.",
        parents=[sub_flags],
    )
    # No subcommand → open the interactive TUI (the bare ``zai-codex-helper``
    # invocation). Every subcommand overrides this via its own set_defaults.
    parser.set_defaults(func=_handle_tui)

    subparsers = parser.add_subparsers(
        dest="cmd",
        required=False,
        metavar="<command>",
    )

    # `use` — nested provider sub-subs (D-03).
    p_use = subparsers.add_parser(
        "use",
        help="switch the default Codex provider",
        parents=[sub_flags],
    )
    use_sub = p_use.add_subparsers(
        dest="provider",
        required=True,
        metavar="<provider>",
    )
    use_sub.add_parser(
        "zai",
        help="make Z.ai (glm-5.2 xhigh) the default",
        parents=[sub_flags],
    ).set_defaults(func=_handle_use_zai)
    use_sub.add_parser(
        "openai",
        help="revert to OpenAI",
        parents=[sub_flags],
    ).set_defaults(func=_handle_use_openai)

    # `restore` — the FIRST real (non-stub) subcommand (Phase 4, D-31).
    p_restore = subparsers.add_parser(
        "restore",
        help="restore config from the one-time backup",
        parents=[sub_flags],
    )
    p_restore.set_defaults(func=_handle_restore)

    # `status` — read-only observability (Phase 8, D-50..D-55).
    p_status = subparsers.add_parser(
        "status",
        help="show current provider, config paths, and version",
        parents=[sub_flags],
    )
    p_status.set_defaults(func=_handle_status)

    # `setup` — onboarding capstone (Phase 12, D-76..D-82).
    p_setup = subparsers.add_parser(
        "setup",
        help="guided end-to-end onboarding",
        parents=[sub_flags],
    )
    p_setup.set_defaults(func=_handle_setup)

    # `install` / `uninstall` — macros: turn Z.ai ON/OFF end-to-end (Core Value
    # in one command). install = setup + apply_zai + install_service; uninstall
    # = apply_openai + uninstall_service + rm yml.
    p_install = subparsers.add_parser(
        "install",
        help="turn Z.ai ON end-to-end (setup + config + Moon Bridge)",
        parents=[sub_flags],
    )
    p_install.add_argument(
        "--force",
        action="store_true",
        help="reinstall the LaunchAgent even if already running (bounces the service)",
    )
    p_install.set_defaults(func=_handle_install)
    p_uninstall = subparsers.add_parser(
        "uninstall",
        help="turn Z.ai OFF (revert config + stop Moon Bridge + rm yml)",
        parents=[sub_flags],
    )
    p_uninstall.set_defaults(func=_handle_uninstall)

    # `set-key` — replace only the Z.ai API key in moonbridge-zai.yml.
    p_setkey = subparsers.add_parser(
        "set-key",
        help="replace the Z.ai API key in moonbridge-zai.yml",
        parents=[sub_flags],
    )
    p_setkey.set_defaults(func=_handle_set_key)

    # `install-service` / `uninstall-service` (Phase 13, D-83..D-88; SERV-01..04).
    p_install = subparsers.add_parser(
        "install-service",
        help="install the Moon Bridge LaunchAgent",
        parents=[sub_flags],
    )
    p_install.add_argument(
        "--force",
        action="store_true",
        help="reinstall even if already running (bounces the service)",
    )
    p_install.set_defaults(func=_handle_install_service)
    p_uninstall = subparsers.add_parser(
        "uninstall-service",
        help="uninstall the Moon Bridge LaunchAgent",
        parents=[sub_flags],
    )
    p_uninstall.set_defaults(func=_handle_uninstall_service)

    # `doctor` — diagnostic (Phase 14, D-89..D-94; DIAG-01..04).
    p_doctor = subparsers.add_parser(
        "doctor",
        help="diagnose the Codex ⇄ Moon Bridge ⇄ Z.ai chain",
        parents=[sub_flags],
    )
    p_doctor.set_defaults(func=_handle_doctor)

    return parser
