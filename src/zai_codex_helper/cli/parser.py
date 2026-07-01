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


def _emit_restart_warning(stream) -> None:
    """Write a hard-to-miss restart warning to ``stream`` (D-47, PROV-04).

    After every successful ``use zai`` / ``use openai`` write the user MUST be
    told that the Codex Desktop App does NOT live-reload ``config.toml`` — a
    user who opens a new Desktop App thread without restarting will still see
    the old default and conclude ``use zai`` silently failed. This warning is
    the UX-critical guard against that. PROV-04.

    The warning conveys the three D-47 facts:
      (a) the config WAS written (the change is on disk),
      (b) the Codex Desktop App does NOT live-reload ``config.toml``,
      (c) a restart is required for the new default to take effect.
    It also notes the one nuance: the ``codex`` CLI picks the change up on its
    NEXT invocation (no restart needed for the CLI), but the Desktop App needs
    a full restart.

    The stream is taken as a parameter (NOT a hard-coded ``sys.stderr`` inside
    the helper) so a test can capture it via ``capsys`` or pass a fake stream —
    this is the testability seam. The CALLER passes ``sys.stderr`` so the
    warning is visible even when stdout is piped (D-47 "goes to stderr").

    Plain text + ANSI (per CLAUDE.md D-04/D-05, no Rich). The leading ``⚠``
    glyph + UPPERCASE prefix make it impossible to miss in a terminal.
    """
    # ANSI: bold + yellow for the header, reset after. Plain text otherwise —
    # no Rich (CLAUDE.md D-04/D-05). Glyph + UPPERCASE prefix = hard to miss.
    stream.write(
        "\n"
        "\033[1;33m⚠  RESTART REQUIRED\033[0m\n"
        "config.toml was written. The Codex Desktop App does NOT live-reload\n"
        "config.toml — you must restart Codex for the new default to take\n"
        "effect. The `codex` CLI picks up the change on its next invocation\n"
        "(no restart needed for the CLI); the Codex Desktop App needs a full\n"
        "restart.\n"
    )


def _render_apply_result(result, warn_stream) -> None:
    """Render a :class:`ProviderApplyResult` to ``warn_stream`` exactly once.

    The provider-apply primitive (``services.provider_apply.apply_provider``)
    does the write and returns a result; the CLI decides what the user sees:
    a dry-run diff, OR the D-47/PROV-04 restart warning after a real write.
    This is the single place the warning is emitted for the ``use`` handlers
    (and TUI toggle), replacing the old inline pipeline that printed itself.
    """
    if result.dry_run_diff is not None:
        print(result.dry_run_diff, file=warn_stream)
        return
    if result.desktop_restart_required:
        _emit_restart_warning(warn_stream)

