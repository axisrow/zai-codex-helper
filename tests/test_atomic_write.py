"""Pin ROADMAP Phase 3 SC-1 and SC-2 for the crash-safe ``atomic_write`` helper.

SC-1 (atomic, never partial): a write via temp + fsync + ``os.replace`` leaves
the destination byte-exact, and a forced exception between temp-create and
replace leaves NO partial destination, NO orphaned temp, and a pre-existing
destination byte-for-byte preserved. The temp is a sibling of the destination
(same-filesystem atomic rename), and ``os.fsync`` is called strictly before
``os.replace``.

SC-2 (mode param): ``mode=None`` does NOT call ``os.chmod`` (the preserve /
``config.toml`` branch); ``mode=0o600`` produces a destination whose
``stat.S_IMODE`` is exactly ``0o600``; overwriting an existing ``0o600`` file
with ``mode=None`` preserves ``0o600``.

Cross-cutting: the helper never emits ``data`` via print/stdout/stderr
(secrets discipline — API keys pass through it in Phase 9+), and it creates
missing parent directories.

All dests live under ``tmp_path`` (the autouse ``_isolate_home`` fixture
already redirects ``HOME`` to a tmp sandbox — CONTEXT D-14). The style mirrors
``tests/test_paths.py``: ``from __future__ import annotations``,
``@pytest.mark.unit``, one focused assertion per test where practical.
"""

from __future__ import annotations

import builtins
import os
import stat
import sys

import pytest

import zai_codex_helper.backends._atomic as atomic_mod
from zai_codex_helper.backends._atomic import atomic_write


class _Boom(RuntimeError):
    """Sentinel exception so ``pytest.raises`` proves the helper re-raised."""


# --------------------------------------------------------------------------- #
# SC-1 — round-trip integrity
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_atomic_write_roundtrip_bytes(tmp_path):
    """SC-1: bytes written through atomic_write read back byte-equal."""
    dest = tmp_path / "cfg.toml"
    atomic_write(dest, b"hello")
    assert dest.read_bytes() == b"hello"


@pytest.mark.unit
def test_atomic_write_roundtrip_str(tmp_path):
    """SC-1: str payload is encoded UTF-8 on disk.

    ``str.encode()`` defaults to UTF-8 on our py310+ floor, so the assertion
    validates the same bytes the helper writes (``data.encode("utf-8")``).
    """
    dest = tmp_path / "cfg.toml"
    atomic_write(dest, "héllo")
    assert dest.read_bytes() == "héllo".encode()


# --------------------------------------------------------------------------- #
# SC-1 — atomicity on exception (no pre-existing destination)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_atomic_write_failure_leaves_no_partial_and_no_temp(tmp_path):
    """SC-1: a forced os.replace failure leaves no dest file and no temp.

    Patches ``os.replace`` in the helper's module namespace so the EXACT call
    the helper makes is intercepted. After the raise: destination does not
    exist, and the destination dir contains no leftover temp.
    """
    dest = tmp_path / "cfg.toml"

    def boom(*args, **kwargs):
        raise _Boom("forced replace failure")

    monkeypatch_os_replace(boom)
    try:
        with pytest.raises(_Boom):
            atomic_write(dest, b"payload")
    finally:
        restore_os_replace()

    assert not dest.exists(), "destination must not appear in a partial state"

    # The .codex subdir is pre-created by the autouse _isolate_home fixture;
    # inspect ONLY the dest's parent for leftover temps.
    leftovers = [p for p in os.listdir(tmp_path) if not p.startswith(".codex")]
    # dest itself did not pre-exist and must not appear; temps are unlinked.
    assert "cfg.toml" not in os.listdir(tmp_path), "partial dest leaked"
    assert leftovers == [], f"orphaned temp survived: {leftovers}"


