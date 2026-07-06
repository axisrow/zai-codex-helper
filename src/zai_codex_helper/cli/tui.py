"""Minimal arrow-key TUI for ``zai-codex-helper`` (``zai-codex-helper tui``).

A single-screen, no-color, stdlib-only menu over the existing LaunchAgent +
doctor service functions. Navigation: ``↑``/``k`` up, ``↓``/``j`` down,
``Enter`` select, ``Esc``/``q`` quit. The screen is cleared and redrawn each
keystroke via an ANSI clear-screen escape (the only "special effect" — no
color, no cursor positioning, no curses).

Raw single-key input (no line buffering) is the one non-trivial bit: it uses
``tty.setcbreak`` + ``termios`` wrapped in ``try/finally`` so the terminal
mode is ALWAYS restored — even on error or interrupt. Without that restore
the user is left in a broken (cbreak) shell.

This module adds no domain logic — it dispatches to the existing service
functions: ``install_macro`` / ``uninstall_macro`` (the Install/Uninstall
macros), ``apply_provider`` (the Z.ai toggle), ``set_key``, and ``run_doctor``.
Those can write config.toml / moonbridge-zai.yml / models_cache.json / .zshrc
and change service state — the TUI is a thin front-end over them, not read-only.
It catches :class:`ZaiCodexHelperError` so a failed action returns to the menu
instead of crashing the TUI (the D-11 one-line ``error: <msg>`` contract is
honored here because the TUI owns its own event loop — unlike the thin CLI
handlers, it cannot let the error propagate to ``main``).
"""

import argparse
import select
import sys
import termios
import tty

from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.aliases import apply_aliases, remove_aliases
from zai_codex_helper.services.paths import Paths

#: The fixed menu skeleton (top to bottom). Each entry is (key, kind) where
#: kind drives how its label is rendered (toggle = appends On/Off from live
#: state) and whether it can be disabled. Install is FIRST, Uninstall is
#: LAST-but-one (Quit last) per the UX spec.
_MENU: tuple[tuple[str, str], ...] = (
    ("Install", "macro-install"),
    ("Z.ai", "toggle-zai"),
    ("Set Key", "action-setkey"),
    ("Aliases", "menu-aliases"),
    ("Doctor", "action-doctor"),
    ("Uninstall", "macro-uninstall"),
    ("Quit", "action-quit"),
)

#: ANSI clear-screen + cursor-home. The single allowed escape: it clears the
#: screen so the redrawn menu replaces the old frame in place. Not color, not
#: a highlight — just a wipe.
_CLEAR = "\033[2J\033[H"


def _read_key() -> str:
    """Read one keystroke without line buffering (caller holds cbreak mode).

    Returns a symbolic name: ``"UP"`` / ``"DOWN"`` for arrow keys, ``"ESC"``
    for a bare Escape, otherwise the literal character (e.g. ``"\r"`` for
    Enter, ``"q"``). cbreak is toggled once per SESSION in :func:`run` (not
    per-read) — two fewer syscalls per keystroke.
    """
    ch = sys.stdin.read(1)
    if ch == "\x1b":  # ESC — either bare Escape or a CSI arrow sequence.
        seq = sys.stdin.read(2)
        return {"[A": "UP", "[B": "DOWN"}.get(seq, "ESC")
    return ch


def _esc_pressed() -> bool:
    """Non-blocking Esc poll (cbreak session must be active).

    Used by the doctor POST spinner's abort callback: ``select`` on stdin with
    a zero timeout, and if a byte is ready AND it's ESC (``\\x1b``), consume it
    and return True. Returns False when nothing is pending (the common case —
    the spinner ticks ~10×/s and stdin is idle).
    """
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if not ready:
        return False
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        # Drain the optional 2-byte CSI tail of an arrow key so it's not
        # misread as the next nav keystroke.
        _tail, _, _ = select.select([sys.stdin], [], [], 0)
        if _tail:
            sys.stdin.read(2)
        return True
    return False


