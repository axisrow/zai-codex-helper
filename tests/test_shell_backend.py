"""Pin ROADMAP Phase 9 SC-2 (marker-fenced idempotent block + clean remove).

``ShellBackend`` is the concrete :class:`ConfigBackend` for ``~/.zshrc`` and
the dotfile-manager primitive Phase 12 ``setup`` injects shell helpers through
and Phase 13 uninstall removes. The user's ``.zshrc`` is precious hand-written
shell, so the backend's two load-bearing guarantees are:

- **Idempotent replace (SC-2 / D-57):** ``write_canonical`` called twice with
  the same body yields EXACTLY ONE fenced section (never an appended
  duplicate). Running ``setup`` twice produces identical output (mirrors
  CONF-06).
- **Lossless preservation (D-57):** everything OUTSIDE the marker fence
  survives a write byte-identical.
- **Clean remove (D-57):** ``remove_block`` deletes the fenced section
  (markers + content) cleanly, leaving the rest of ``.zshrc`` intact.

Style mirrors ``tests/test_toml_backend.py``: ``from __future__ import
annotations``, ``@pytest.mark.unit`` (flat ``tests/`` layout, CONTEXT D-14 HOME
isolation via the autouse ``_isolate_home`` fixture). All backends are built
from ``Paths.from_home(tmp_path)`` — never the real ``$HOME``.

What this file pins (one test per behavior in the plan's <behavior> block):

- append-when-no-markers (D-57 append branch)
- replace-in-place-when-markers-exist (D-57 replace branch; no duplication)
- write-twice-is-idempotent (SC-2 core; CONF-06 analog)
- preserves-outside-content (D-57 lossless)
- remove-block-cleans-fence (D-57 remove)
- remove-block-idempotent-no-fence (D-57 remove no-op)
- write-into-nonexistent-zshrc (fresh user)
- markers-are-exact-strings (D-60 pin against drift)
- backup-once-inherited-not-overridden (D-30)
- lands-at-0644 (D-DEFERRED-01 explicit mode)
"""

from __future__ import annotations

import inspect

import pytest

from zai_codex_helper.backends.base import ConfigBackend
from zai_codex_helper.backends.shell import (
    MARKER_END,
    MARKER_START,
    ShellBackend,
)
from zai_codex_helper.services.paths import Paths

# A representative shell-helper body (the kind Phase 12 will inject).
BODY = "codex-zai() { echo 'using z.ai'; }"
NEW_BODY = "codex-zai() { echo 'using z.ai v2'; }"


@pytest.mark.unit
def test_shell_append_when_no_markers(tmp_path):
    """D-57 append branch: no markers → fence appended, user content survives."""
    backend = ShellBackend(Paths.from_home(tmp_path))
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text("alias ll='ls -la'\n", encoding="utf-8")

    backend.write_canonical(BODY)

    result = zshrc.read_text(encoding="utf-8")
    # User line survives verbatim.
    assert "alias ll='ls -la'" in result
    # Fence appears exactly once, in order.
    assert result.count(MARKER_START) == 1
    assert result.count(MARKER_END) == 1
    assert result.index(MARKER_START) < result.index(MARKER_END)
    # Body is inside the fence.
    assert BODY in result


@pytest.mark.unit
def test_shell_replace_in_place_when_markers_exist(tmp_path):
    """D-57 replace branch: existing fence → replaced IN PLACE, no duplication."""
    backend = ShellBackend(Paths.from_home(tmp_path))
    zshrc = tmp_path / ".zshrc"
    user_content = "alias ll='ls -la'\n# my comment\n"
    # Seed: user content + an existing fence with OLD body.
    seed = f"{user_content}\n{MARKER_START}\nOLD_BODY\n{MARKER_END}\n"
    zshrc.write_text(seed, encoding="utf-8")

    backend.write_canonical(NEW_BODY)

    result = zshrc.read_text(encoding="utf-8")
    # Exactly ONE fence — no duplication (the SC-2 chokepoint).
    assert result.count(MARKER_START) == 1
    assert result.count(MARKER_END) == 1
    # NEW body present, OLD body gone.
    assert NEW_BODY in result
    assert "OLD_BODY" not in result
    # User content outside the fence is byte-identical to the seed (lossless).
    assert user_content in result


@pytest.mark.unit
def test_shell_write_twice_is_idempotent(tmp_path):
    """SC-2 core: write twice → identical output, exactly one fence (CONF-06 analog)."""
    backend = ShellBackend(Paths.from_home(tmp_path))
    # Empty .zshrc baseline.
    (tmp_path / ".zshrc").write_text("", encoding="utf-8")

    backend.write_canonical(BODY)
    snapshot = (tmp_path / ".zshrc").read_text(encoding="utf-8")

    backend.write_canonical(BODY)
    after = (tmp_path / ".zshrc").read_text(encoding="utf-8")

    assert after == snapshot  # idempotent — running setup twice = identical
    assert after.count(MARKER_START) == 1
    assert after.count(MARKER_END) == 1