def _handle_use_zai(args: argparse.Namespace) -> int:
    """Make Z.ai (``glm-5.2``, ``xhigh``) the Codex default (D-45, PROV-01).

    Phase 7 — the Core Value. This is the command the project exists to
    deliver: ``zai-codex-helper use zai`` writes the canonical Z.ai desired
    state to the real ``~/.codex/config.toml`` end-to-end. Replaces the Phase
    1 ``_stub("use zai")`` wiring (D-03).

    Follows the D-31 restore-handler shape verbatim: lazy imports inside the
    body, resolve ``Paths.default()``, delegate to the shared
    :func:`~zai_codex_helper.services.provider_apply.apply_provider` + render the
    result once, return 0. Does NOT catch :class:`ZaiCodexHelperError` (D-11 —
    owned by :func:`main`), does NOT call ``sys.exit``.

    Args:
        args: The parsed argparse namespace (unused beyond dispatch).

    Returns:
        0 on success (the pipeline raises on failure; success means the
        config was written, post-conditions passed, and the restart warning
        was emitted).
    """
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
    """Revert to the OpenAI default (``gpt-5.5``) — PROV-02, the inverse of :func:`_handle_use_zai`.

    Phase 7 — the reversible half of the Core Value:
    ``zai-codex-helper use openai`` writes ``model = "gpt-5.5"``, removes the
    ``model_provider`` pointer (Codex falls back to its builtin OpenAI
    provider), and PRESERVES the ``[model_providers.zai-moonbridge]`` block so
    a later ``use zai`` does not need to recreate it. Replaces the Phase 1
    ``_stub("use openai")`` wiring (D-03).

    Follows the D-31 restore-handler shape verbatim: lazy imports, resolve
    ``Paths.default()``, delegate to
    :func:`~zai_codex_helper.services.provider_apply.apply_provider` + render the
    result once, return 0. Does NOT catch :class:`ZaiCodexHelperError`, does NOT
    call ``sys.exit``.

    Args:
        args: The parsed argparse namespace (unused beyond dispatch).

    Returns:
        0 on success.
    """
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
    """Roll the user's config back to the one-time ``.bak`` (D-31, SC-2).

    This is the first REAL (non-stub) subcommand handler (Phase 4, D-31).
    It is autonomous — no interactive prompt — and restores unconditionally
    (the "are you sure" UX is a later phase).

    The handler owns NO error formatting. Any
    :class:`zai_codex_helper.__main__.ZaiCodexHelperError` (e.g.
    ``"no backup to restore"``) is allowed to PROPAGATE to
    :func:`zai_codex_helper.__main__.main`, which formats it per D-11
    (one-line ``error: <msg>`` on stderr + exit 1, full traceback under
    ``--debug``). It does NOT call ``sys.exit``, does NOT print to stderr,
    and does NOT wrap the coordinator call in ``try/except``.

    Delegates to :meth:`BackupCoordinator.restore` (Plan 04-01) — the
    coordinator itself is NOT redefined here. Paths resolve via
    :meth:`Paths.default()` (never hard-codes ``~/.codex``).

    Passes the real :class:`TomlBackend` to the coordinator so it sees a
    full :class:`ConfigBackend` (path + declared ``backup_mode``), not a
    path-only stand-in.
    """
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
    """Print the current provider, config paths, and version — READ-ONLY (D-50..D-55, PROV-05).

    Phase 8 — the observability companion to the Core Value. After ``use zai``
    a user runs ``status`` to confirm Z.ai is active at a glance, without
    hand-reading ``config.toml``. Prints three plain-text sections (D-50):

    1. **Provider** — the active default provider (Z.ai vs OpenAI builtin) with
       the flat top-level ``model`` and ``model_reasoning_effort`` values. For
       a missing config: "OpenAI (builtin default), config.toml not yet
       created" (D-52 — missing != broken).
    2. **Config paths** — every ``Paths.default()``-resolved location
       (``config_toml``, ``moonbridge_yml``, ``models_cache``, ``zshrc``,
       ``launchagents_dir``) with an ``[exists]`` / ``[missing]`` marker from
       the read-only ``Path.exists()``.
    3. **Version** — ``zai-codex-helper <__version__>`` (D-16 single source).

    READ-ONLY GUARANTEE (D-51 — load-bearing, T-08-01): the handler calls ONLY
    ``TomlBackend.read()`` (when the config exists), ``Path.exists()`` for
    path markers, and ``zai_codex_helper.__version__``. It does NOT call
    ``write_canonical`` / ``backup_once`` / ``atomic_write`` / ``os.replace``
    / ``os.chmod`` / ``unlink`` / ``mkdir`` / ``rename`` — enforced by the
    static guard in ``tests/test_status.py`` and the byte-identical HOME
    snapshot test across three seed states.

    ERROR CONTRACT (D-52, T-08-02): the handler does NOT catch
    :class:`ZaiCodexHelperError` and does NOT call ``sys.exit`` — it lets the
    read-boundary translator's :class:`ZaiCodexHelperError` (raised on
    malformed TOML) propagate to :func:`zai_codex_helper.__main__.main`, which
    formats it per D-11 (one-line ``error: <msg>`` + exit 1, traceback under
    ``--debug``). Missing config is NOT an error (exit 0, D-52).

    Args:
        args: The parsed argparse namespace (unused beyond dispatch).

    Returns:
        0 on a parseable config AND on a missing config. A broken config
        raises before return (translated by the read boundary; ``main``
        returns 1).
    """
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
    """Install the Moon Bridge LaunchAgent (Phase 13, SERV-01/SERV-04, D-83/D-86).

    Autonomous (no prompt). Writes the canonical plist
    (KeepAlive/RunAtLoad/absolute binary path via Phase 9's
    :class:`PlistBackend`), runs ``launchctl bootstrap gui/<UID> <plist>``, and
    verifies the agent is actually loaded + listening (SERV-04 — bootstrap exit
    0 alone is insufficient). Replaces the Phase 1 ``_stub("install-service")``
    wiring (D-02).

    Follows the D-31 restore / D-45 use-handler / D-76 setup-handler shape
    verbatim: lazy imports inside the body, resolve ``Paths.default()``,
    delegate to :func:`zai_codex_helper.services.lifecycle.install_service`,
    return the int. Does NOT catch :class:`ZaiCodexHelperError` (D-11 — owned
    by :func:`zai_codex_helper.__main__.main`), does NOT call ``sys.exit``.

    The ``runner`` param is NOT forwarded — it defaults to
    :func:`subprocess.run` inside ``install_service`` (the seam is for unit
    tests only; threat T-13-07). A non-zero exit / :class:`ZaiCodexHelperError`
    (platform gate on non-darwin, real bootstrap failure, verify-not-loaded)
    propagates to :func:`main` per D-11.

    Args:
        args: The parsed argparse namespace (unused beyond dispatch).

    Returns:
        0 on success (the agent is registered AND verified loaded; a loaded-
        but-not-listening state is a WARNING, still exit 0 — SERV-04).
    """
    from zai_codex_helper.services.lifecycle import install_service
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    # Phase 15 (D-95): forward the root --dry-run flag so
    # `install-service --dry-run` prints a "would write plist + bootstrap"
    # summary and writes/calls nothing.
    return install_service(paths, dry_run=getattr(args, "dry_run", False))


