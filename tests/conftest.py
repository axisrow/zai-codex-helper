"""Project-wide pytest configuration and shared fixtures.

The autouse ``_isolate_home`` fixture is the project's "do not corrupt the
developer's real files" ideology (CONTEXT D-14) made testable: it points
``HOME`` at a per-test temporary directory and pre-creates the ``.codex``
subdir inside it. Every test — unit, integration, smoke — gets this isolation
with zero opt-in (``autouse=True``). A buggy test in Phase 14 still must not
write to the developer's real ``~/.codex``.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    """Isolate EVERY test from the real ``$HOME`` (CONTEXT D-14).

    Sets ``HOME`` to a per-test ``tmp_path`` and pre-creates the ``.codex``
    directory so tests that touch ``$HOME/.codex`` write into the sandbox.
    Yields the isolated home path so tests that want to assert against it
    may request the fixture explicitly (see ``tests/test_home_isolation.py``).
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".codex").mkdir(parents=True, exist_ok=True)
    yield tmp_path