def _pause() -> None:
    """Block until any key so the user can read an action's output before redraw.

    Reads ONE key via :func:`_read_key` (NOT builtin ``input()``) — the TUI
    holds the terminal in cbreak for the whole session, and ``input()`` cannot
    work in cbreak (chars arrive one-at-a-time without ``\\n``, so ``input()``
    would block forever). ``_read_key`` reads a single cbreak keystroke, which
    is exactly "press any key". Without this pause the redraw ``_CLEAR`` would
    wipe Doctor's output before the user sees it.
    """
    print("\n[press any key]")
    # _read_key uses sys.stdin.read(1), which returns "" at EOF (never raises
    # EOFError), so a closed stdin just falls through and returns — no guard
    # needed.
    _read_key()


def _state(paths) -> tuple[bool, bool, str]:
    """Read the live installation state for labels + macro-disable logic.

    Returns ``(is_zai, mb_loaded, provider_label)``. ``is_zai`` from
    :func:`detect_provider`; ``mb_loaded`` from :func:`verify_service_loaded`
    (launchctl half only — the port is doctor's concern). Both are read-only.
    Any read error degrades gracefully (treated as off) so a broken state
    never crashes the TUI.
    """
    from zai_codex_helper.backends.toml import TomlBackend
    from zai_codex_helper.services.lifecycle import verify_service_loaded
    from zai_codex_helper.services.status import detect_provider, read_for_status

    try:
        doc = read_for_status(TomlBackend(paths))
        desc = detect_provider(doc)
        is_zai = desc.is_zai
        label = desc.provider_label
    except Exception:  # noqa: BLE001 — TUI must not crash on a broken config.
        is_zai, label = False, "(config unreadable)"
    try:
        mb_loaded = verify_service_loaded(paths)[0]
    except Exception:  # noqa: BLE001 — launchctl errors → assume not loaded.
        mb_loaded = False
    return is_zai, mb_loaded, label


def _render_label(base_label: str, kind: str, state: tuple[bool, bool, str]) -> str:
    """Render a menu label: the static base, with On/Off appended for toggles.

    The base label comes straight from :data:`_MENU` (single source — no second
    kind→label dict). Only the Z.ai toggle mutates it (appends live On/Off).
    """
    if kind == "toggle-zai":
        is_zai = state[0]
        return f"{base_label}: {'On' if is_zai else 'Off'}"
    return base_label


def _is_disabled(kind: str, state: tuple[bool, bool, str]) -> bool:
    """Install disabled when already fully on; Uninstall when fully off."""
    is_zai, mb_loaded, _ = state
    if kind == "macro-install":
        return is_zai and mb_loaded
    if kind == "macro-uninstall":
        return not is_zai and not mb_loaded
    return False


#: The Aliases submenu items: (label, alias-name). ``None`` alias-name = Back.
#: Labels are bare names (no "Install" verb) — the verb lives in the contextual
#: footer hint (Enter to install / Enter to uninstall). zai is a fence alias;
#: glm is a generated script — both flow through the same
#: apply_aliases/remove_aliases service functions (glm routes internally).
_ALIASES_SUBMENU: tuple[tuple[str, str | None], ...] = (
    ("zai", "zai"),
    ("glm", "glm"),
    ("Back", None),
)