# --------------------------------------------------------------------------- #
# SC-1 — atomicity on exception (pre-existing destination preserved)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_atomic_write_failure_preserves_pre_existing_destination(tmp_path):
    """SC-1: on a failed overwrite, the pre-existing destination is unchanged.

    os.replace is atomic — on failure the old destination is the only visible
    state, byte-for-byte.
    """
    dest = tmp_path / "cfg.toml"
    prior = b"ORIGINAL-CONFIG"
    dest.write_bytes(prior)

    def boom(*args, **kwargs):
        raise _Boom("forced replace failure")

    monkeypatch_os_replace(boom)
    try:
        with pytest.raises(_Boom):
            atomic_write(dest, b"NEW-BUT-SHOULD-NOT-LAND")
    finally:
        restore_os_replace()

    assert dest.read_bytes() == prior, "pre-existing destination was corrupted"


# --------------------------------------------------------------------------- #
# SC-1 — temp is a sibling of the destination (same-filesystem rename)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_atomic_write_temp_is_sibling_of_destination(tmp_path):
    """SC-1: the temp file's parent equals the destination's parent.

    Record every NamedTemporaryFile call's ``dir`` kwarg by patching the
    helper's module-level ``tempfile.NamedTemporaryFile``. Same-dir guarantee
    means os.replace is a same-filesystem atomic rename (T-03-06).
    """
    dest = tmp_path / "nested" / "cfg.toml"
    dest.parent.mkdir(parents=True, exist_ok=True)

    seen_dirs = []
    real_ntf = atomic_mod.tempfile.NamedTemporaryFile

    def recording_ntf(*args, **kwargs):
        seen_dirs.append(kwargs.get("dir"))
        return real_ntf(*args, **kwargs)

    atomic_mod.tempfile.NamedTemporaryFile = recording_ntf
    try:
        atomic_write(dest, b"x")
    finally:
        atomic_mod.tempfile.NamedTemporaryFile = real_ntf

    assert seen_dirs, "NamedTemporaryFile was not called"
    assert str(dest.parent) in seen_dirs, (
        f"temp dir must be the destination parent; got {seen_dirs}"
    )


# --------------------------------------------------------------------------- #
# SC-1 — fsync called strictly before os.replace (load-bearing order)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_atomic_write_fsync_before_replace_order(tmp_path):
    """SC-1: os.fsync runs strictly BEFORE os.replace (order is load-bearing).

    Recorders append to a shared list; assert the list is exactly
    ``["fsync", "replace"]``.
    """
    dest = tmp_path / "cfg.toml"
    order: list[str] = []

    real_fsync = atomic_mod.os.fsync
    real_replace = atomic_mod.os.replace

    def fsync_recorder(fd):
        order.append("fsync")
        return real_fsync(fd)

    def replace_recorder(src, dst):
        order.append("replace")
        return real_replace(src, dst)

    atomic_mod.os.fsync = fsync_recorder
    atomic_mod.os.replace = replace_recorder
    try:
        atomic_write(dest, b"x")
    finally:
        atomic_mod.os.fsync = real_fsync
        atomic_mod.os.replace = real_replace

    assert order == ["fsync", "replace"], (
        f"fsync must precede replace; observed order={order}"
    )


# --------------------------------------------------------------------------- #
# SC-2 — mode=None does NOT call os.chmod
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_atomic_write_mode_none_does_not_chmod(tmp_path):
    """SC-2: mode=None is the preserve branch — os.chmod is NOT invoked."""
    dest = tmp_path / "cfg.toml"
    chmod_calls: list[tuple] = []

    real_chmod = atomic_mod.os.chmod
    atomic_mod.os.chmod = lambda *a, **k: chmod_calls.append((a, k))
    try:
        atomic_write(dest, b"x", mode=None)
    finally:
        atomic_mod.os.chmod = real_chmod

    assert chmod_calls == [], f"mode=None must not chmod; saw calls={chmod_calls}"


# --------------------------------------------------------------------------- #
# SC-2 — mode=0o600 produces exactly 0600 on the destination
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_atomic_write_mode_0600_exact_permissions(tmp_path):
    """SC-2: mode=0o600 → stat.S_IMODE == 0o600 exactly (secrets branch)."""
    dest = tmp_path / "moonbridge-zai.yml"
    atomic_write(dest, b"api_key: secret", mode=0o600)
    got = stat.S_IMODE(os.stat(dest).st_mode)
    assert got == 0o600, f"expected 0o600, got {oct(got)}"


