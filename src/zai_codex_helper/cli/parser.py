"""Argparse parser builder for the ``zai-codex-helper`` CLI.

The parser produced here is the dispatch contract every later phase plugs
into: each subcommand registers a handler via ``set_defaults(func=...)``,
and :func:`zai_codex_helper.__main__.main` calls ``args.func(args)``. Phase 1
wired stub handlers that print ``"<name>: not implemented in this phase"``;
phases 7/8/12/13/14 replace those stubs with real handlers by swapping the
``func`` default — no dispatch code changes required.

Phase 4 (D-31): ``restore`` is the FIRST real (non-stub) subcommand. It
calls :meth:`BackupCoordinator.restore` (Plan 04-01) via the D-11 error
contract — the handler does NOT catch/print/exit itself; any
:class:`ZaiCodexHelperError` propagates to :func:`main`, which formats it as
one-line stderr + exit 1 (and re-raises under ``--debug``).

Phase 7 (D-45/D-47, PROV-01/02/04): ``use zai`` and ``use openai`` are the
second and third real subcommands — the Core Value. They delegate to the
shared :func:`_apply_provider_pipeline` (the D-45 end-to-end write path:
seed-if-missing → backup_once → read → apply_zai/apply_openai →
write_canonical → check_postconditions → restart warning) and emit a
hard-to-miss restart warning to stderr (D-47). The remaining commands remain
stubs until their phases.

Phase 8 (D-50..D-55, PROV-05): ``status`` is the read-only observability
companion to the Core Value. After ``use zai``, a user runs ``status`` to
confirm Z.ai is active at a glance — provider + config paths + version, in
plain text, with NO writes (D-51 — load-bearing). It reuses Phase 5's
:class:`TomlBackend.read` (read-only) via the Phase 8 read-boundary
translator (:func:`zai_codex_helper.services.status.read_for_status`), Phase
2's :meth:`Paths.default`, Phase 1's :data:`__version__`, and Phase 6's
provider constants. Detection (D-53) is delegated to the pure
:func:`zai_codex_helper.services.status.detect_provider` helper. The other
four commands (setup/doctor/install-service/uninstall-service) remain stubs.

Phase 12 (D-76..D-82, SETUP-01/02/03, SECR-01/03): ``setup`` is the onboarding
capstone — the FOURTH real (non-stub) subcommand. It delegates to
:func:`zai_codex_helper.services.setup.run_setup`, the services-layer
orchestrator that composes every prior phase (Paths, backup, TomlBackend,
YamlBackend@0600, ShellBackend, build_moonbridge, the provider pipeline)
into one interactive + scriptable + idempotent end-to-end flow. The handler
is a thin shell: it resolves ``Paths.default()`` and forwards
``args.yes or args.no_input`` (D-79 — both flags map to headless mode) +
``args.dry_run``. All step logic lives in the orchestrator (D-81). A new
``--no-input`` root flag mirrors ``--yes`` for non-interactive automation.
install-service / uninstall-service / doctor REMAINED stubs until their phases.

Phase 14 (D-89..D-94, DIAG-01..04): ``doctor`` is the SEVENTH real (non-stub)
subcommand — the LAST Phase 1 stub to become real. It delegates to
:func:`zai_codex_helper.services.doctor.run_doctor`, the READ-ONLY 9-check
diagnostic pipeline. The Phase 1 stub set is now EMPTY: all of
use/restore/status/setup/install-service/uninstall-service/doctor are real.
The ``_stub`` helper is retained (tests may reference it) but the stub
registration loop is gone.
"""

import argparse
import sys
from types import SimpleNamespace


def _stub(name: str):
    """Return a stub handler that prints ``not implemented`` to stderr.

    Stubs return 0 so smoke ``--help`` stays exit 0 and an accidental stub
    invocation does no harm; the contract does not mandate a non-zero stub
    exit (RESEARCH Open Question 1 — resolved: exit 0 + stderr message).
    """

    def handler(args: argparse.Namespace) -> int:
        print(f"{name}: not implemented in this phase", file=sys.stderr)
        return 0

    return handler


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