def _aliases_submenu(paths, args: argparse.Namespace) -> None:
    """Arrow-key submenu for the opt-in aliases (zai, glm). Returns to main menu.

    Three items: zai, glm, Back. Each alias shows live state — ``[installed]``
    or ``[not installed]`` (strict: glm is "ours" iff the script carries the
    helper marker; a foreign ~/.local/bin/glm is "not installed"). The footer
    hint is contextual on the selected item: ``Enter to install`` when not
    installed, ``Enter to uninstall`` when installed, ``Enter to go back`` on
    Back.
    Selecting an alias TOGGLES it (install via :func:`apply_aliases` if absent,
    remove via :func:`remove_aliases` if present — both route ``glm`` to the
    script service). Esc / Back returns to the main menu. cbreak is already
    active (the main loop holds it for the whole session), so
    :func:`_read_key` works here too.

    Presence is computed once per redraw (a snapshot over both aliases) rather
    than per row + per footer hint — each check reads the fence / parses the
    yml, and the loop redraws on every keystroke.

    ``ZaiCodexHelperError`` (e.g. ``glm`` without the yml/key) is caught and
    printed — the submenu stays up, mirroring how the main loop handles its
    own action errors.
    """
    from zai_codex_helper.services.aliases import is_alias_installed

    dry = getattr(args, "dry_run", False)
    sel = 0
    while True:
        # Snapshot each alias's installed-state once per redraw (each check is
        # a fence read / yml parse — don't repeat per row + per footer hint).
        installed = {
            name: is_alias_installed(paths, name)
            for _, name in _ALIASES_SUBMENU
            if name is not None
        }
        print(_CLEAR, end="")
        print("zai-codex-helper   Aliases\n")
        for i, (label, name) in enumerate(_ALIASES_SUBMENU):
            if name is None:
                rendered = label
            else:
                state = "installed" if installed[name] else "not installed"
                rendered = f"{label}  [{state}]"
            marker = ">" if i == sel else " "
            print(f"  {marker} {rendered}")
        # Contextual footer hint on the selected row.
        _, sel_name = _ALIASES_SUBMENU[sel]
        if sel_name is None:
            action = "go back"
        elif installed[sel_name]:
            action = "uninstall"
        else:
            action = "install"
        print(f"\n  ↑↓ move   Enter to {action}   Esc back")

        key = _read_key()
        if key in ("UP", "k"):
            sel = (sel - 1) % len(_ALIASES_SUBMENU)
        elif key in ("DOWN", "j"):
            sel = (sel + 1) % len(_ALIASES_SUBMENU)
        elif key in ("\r", "\n"):
            _, name = _ALIASES_SUBMENU[sel]
            if name is None:
                return  # Back
            try:
                if installed[name]:
                    remove_aliases(paths, names=[name], dry_run=dry)
                else:
                    apply_aliases(paths, names=[name], dry_run=dry)
            except ZaiCodexHelperError as e:
                # Pause only on the error path — the redraw _CLEAR would wipe
                # the message. A successful toggle prints nothing, so it
                # redraws at once (no "press any key" stall).
                print(f"error: {e}", file=sys.stderr)
                _pause()
        elif key in ("ESC", "q"):
            return


def _dispatch(
    kind: str, paths, args: argparse.Namespace, state: tuple[bool, bool, str]
) -> bool:
    """Run the selected menu item. Returns True iff the TUI should quit.

    ``state`` is the loop's already-computed ``_state(paths)`` tuple — passed in
    so ``toggle-zai`` reuses the cached ``is_zai`` instead of a second
    ``_state`` call (which shells out to a slow ``launchctl print``).

    Lazy imports keep ``tui.py`` import-light and side-effect-free at module
    load (mirrors the lazy-import discipline in ``cli/parser.py`` handlers).
    """
    from zai_codex_helper.services.doctor import run_doctor
    from zai_codex_helper.services.providers import apply_openai, apply_zai

    dry = getattr(args, "dry_run", False)
    if kind == "action-quit":
        return True
    if kind == "menu-aliases":
        _aliases_submenu(paths, args)
        return False
    if kind == "macro-install":
        import os

        from zai_codex_helper.services.install import install_macro

        # Headless install requires ZAI_API_KEY. In the (interactive) TUI, if the
        # env var is unset, collect it here rather than hard-erroring like an
        # automation path (#11) — the same hidden getpass under cbreak that the
        # Set Key item already uses. Dry-run is a preview: never prompt for a
        # secret just to show a diff. The key goes into a scoped environ mapping
        # (not the global os.environ) so it can't leak into build/launchctl.
        environ = None
        if not dry and not os.environ.get("ZAI_API_KEY"):
            import getpass

            from zai_codex_helper.services.setup import _prompt_api_key

            environ = {"ZAI_API_KEY": _prompt_api_key(getpass.getpass)}
        install_macro(paths, dry_run=dry, headless=True, environ=environ)
    elif kind == "macro-uninstall":
        from zai_codex_helper.services.install import uninstall_macro

        uninstall_macro(paths, dry_run=dry)
    elif kind == "toggle-zai":
        # Flip the config provider: zai→openai or openai→zai. Reuse the loop's
        # cached is_zai (no second launchctl-backed _state call).
        from zai_codex_helper.cli.parser import _render_apply_result
        from zai_codex_helper.services.provider_apply import apply_provider

        is_zai = state[0]
        result = apply_provider(
            paths, apply_openai if is_zai else apply_zai, dry_run=dry
        )
        _render_apply_result(result, sys.stderr)
    elif kind == "action-setkey":
        from zai_codex_helper.services.api_key import set_key

        set_key(paths, dry_run=dry)
    elif kind == "action-doctor":
        from zai_codex_helper.services.doctor import run_with_spinner

        # The POST probe is slow (3–20s upstream); run it in a background
        # thread with a spinner, abortable via Esc (cbreak is active in TUI).
        run_doctor(
            paths,
            post_check_runner=lambda call: run_with_spinner(
                call, should_abort=_esc_pressed
            ),
        )
    return False


