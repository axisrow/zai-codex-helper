"""Unit tests for :func:`zai_codex_helper.services.env.child_env` (#16).

The sanitized env strips ZAI_API_KEY (and any future secret) before it can be
inherited by a child process, without disturbing the rest of the environment.
"""

from __future__ import annotations

import pytest

from zai_codex_helper.services.env import SENSITIVE_ENV_VARS, child_env


@pytest.mark.unit
def test_child_env_strips_zai_api_key():
    """ZAI_API_KEY is removed; every other var survives verbatim."""
    src = {"ZAI_API_KEY": "secret", "PATH": "/usr/bin", "HOME": "/Users/x"}
    out = child_env(src)
    assert "ZAI_API_KEY" not in out
    assert out == {"PATH": "/usr/bin", "HOME": "/Users/x"}


@pytest.mark.unit
def test_child_env_no_key_is_identity():
    """With no sensitive var present, the result equals the input (a fresh copy)."""
    src = {"PATH": "/usr/bin", "LANG": "en_US.UTF-8"}
    out = child_env(src)
    assert out == src
    assert out is not src  # a copy, not the same object


@pytest.mark.unit
def test_child_env_does_not_mutate_source():
    """The source mapping is never mutated."""
    src = {"ZAI_API_KEY": "secret", "PATH": "/usr/bin"}
    child_env(src)
    assert src["ZAI_API_KEY"] == "secret"  # source untouched


@pytest.mark.unit
def test_sensitive_set_contains_the_key():
    """The stripped-var set names ZAI_API_KEY (the one secret today)."""
    assert "ZAI_API_KEY" in SENSITIVE_ENV_VARS