def _handle_uninstall_service(args: argparse.Namespace) -> int:
    """Uninstall the Moon Bridge LaunchAgent (Phase 13, SERV-02/SERV-03, D-84/D-85).

    Autonomous (no prompt). Runs ``launchctl bootout gui/<UID>/<LABEL>`` (the
    SAME shared Label install bootstrapped — D-85, never an orphan) and removes
    the plist. Idempotent: running uninstall twice (or after a manual
    ``bootout``) exits 0 because both the already-booted-out condition (EIO rc
    36 / "Could not find service") and the missing-plist condition are
    swallowed. A REAL failure (e.g. "Operation not permitted") raises. Replaces
    the Phase 1 ``_stub("uninstall-service")`` wiring (D-02).

    Follows the D-31 / D-45 / D-76 handler shape verbatim: lazy imports,
    ``Paths.default()``, delegate to
    :func:`zai_codex_helper.services.lifecycle.uninstall_service`, return the
    int. Does NOT catch :class:`ZaiCodexHelperError` (D-11), does NOT call
    ``sys.exit``. The ``runner`` param is NOT forwarded (the seam is for unit
    tests only; threat T-13-07).

    Args:
        args: The parsed argparse namespace (unused beyond dispatch).

    Returns:
        0 on success (the agent is de-registered AND the plist removed).
    """
    from zai_codex_helper.services.lifecycle import uninstall_service
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    # Phase 15 (D-95): forward the root --dry-run flag (symmetric with
    # install-service) so `uninstall-service --dry-run` prints a summary and
    # does NOT really bootout the agent + delete the plist.
    return uninstall_service(paths, dry_run=getattr(args, "dry_run", False))


def _handle_setup(args: argparse.Namespace) -> int:
    """Run the guided end-to-end onboarding (D-76..D-82, SETUP-01/02/03).

    Phase 12 — the capstone. This is the command a new user runs ONCE to wire
    up the whole Codex ⇄ Moon Bridge ⇄ Z.ai link: it walks provider choice →
    API key → ``moonbridge-zai.yml``@0600 → Moon Bridge build → shell helpers
    opt-in → apply the chosen provider → LaunchAgent OFFER → summary. The same
    flow runs headless via ``--yes`` / ``--no-input`` (D-79). Replaces the
    Phase 1 ``_stub("setup")`` wiring (D-02).

    Follows the D-31 restore / D-45 use-handler shape verbatim: lazy imports
    inside the body, resolve ``Paths.default()``, delegate, return the int the
    orchestrator returns (0 on success). Does NOT catch
    :class:`ZaiCodexHelperError` (D-11 — owned by :func:`main`), does NOT call
    ``sys.exit``.

    D-79 mapping: ``getattr(args, 'yes', False) or getattr(args, 'no_input', False)`` both force headless mode
    (every ``confirm()`` returns True; provider defaults to zai; ZAI_API_KEY
    env becomes REQUIRED). The ``--no-input`` flag is added in
    :func:`build_parser` alongside ``--yes``.

    Args:
        args: The parsed argparse namespace. Reads ``args.yes``,
            ``args.no_input``, and ``getattr(args, 'dry_run', False)``.

    Returns:
        0 on success (the orchestrator raises on failure; success means the
        full onboarding flow completed and the chosen provider is applied).
    """
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
    """Macro: turn Z.ai ON end-to-end — one command for the Core Value.

    Delegates to :func:`install_macro` (single source of truth, shared with the
    TUI). After this, a bare ``codex`` (no flags/env/profile — what BOTH Codex
    CLI and Desktop read) starts on Z.ai. Does NOT catch
    :class:`ZaiCodexHelperError` (D-11 — owned by :func:`main`).
    """
    from zai_codex_helper.services.install import install_macro
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    install_macro(
        paths,
        dry_run=getattr(args, "dry_run", False),
        headless=getattr(args, "yes", False) or getattr(args, "no_input", False),
    )
    return 0