def _apply_provider_pipeline(transform, warn_stream, *, dry_run: bool = False) -> None:
    """Run the D-45 end-to-end write pipeline against the REAL ``config.toml``.

    This is the single write path both ``use`` handlers delegate to (D-45 —
    the load-bearing pipeline order the project's Core Value depends on). It
    glues Phase 5 (:class:`TomlBackend`), Phase 4
    (:meth:`BackupCoordinator.backup_once` via the ABC), Phase 6 (the pure
    ``transform`` + :func:`check_postconditions`), Phase 3
    (:func:`atomic_write` via ``write_canonical``), and Phase 2
    (:meth:`Paths.default`) into one crash-safe, idempotent, reversible write.

    Pipeline order (D-45 — each step's placement is load-bearing):

      a. ``paths = Paths.default()`` (D-46 — the production entry point; the
         autouse ``_isolate_home`` test fixture repoints ``HOME`` at the
         sandbox, so ``Path.home()`` resolves under ``tmp_path`` in tests).
      b. ``backend = TomlBackend(paths)``.
      c. SEED-IF-MISSING (D-45 step 3): if the config does NOT exist, write a
         fresh empty ``tomlkit.document()``. This MUST run BEFORE
         ``backup_once`` because :meth:`BackupCoordinator.backup_once` RAISES
         ``ZaiCodexHelperError("no config to back up")` when the source is
         absent (``backends/_backup.py`` ~line 112) — without this seed,
         ``use zai`` on a fresh install errors out instead of creating the
         config. The transform then populates the empty doc.
      d. ``backend.backup_once()`` (D-45 step 2 — the one-shot ``.bak`` via
         the sentinel-gated coordinator; no-op after the first run, safe to
         call every time).
      e. ``doc = backend.read()`` (D-45 step 4).
      f. ``doc = transform(doc)`` (D-45 step 5 — ``apply_zai`` or
         ``apply_openai``; pure).
      g. ``backend.write_canonical(doc)`` (D-45 step 6 — atomic, crash-safe).
      h. ``check_postconditions(doc)`` (D-45 step 7 — raises
         :class:`ZaiCodexHelperError` on violation; run AFTER write so it
         validates the post-write state; the transform is pure and
         ``write_canonical`` is faithful, so the in-memory doc equals the
         on-disk doc).
      i. ``_emit_restart_warning(warn_stream)`` (D-45 step 8, D-47).

    The helper does NOT catch :class:`ZaiCodexHelperError` (D-11/D-45 — the
    D-11 formatting is owned by :func:`zai_codex_helper.__main__.main`) and
    does NOT call ``sys.exit``. A postcondition violation propagates as
    :class:`ZaiCodexHelperError` to :func:`main`, which formats it one-line on
    stderr + exit 1 (and re-raises under ``--debug``).

    Phase 15 dry-run branch (CONF-07, D-95): when ``dry_run`` is True the
    pipeline runs steps a-f (paths, backend, seed-if-missing, backup_once is
    STILL a write so it is SKIPPED, read, transform) but STOPS before step g
    ``write_canonical``. It serializes the transformed doc via
    ``tomlkit.dumps(doc)``, computes a real unified diff against the current
    ``config.toml`` via :func:`zai_codex_helper.services.diff_preview.compute_diff`,
    prints it to ``warn_stream``, and returns WITHOUT writing — steps g
    (write), h (postcondition check — no write to validate against), and i
    (restart warning — no real write happened) are all skipped. The
    backup_once is skipped because it is itself a mutating call (a one-shot
    ``.bak`` write); the dry-run prints "would back up config.toml" instead.

    Args:
        transform: A pure transform callable (``apply_zai`` or
            ``apply_openai``) taking a ``tomlkit.TOMLDocument`` and returning
            the same mutated object.
        warn_stream: The stream the restart warning is written to (the caller
            passes ``sys.stderr`` — D-47). Under ``dry_run`` the diff preview
            is also routed here so a piped stdout is not polluted.
        dry_run: Phase 15 (D-95). When True, preview the would-be
            ``config.toml`` change as a unified diff and write NOTHING.
    """
    # Lazy imports keep `parser.py` import-light and side-effect-free at
    # module load (mirrors `_handle_restore`'s lazy-import discipline).
    import tomlkit

    from zai_codex_helper.backends.toml import TomlBackend
    from zai_codex_helper.services.diff_preview import compute_diff
    from zai_codex_helper.services.paths import Paths
    from zai_codex_helper.services.providers import check_postconditions

    # a. Resolve paths via the production entry point (D-46). In tests the
    #    autouse `_isolate_home` fixture repoints HOME at tmp_path, so
    #    Paths.default() resolves under the sandbox — no real-HOME write.
    paths = Paths.default()
    # b. Concrete TOML backend (Phase 5) bound to paths.config_toml.
    backend = TomlBackend(paths)

    # c. SEED-IF-MISSING (D-45 step 3) — MUST precede backup_once. The
    #    coordinator raises "no config to back up" when the source is absent,
    #    so without this branch `use zai` on a fresh install errors out
    #    instead of creating the config. An empty tomlkit document is the
    #    minimal seed; the transform (step f) populates it.
    if not backend.exists():
        backend.write_canonical(tomlkit.document())

    # d. One-shot .bak (D-45 step 2). Sentinel-gated: no-op after the first
    #    run, so calling it every time is safe and idempotent. DRY-RUN: this
    #    is itself a mutating call (a one-shot .bak write), so SKIP it under
    #    dry_run and surface the would-do intent instead (CONF-07 — the dry-run
    #    must not mutate ANY file, including the backup).
    if dry_run:
        print("would back up config.toml (one-shot .bak)", file=warn_stream)
    else:
        backend.backup_once()

    # e. Read the (now-existing) config into a live, style-preserving doc.
    doc = backend.read()
    # f. Apply the pure desired-state transform (apply_zai / apply_openai).
    doc = transform(doc)

    # D-95 dry-run branch: compute the would-be config.toml diff and print it,
    # then STOP — no write, no postcondition check (nothing to validate
    # against), no restart warning (no real write happened). The serialized
    # target MUST match what write_canonical would produce byte-for-byte so
    # the preview is faithful; tomlkit.dumps(doc) is exactly that.
    if dry_run:
        target_text = tomlkit.dumps(doc)
        diff = compute_diff(paths.config_toml, target_text)
        print(diff, file=warn_stream)
        return

    # g. Atomic, crash-safe write (Phase 3 via Phase 5).
    backend.write_canonical(doc)
    # h. Post-condition check (Phase 6). Run AFTER the write so it validates
    #    the post-write state. Raises ZaiCodexHelperError on violation; let
    #    it propagate to main() per D-11 — do NOT catch here.
    check_postconditions(doc)
    # i. Hard-to-miss restart warning (D-47, PROV-04).
    _emit_restart_warning(warn_stream)