# --------------------------------------------------------------------------- #
# SC-2 — overwrite with mode=None preserves pre-existing 0600
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_atomic_write_overwrite_preserves_pre_existing_0600(tmp_path):
    """SC-2: rewriting a 0600 file with mode=None keeps it 0600.

    os.replace on POSIX preserves the existing destination's mode; combined
    with mode=None skipping chmod this is the 'preserve existing mode' contract
    for config.toml-overwrite.
    """
    dest = tmp_path / "cfg.toml"
    # first write creates a 0600 file
    atomic_write(dest, b"first", mode=0o600)
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600

    # second write with mode=None must NOT relax the 0600 perms
    atomic_write(dest, b"second", mode=None)
    assert dest.read_bytes() == b"second"
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600, (
        "mode=None overwrite must preserve pre-existing 0600 (os.replace keeps dest mode)"
    )


# --------------------------------------------------------------------------- #
# Secrets discipline — data never emitted via print/stdout/stderr
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_atomic_write_never_emits_data_via_stdio(tmp_path):
    """T-03-03: the helper never prints/writes data to stdout/stderr.

    Patches builtins.print, sys.stdout.write, sys.stderr.write; asserts none
    were called with any argument containing the secret. Also asserts the
    helper module does not import logging. The file itself DOES contain the
    secret (the discipline is about logging, not about the file).
    """
    secret = b"SECRETVALUE-d0-not-leak"
    dest = tmp_path / "moonbridge-zai.yml"

    print_calls: list[tuple] = []
    stdout_calls: list[tuple] = []
    stderr_calls: list[tuple] = []

    real_print = builtins.print
    real_stdout_write = sys.stdout.write
    real_stderr_write = sys.stderr.write

    def spy_print(*args, **kwargs):
        print_calls.append((args, kwargs))
        # do NOT actually emit
        return None

    def spy_stdout_write(s):
        stdout_calls.append((s,))
        return len(s)

    def spy_stderr_write(s):
        stderr_calls.append((s,))
        return len(s)

    monkeypatch_stdio(spy_print, spy_stdout_write, spy_stderr_write)
    try:
        atomic_write(dest, secret, mode=0o600)
    finally:
        restore_stdio(real_print, real_stdout_write, real_stderr_write)

    # the file itself must contain the secret (proves the write happened)
    assert dest.read_bytes() == secret

    # none of the spied callables saw the secret
    for args in print_calls:
        assert not any("SECRETVALUE" in str(a) for a in args[0]), (
            f"print leaked secret: {args}"
        )
    for (s,) in stdout_calls:
        assert "SECRETVALUE" not in s, f"stdout leaked secret: {s!r}"
    for (s,) in stderr_calls:
        assert "SECRETVALUE" not in s, f"stderr leaked secret: {s!r}"

    # the helper must not import logging (structural secrets-discipline check)
    assert not hasattr(atomic_mod, "logging"), (
        "_atomic.py must not import logging (T-03-03); secrets pass through it"
    )


# --------------------------------------------------------------------------- #
# Directory creation — the one non-atomic allowance
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_atomic_write_creates_missing_parent_dirs(tmp_path):
    """The helper creates missing parents (the one non-atomic allowance, D-09)."""
    dest = tmp_path / "a" / "b" / "c" / "cfg.toml"
    atomic_write(dest, b"x")
    assert dest.read_bytes() == b"x"
    assert dest.parent.is_dir(), "parent directories were not created"


# --------------------------------------------------------------------------- #
# Local helpers — module-namespace monkeypatching (intercepts the helper's
# exact os.replace / tempfile.NamedTemporaryFile calls).
# --------------------------------------------------------------------------- #
_REAL_REPLACE = atomic_mod.os.replace


def monkeypatch_os_replace(fn):
    atomic_mod.os.replace = fn


def restore_os_replace():
    atomic_mod.os.replace = _REAL_REPLACE


def monkeypatch_stdio(print_fn, stdout_fn, stderr_fn):
    builtins.print = print_fn
    sys.stdout.write = stdout_fn
    sys.stderr.write = stderr_fn


def restore_stdio(real_print, real_stdout_write, real_stderr_write):
    builtins.print = real_print
    sys.stdout.write = real_stdout_write
    sys.stderr.write = real_stderr_write
