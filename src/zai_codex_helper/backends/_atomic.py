"""Crash-safe file-write boundary behind the ``backends/`` IO layer (D-09).

A single primitive, :func:`atomic_write`, performs every disk mutation the
tool will ever make. The atomicity recipe is temp-in-same-dir + ``os.fsync`` +
``os.replace`` (CONF-01): a write goes to a temp file created as a *sibling*
of the destination, the temp is fsync-ed, then ``os.replace`` renames it
atomically over the destination (atomic on POSIX/macOS). An interrupted write
— crash, power loss, Ctrl-C, exception — therefore never leaves a half-written
config at the destination and never orphans a temp file (T-03-01, T-03-05).

Mode contract:

- ``mode=None`` → do NOT chmod; the destination keeps the tempfile's umask-governed
  mode or, on overwrite, the pre-existing destination's mode (the ``config.toml``
  branch — CLAUDE.md "preserve existing mode").
- ``mode=0o600`` → ``os.chmod(path, 0o600)`` AFTER the successful replace (the
  secrets branch — CLAUDE.md File Permissions table; the single mechanism by
  which ``moonbridge-zai.yml`` lands restricted).

The helper never prints or logs ``data``: API keys pass through it unchanged in
Phase 9+ (T-03-03). Phase 4's ``ConfigBackend.write_canonical`` will delegate
here without rework.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = ["atomic_write"]


def atomic_write(path: str | Path, data: bytes | str, mode: int | None = None) -> None:
    """Write ``data`` to ``path`` crash-safely (CONF-01, D-26).

    Sequence (order is load-bearing):

    1. Coerce ``path`` to ``pathlib.Path`` (accepts ``str | Path``).
    2. ``path.parent.mkdir(parents=True, exist_ok=True)`` — the one non-atomic
       allowance, run BEFORE temp creation so the temp lands in the right dir.
    3. ``tempfile.NamedTemporaryFile(dir=str(path.parent), delete=False)`` —
       temp is a *sibling* of the destination so ``os.replace`` is a
       same-filesystem rename (atomic on POSIX/macOS; T-03-06).
    4. Write ``data`` (``str`` encoded UTF-8), ``flush()``, ``os.fsync(fd)``
       (load-bearing durability call).
    5. Close the temp, then ``os.replace(temp, path)`` (atomic overwrite).
    6. If ``mode is not None``, ``os.chmod(path, mode)`` AFTER replace (chmod
       the destination, never the temp — a crash between replace and chmod
       leaves a correctly-replaced file with old perms, not a half-applied
       state). ``mode=None`` skips chmod entirely (preserve existing mode).

    On ANY exception after temp creation: ``os.unlink(temp)`` cleanup then
    re-raise — the destination is never visible in a partial state and no
    orphaned temp survives (T-03-01, T-03-05). The original exception is never
    swallowed.

    Args:
        path: Destination file (``str | Path``); parents are created if absent.
        data: Payload (``bytes`` written verbatim, ``str`` encoded UTF-8).
        mode: ``None`` to preserve existing/umask mode (``config.toml``), or an
            integer mode (e.g. ``0o600`` for secrets) applied via
            ``os.chmod`` AFTER replace.

    Returns:
        None — the observable side effect is the written file at ``path``.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    payload = data.encode("utf-8") if isinstance(data, str) else data

    # Create the temp as a SIBLING of the destination so os.replace is a
    # same-filesystem atomic rename (T-03-06).
    tmp = tempfile.NamedTemporaryFile(dir=str(dest.parent), delete=False)
    tmp_name = tmp.name
    try:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())  # load-bearing durability call (T-03-01)
    finally:
        # Close before replace (portable: Windows cannot replace an open file;
        # POSIX tolerates it but closing first is cleaner and symmetric).
        tmp.close()

    try:
        os.replace(tmp_name, str(dest))  # atomic overwrite on POSIX/macOS
    except BaseException:
        # replace failed → unlink the temp so no orphan survives (T-03-05),
        # and the destination is untouched (old file is the only visible state).
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

    if mode is not None:
        # chmod the DESTINATION after a successful replace — never the temp.
        # A crash between replace and chmod leaves a correctly-replaced file
        # with the old perms, not a half-applied state.
        os.chmod(str(dest), mode)