def _handle_use_zai(args: argparse.Namespace) -> int:
    """Make Z.ai (``glm-5.2``, ``xhigh``) the Codex default (D-45, PROV-01).

    Phase 7 — the Core Value. This is the command the project exists to
    deliver: ``zai-codex-helper use zai`` writes the canonical Z.ai desired
    state to the real ``~/.codex/config.toml`` end-to-end. Replaces the Phase
    1 ``_stub("use zai")`` wiring (D-03).

    Follows the D-31 restore-handler shape verbatim: lazy imports inside the
    body, resolve ``Paths.default()``, delegate to the shared
    :func:`_apply_provider_pipeline`, return 0. Does NOT catch
    :class:`ZaiCodexHelperError` (D-11 — owned by :func:`main`), does NOT call
    ``sys.exit``.

    Args:
        args: The parsed argparse namespace (unused beyond dispatch).

    Returns:
        0 on success (the pipeline raises on failure; success means the
        config was written, post-conditions passed, and the restart warning
        was emitted).
    """
    # Lazy import of the transform (mirrors `_handle_restore`'s discipline so
    # parser.py stays import-light at module load).
    from zai_codex_helper.services.providers import apply_zai

    # Phase 15 (D-95): forward the root --dry-run flag so `use zai --dry-run`
    # previews the would-be config.toml change as a diff and writes nothing.
    _apply_provider_pipeline(apply_zai, sys.stderr, dry_run=args.dry_run)
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
    ``Paths.default()``, delegate to :func:`_apply_provider_pipeline`, return
    0. Does NOT catch :class:`ZaiCodexHelperError`, does NOT call
    ``sys.exit``.

    Args:
        args: The parsed argparse namespace (unused beyond dispatch).

    Returns:
        0 on success.
    """
    from zai_codex_helper.services.providers import apply_openai

    # Phase 15 (D-95): forward the root --dry-run flag so `use openai --dry-run`
    # previews the would-be config.toml change as a diff and writes nothing.
    _apply_provider_pipeline(apply_openai, sys.stderr, dry_run=args.dry_run)
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

    Note on the backend: ``BackupCoordinator.restore`` only reads
    ``backend.path`` (the live file to restore into). ``TomlBackend`` (the
    real concrete backend) lands in Phase 5, so a path-only
    :class:`types.SimpleNamespace` satisfies the coordinator's contract
    today. This is a Phase-4 expedient — replaced by ``TomlBackend`` in
    Phase 5.
    """
    # Lazy imports keep `parser.py` import-light and side-effect-free at
    # module load (avoids walking _backup -> __main__ -> parser on import).
    from zai_codex_helper.backends._backup import BackupCoordinator
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    # Phase-4 expedient: path-only backend. BackupCoordinator.restore reads
    # only backend.path; replaced by TomlBackend in Phase 5.
    backend = SimpleNamespace(path=paths.config_toml)
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
    return install_service(paths, dry_run=args.dry_run)


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
    return uninstall_service(paths)


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

    D-79 mapping: ``args.yes or args.no_input`` both force headless mode
    (every ``confirm()`` returns True; provider defaults to zai; ZAI_API_KEY
    env becomes REQUIRED). The ``--no-input`` flag is added in
    :func:`build_parser` alongside ``--yes``.

    Args:
        args: The parsed argparse namespace. Reads ``args.yes``,
            ``args.no_input``, and ``args.dry_run``.

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
        yes=args.yes or args.no_input,
        dry_run=args.dry_run,
    )


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
    from zai_codex_helper.services.doctor import run_doctor
    from zai_codex_helper.services.paths import Paths

    paths = Paths.default()
    return run_doctor(paths)