def _handle_uninstall(args: argparse.Namespace) -> int:
    """Macro: turn Z.ai OFF — revert Codex to the OpenAI default, fully.

    Delegates to :func:`uninstall_macro` (shared with the TUI). After this, a
    bare ``codex`` starts on OpenAI, and the Moon Bridge service is gone. Does
    NOT catch :class:`ZaiCodexHelperError` (D-11).
    """
    from zai_codex_helper.services.install import uninstall_macro
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    uninstall_macro(
        paths,
        dry_run=getattr(args, "dry_run", False),
    )
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    """Diagnose the Codex ⇄ Moon Bridge ⇄ Z.ai chain (Phase 14, DIAG-01..04, D-89..D-94).

    The SEVENTH real (non-stub) subcommand — the LAST Phase 1 stub to become
    real. ``zai-codex-helper doctor`` walks the chain link-by-link and prints a
    colored verdict (``[OK]``/``[!]``/``[X]``) plus a ``To fix:`` hint for
    every non-pass check, exiting ``0`` unless at least one check FAILS.
    READ-ONLY (D-94): no writes, no launchctl bootstrap, no build.

    Follows the D-31 restore / D-45 use-handler / D-83 install-handler shape
    verbatim: lazy imports inside the body, resolve ``Paths.default()``,
    delegate to :func:`zai_codex_helper.services.doctor.run_doctor`, return
    the int exit code run_doctor returns. doctor owns its own colored output
    and its exit code (it does NOT raise :class:`ZaiCodexHelperError`
    per-check — it catches, marks the CheckResult, continues, and computes the
    exit code at the end), so the handler is catch-free like
    :func:`_handle_install_service`.

    The ``runner`` / ``http_client`` / ``environ`` params are NOT forwarded —
    they default to :func:`subprocess.run`, an internally-constructed
    hard-timeout :class:`httpx.Client`, and ``os.environ`` inside run_doctor
    (the seams are for unit tests only; mirrors the T-13-07 discipline).

    Args:
        args: The parsed argparse namespace (unused beyond dispatch).

    Returns:
        ``0`` if no check failed; ``1`` if any check failed. WARNs do NOT
        fail doctor.
    """
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
    """Open the interactive arrow-key menu — the bare ``zai-codex-helper`` default.

    This is the root parser's default ``func`` (no subcommand), so a bare
    ``zai-codex-helper`` invocation lands here. A thin shell like every other
    handler: it delegates to :func:`zai_codex_helper.cli.tui.run`, which owns
    its own event loop and catches :class:`ZaiCodexHelperError` per-action (so
    a failed Install / Uninstall / Doctor returns to the menu instead of
    exiting). The ``--dry-run`` flag is forwarded so ``Install`` previews
    instead of writing (mirrors the ``install-service --dry-run`` path).
    """
    from zai_codex_helper.cli import tui

    return tui.run(args)


def _handle_set_key(args: argparse.Namespace) -> int:
    """Replace the Z.ai API key in ``moonbridge-zai.yml`` (``set-key``).

    A thin shell like every other handler: resolve ``Paths.default()``,
    delegate to :func:`zai_codex_helper.services.api_key.set_key`, return the
    int. Forwards ``--dry-run`` so the change previews as a redacted diff and
    writes nothing. Does NOT catch :class:`ZaiCodexHelperError` (D-11 — owned
    by :func:`main`), does NOT call ``sys.exit``.
    """
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