def run(args: argparse.Namespace) -> int:
    """Run the TUI event loop. Returns 0 on clean exit.

    Refuses to run when stdin is not a TTY (piped / redirected) — cbreak mode
    on a non-terminal fd would misbehave, so we surface an actionable error
    instead of degrading silently. cbreak is entered ONCE for the whole
    session and restored in ``finally`` so a broken shell is never left behind.
    """
    if not sys.stdin.isatty():
        print("error: tui requires a terminal", file=sys.stderr)
        return 1

    paths = Paths.default()
    sel = 0
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        # Cache the live state; recompute ONLY after an action that may change
        # it (dispatch). Recomputing on every ↑↓ keystroke made the TUI lag —
        # _state shells out to `launchctl print` (a slow launchd IPC), so the
        # menu redraw stalled ~0.2-0.5s per navigation key.
        state = _state(paths)
        while True:
            print(_CLEAR, end="")
            prov = state[2]
            print(f"zai-codex-helper   Provider: {prov}\n")
            for i, (base_label, kind) in enumerate(_MENU):
                label = _render_label(base_label, kind, state)
                disabled = _is_disabled(kind, state)
                marker = ">" if i == sel else " "
                tag = "  (already done)" if disabled and i == sel else ""
                print(f"  {marker} {label}{tag}")
            print("\n  ↑↓ move   Enter select   Esc quit")

            key = _read_key()
            if key in ("UP", "k"):
                sel = (sel - 1) % len(_MENU)
            elif key in ("DOWN", "j"):
                sel = (sel + 1) % len(_MENU)
            elif key in ("\r", "\n"):
                kind = _MENU[sel][1]
                if _is_disabled(kind, state):
                    print("  (already in this state — nothing to do)")
                    _pause()
                    continue
                try:
                    if _dispatch(kind, paths, args, state):
                        return 0  # Quit — exit without pausing.
                except ZaiCodexHelperError as e:
                    # D-11 contract honored in-loop: the TUI owns its event
                    # loop, so it formats the error and returns to the menu
                    # rather than propagating to __main__.main (which would
                    # exit the process).
                    print(f"error: {e}", file=sys.stderr)
                # Refresh the cached state ONLY for actions that change the
                # installation state (install/uninstall/toggle). set-key/doctor
                # don't, so skip the launchctl+config re-read for them.
                if kind in ("macro-install", "macro-uninstall", "toggle-zai"):
                    state = _state(paths)
                # Pause only for actions that print output the redraw would wipe
                # (install/uninstall/toggle/set-key/doctor). menu-aliases manages
                # its own pause internally and prints nothing on return — no
                # "press any key" stall on Back.
                if kind != "menu-aliases":
                    _pause()
            elif key in ("ESC", "q"):
                return 0
    except KeyboardInterrupt:
        # Ctrl+C during _read_key — a clean quit, not a crash. The `finally`
        # below still restores termios so the shell isn't left in cbreak.
        return 0
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":  # pragma: no cover — manual smoke entry
    raise SystemExit(run(argparse.Namespace(dry_run=False)))