def build_parser() -> argparse.ArgumentParser:
    """Build the root ``zai-codex-helper`` argparse parser.

    The root parser owns the global flags (``--debug`` / ``--yes`` /
    ``--dry-run``) and the subcommand dispatch table. Subparsers use
    ``dest="cmd", required=True`` so invoking the CLI with no subcommand
    produces argparse's clean error + exit 2 instead of an
    ``AttributeError`` on ``args.func`` (RESEARCH Pitfall 4).
    """
    parser = argparse.ArgumentParser(
        prog="zai-codex-helper",
        description="Manage the Codex ⇄ Moon Bridge ⇄ Z.ai link.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="show full traceback on error",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="answer yes to all prompts (non-interactive)",
    )
    parser.add_argument(
        "--no-input",
        action="store_true",
        help="non-interactive: no prompts, env vars required",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview changes without writing",
    )

    subparsers = parser.add_subparsers(
        dest="cmd",
        required=True,
        metavar="<command>",
    )

    # `use` — nested provider sub-subs (D-03). Phase 7 swaps _stub for real handlers.
    p_use = subparsers.add_parser(
        "use",
        help="switch the default Codex provider",
    )
    use_sub = p_use.add_subparsers(
        dest="provider",
        required=True,
        metavar="<provider>",
    )
    use_sub.add_parser(
        "zai",
        help="make Z.ai (glm-5.2 xhigh) the default",
    ).set_defaults(func=_handle_use_zai)
    use_sub.add_parser(
        "openai",
        help="revert to OpenAI",
    ).set_defaults(func=_handle_use_openai)

    # `restore` — the FIRST real (non-stub) subcommand (Phase 4, D-31).
    # SC-2: "a `restore` command rolls the user's config back to the last
    # one-time backup". Autonomous (no prompt in Phase 4). The handler lets
    # ZaiCodexHelperError propagate so main() owns the D-11 formatting.
    p_restore = subparsers.add_parser(
        "restore",
        help="restore config from the one-time backup",
    )
    p_restore.set_defaults(func=_handle_restore)

    # `status` — the read-only observability command (Phase 8, D-50..D-55).
    # Prints the current provider, config paths, and version. READ-ONLY (D-51).
    p_status = subparsers.add_parser(
        "status",
        help="show current provider, config paths, and version",
    )
    p_status.set_defaults(func=_handle_status)

    # `setup` — the FOURTH real (non-stub) subcommand (Phase 12, D-76..D-82).
    # The onboarding capstone: delegates to services.setup.run_setup (the
    # services-layer orchestrator). install-service / uninstall-service are
    # the FIFTH/SIXTH real subcommands (Phase 13 below); doctor is the SEVENTH
    # (Phase 14 below).
    p_setup = subparsers.add_parser(
        "setup",
        help="guided end-to-end onboarding",
    )
    p_setup.set_defaults(func=_handle_setup)

    # `install-service` / `uninstall-service` — the FIFTH/SIXTH real (non-stub)
    # subcommands (Phase 13, D-83..D-88; SERV-01..04). The LaunchAgent lifecycle
    # pair: install writes the plist + bootstraps the agent (+ verifies loaded +
    # listening); uninstall bootouts the agent + removes the plist. Both share
    # ONE Label constant imported from PlistBackend (D-85 — no orphan). The
    # handlers are thin shells (lazy imports, Paths.default(), delegate); the
    # runner seam is NOT forwarded (production uses the real launchctl).
    p_install = subparsers.add_parser(
        "install-service",
        help="install the Moon Bridge LaunchAgent",
    )
    p_install.set_defaults(func=_handle_install_service)
    p_uninstall = subparsers.add_parser(
        "uninstall-service",
        help="uninstall the Moon Bridge LaunchAgent",
    )
    p_uninstall.set_defaults(func=_handle_uninstall_service)

    # `doctor` — the SEVENTH real (non-stub) subcommand (Phase 14,
    # D-89..D-94; DIAG-01..04). The LAST Phase 1 stub to become real: the
    # Phase 1 stub set is now EMPTY. READ-ONLY 9-check diagnostic; the handler
    # is a thin shell (lazy imports, Paths.default(), delegate); the
    # runner/http_client/environ seams are NOT forwarded (production uses the
    # real subprocess.run + an internally-constructed httpx.Client).
    p_doctor = subparsers.add_parser(
        "doctor",
        help="diagnose the Codex ⇄ Moon Bridge ⇄ Z.ai chain",
    )
    p_doctor.set_defaults(func=_handle_doctor)

    return parser
