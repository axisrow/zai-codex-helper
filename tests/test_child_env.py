"""Unit tests for :func:`zai_codex_helper.services.env.child_env` (#16).

The sanitized env strips ZAI_API_KEY (and any future secret) before it can be
inherited by a child process, without disturbing the rest of the environment.
"""

from __future__ import annotations

import pytest

from zai_codex_helper.services.env import SENSITIVE_ENV_VARS, child_env


@pytest.mark.unit
def test_child_env_strips_both_secrets_keeps_path_home():
    """Both ZAI_API_KEY and MOONBRIDGE_API_KEY are removed; PATH/HOME survive.

    MOONBRIDGE_API_KEY is the legacy foreign-shim token the helper strips from
    .zshrc; if a user's shell still exports it, it must not leak to subprocesses.
    """
    src = {
        "ZAI_API_KEY": "secret",
        "MOONBRIDGE_API_KEY": "sk-moonbridge-zai-local",
        "PATH": "/usr/bin",
        "HOME": "/Users/x",
    }
    out = child_env(src)
    assert "ZAI_API_KEY" not in out
    assert "MOONBRIDGE_API_KEY" not in out
    assert out == {"PATH": "/usr/bin", "HOME": "/Users/x"}  # PATH/HOME preserved


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
def test_sensitive_set_contains_both_secrets():
    """The stripped-var set names both known secrets."""
    assert "ZAI_API_KEY" in SENSITIVE_ENV_VARS
    assert "MOONBRIDGE_API_KEY" in SENSITIVE_ENV_VARS