@pytest.mark.unit
def test_shell_preserves_outside_content(tmp_path):
    """D-57 lossless: multi-line user content survives verbatim in original position."""
    backend = ShellBackend(Paths.from_home(tmp_path))
    zshrc = tmp_path / ".zshrc"
    user_content = (
        "# leading comment\n"
        "alias ll='ls -la'\n"
        "source ~/.zshrc.local\n"
        "\n"
        "export EDITOR=vim\n"
    )
    zshrc.write_text(user_content, encoding="utf-8")

    backend.write_canonical(BODY)

    result = zshrc.read_text(encoding="utf-8")
    # Every user line appears verbatim, in original relative order. The fenced
    # block is appended at the end; assert each user line survives unchanged.
    for line in user_content.splitlines():
        assert line in result, f"user line missing/modified: {line!r}"


@pytest.mark.unit
def test_shell_remove_block_cleans_fence(tmp_path):
    """D-57 remove: fenced section deleted; user content survives intact."""
    backend = ShellBackend(Paths.from_home(tmp_path))
    zshrc = tmp_path / ".zshrc"
    user_content = "alias ll='ls -la'\n# my comment\n"
    seed = f"{user_content}\n{MARKER_START}\n{BODY}\n{MARKER_END}\n"
    zshrc.write_text(seed, encoding="utf-8")

    backend.remove_block()

    result = zshrc.read_text(encoding="utf-8")
    assert MARKER_START not in result
    assert MARKER_END not in result
    assert BODY not in result
    # User content survives intact.
    assert "alias ll='ls -la'" in result
    assert "# my comment" in result


@pytest.mark.unit
def test_shell_remove_block_idempotent_no_fence(tmp_path):
    """D-57 remove no-op: removing from a fence-less file leaves it unchanged."""
    backend = ShellBackend(Paths.from_home(tmp_path))
    zshrc = tmp_path / ".zshrc"
    seed = "alias ll='ls -la'\n# no fence here\n"
    zshrc.write_text(seed, encoding="utf-8")

    backend.remove_block()

    assert zshrc.read_text(encoding="utf-8") == seed  # unchanged


@pytest.mark.unit
def test_shell_write_into_nonexistent_zshrc(tmp_path):
    """Fresh user: file absent → write_canonical creates it with just the fence."""
    backend = ShellBackend(Paths.from_home(tmp_path))
    # Do NOT seed .zshrc (file absent — fresh user).
    zshrc = tmp_path / ".zshrc"
    assert not zshrc.exists()

    backend.write_canonical(BODY)

    assert zshrc.exists()
    result = zshrc.read_text(encoding="utf-8")
    # read() returned "" so append produced just the fence.
    assert result.count(MARKER_START) == 1
    assert result.count(MARKER_END) == 1
    assert BODY in result
    # The fence is the whole file (no leading blank line, no user content).
    assert result.startswith(MARKER_START)
    assert result.rstrip("\n").endswith(MARKER_END)


@pytest.mark.unit
def test_shell_markers_are_exact_strings():
    """D-60: pin the EXACT marker literals against accidental drift."""
    assert MARKER_START == "# >>> zai-codex-helper >>>"
    assert MARKER_END == "# <<< zai-codex-helper <<<"


@pytest.mark.unit
def test_shell_backup_once_inherited_not_overridden():
    """D-30: backup_once is inherited from ConfigBackend, not overridden."""
    src = inspect.getsource(ShellBackend)
    assert "def backup_once" not in src, (
        "ShellBackend must NOT override backup_once (D-30 — inherited from ABC)"
    )
    # And it resolves to the ABC's concrete method.
    assert ShellBackend.backup_once is ConfigBackend.backup_once


@pytest.mark.unit
def test_shell_lands_at_0644(tmp_path):
    """D-DEFERRED-01: explicit default mode lands .zshrc at 0644 (dotfile convention)."""
    backend = ShellBackend(Paths.from_home(tmp_path))
    backend.write_canonical(BODY)

    mode = (tmp_path / ".zshrc").stat().st_mode & 0o777
    assert mode == 0o644, f".zshrc landed at {oct(mode)}, expected 0o644"


@pytest.mark.unit
def test_shell_write_raw_writes_verbatim_no_fence(tmp_path):
    """``write_raw`` writes the WHOLE text byte-for-byte, adding NO marker fence.

    Unlike ``write_canonical`` (which wraps its arg in the fence), ``write_raw``
    is the whole-file surface a caller like ``strip_foreign_codex_function`` uses
    to rewrite the user's .zshrc verbatim — routed through the backend, not a
    direct ``atomic_write``.
    """
    zshrc = tmp_path / ".zshrc"
    backend = ShellBackend(Paths.from_home(tmp_path))
    raw = "alias ll='ls -la'\n# user comment\nexport FOO=1\n"

    backend.write_raw(raw)

    written = zshrc.read_text(encoding="utf-8")
    assert written == raw  # exact bytes, nothing added
    assert MARKER_START not in written and MARKER_END not in written  # no fence


@pytest.mark.unit
def test_shell_write_raw_mode_none_preserves_existing_perms(tmp_path):
    """``write_raw(mode=None)`` preserves the file's existing permissions."""
    import os

    zshrc = tmp_path / ".zshrc"
    zshrc.write_text("old\n", encoding="utf-8")
    os.chmod(zshrc, 0o600)
    backend = ShellBackend(Paths.from_home(tmp_path))

    backend.write_raw("new\n")

    assert zshrc.read_text(encoding="utf-8") == "new\n"
    assert (zshrc.stat().st_mode & 0o777) == 0o600  # unchanged
