"""Phase 8 — the read-only observability helpers for ``status`` (D-50..D-55).

This module holds the PURE provider-detection logic and a thin read-only
read-boundary translator for ``zai-codex-helper status``. It is the
declarative companion to Phase 7's Core Value: after ``use zai``, a user runs
``status`` to confirm Z.ai is active without hand-reading ``config.toml``.

PURITY CONTRACT (D-54, T-08-01 — load-bearing):

- NO filesystem IO. This module does NOT import ``Paths``, does NOT call
  ``Path.exists()``, does NOT ``open()`` anything, does NOT touch
  ``os.replace`` / ``os.chmod`` / ``unlink`` / ``mkdir`` / ``rename``. It
  takes a parsed ``tomlkit.TOMLDocument`` (or a ``config_present=False``
  signal) and returns a descriptor. The ONLY call that touches the outside
  world is :func:`read_for_status`, which delegates the read to a caller-
  supplied backend — and even there the module performs no writes.
- NO mutation of the parsed document. The detection helper reads via
  ``doc.get(...)`` only (read-only ``tomlkit`` access).

Provider detection (D-53): the active default is read from the flat top-level
``model_provider`` key. ``model_provider = "zai-moonbridge"`` -> Z.ai active;
absent -> OpenAI builtin default. Detection is NEVER inferred from ``model``
alone (a config may carry ``model = "glm-5.2"`` without the provider wired —
that is a misconfig reported truthfully via ``model_provider``).

Read boundary (D-52, T-08-02): ``TomlBackend.read()`` raises a
``tomlkit``-native parse error on malformed TOML, which is NOT a
:class:`ZaiCodexHelperError` subclass. :func:`read_for_status` translates any
non-:class:`ZaiCodexHelperError` raised by the read into a
:class:`ZaiCodexHelperError` so the handler stays catch-free and
:func:`zai_codex_helper.__main__.main`'s D-11 formatter owns the one-line
``error: <msg>`` + exit 1 (no traceback unless ``--debug``).
"""

from __future__ import annotations

from dataclasses import dataclass

from tomlkit import TOMLDocument

from zai_codex_helper.errors import ZaiCodexHelperError
from zai_codex_helper.services.providers import (
    ZAI_MODEL,
    ZAI_PROVIDER_ID,
    ZAI_REASONING_EFFORT,
)

__all__ = [
    "ProviderDescriptor",
    "OPENAI_BUILTIN_LABEL",
    "ZAI_LABEL",
    "detect_provider",
    "read_for_status",
]

#: The human-readable label for the Z.ai default (D-50). Kept here (not in
#: ``services.providers``) because providers.py owns the DESIRED STATE and this
#: module owns the OBSERVED STATE; the label is a status-rendering concern.
#: The model/effort VALUES come from providers.py (single source of truth).
ZAI_LABEL = "Z.ai"

#: The human-readable label for the OpenAI builtin default (D-50). Used when
#: ``model_provider`` is absent OR the config is missing entirely.
OPENAI_BUILTIN_LABEL = "OpenAI (builtin default)"


@dataclass(frozen=True)
class ProviderDescriptor:
    """The observed provider state for ``status`` rendering (D-50, D-53).

    A pure value object: detection produces it, the handler renders it. Fields:

    - ``provider_label``: the active default's human label (``ZAI_LABEL`` when
      ``model_provider == ZAI_PROVIDER_ID``; ``OPENAI_BUILTIN_LABEL``
      otherwise).
    - ``is_zai``: True iff ``model_provider == ZAI_PROVIDER_ID`` (D-53).
    - ``model``: the flat top-level ``model`` value, or ``None`` if absent.
    - ``model_reasoning_effort``: the flat top-level
      ``model_reasoning_effort`` value, or ``None`` if absent.
    - ``config_present``: True iff a ``config.toml`` was read. When False
      (missing config — D-52) the descriptor reports OpenAI builtin default
      with ``model``/``model_reasoning_effort`` None and a flag the handler
      uses to emit "config.toml not yet created".
    """

    provider_label: str
    is_zai: bool
    model: str | None
    model_reasoning_effort: str | None
    config_present: bool


def detect_provider(doc: TOMLDocument | None) -> ProviderDescriptor:
    """Detect the active provider from a parsed doc (D-53, D-54 — pure, no IO).

    Args:
        doc: A parsed ``tomlkit.TOMLDocument``, or ``None`` to signal the
            missing-config branch (D-52: missing != broken). When ``None``,
            reports OpenAI builtin default with ``config_present=False``.

    Returns:
        A :class:`ProviderDescriptor` describing the observed state.

    Detection rule (D-53, verbatim): read the flat top-level ``model_provider``
    key. If it equals :data:`~zai_codex_helper.services.providers.ZAI_PROVIDER_ID`
    (``"zai-moonbridge"``) -> Z.ai is active. If ``model_provider`` is absent
    (or the config is missing entirely) -> OpenAI builtin default. Do NOT
    infer from ``model`` (a config may carry ``model = "glm-5.2"`` without the
    provider wired — reported truthfully via ``model_provider``).

    The ``model`` and ``model_reasoning_effort`` values are read the SAME flat
    top-level way Phase 6 writes them (D-39). Pure: no Paths, no Path.exists,
    no open, no tomlkit mutation — read-only ``doc.get(...)`` only.
    """
    if doc is None:
        # D-52 missing-config branch: NOT broken. OpenAI builtin default with
        # no model/effort (the config.toml that carries them is not yet created).
        return ProviderDescriptor(
            provider_label=OPENAI_BUILTIN_LABEL,
            is_zai=False,
            model=None,
            model_reasoning_effort=None,
            config_present=False,
        )

    # D-53: detection by model_provider truth. Read-only tomlkit access.
    provider_id = doc.get("model_provider")
    is_zai = provider_id == ZAI_PROVIDER_ID
    label = ZAI_LABEL if is_zai else OPENAI_BUILTIN_LABEL

    # model / model_reasoning_effort are flat top-level (D-39). None if absent.
    model = doc.get("model")
    model = str(model) if model is not None else None
    effort = doc.get("model_reasoning_effort")
    effort = str(effort) if effort is not None else None

    return ProviderDescriptor(
        provider_label=label,
        is_zai=is_zai,
        model=model,
        model_reasoning_effort=effort,
        config_present=True,
    )


def read_for_status(backend) -> TOMLDocument | None:
    """Read ``config.toml`` for ``status``, translating parse errors (D-52).

    The read-boundary translator for the status path. Called by
    :func:`zai_codex_helper.cli.parser._handle_status` with the real
    :class:`~zai_codex_helper.backends.toml.TomlBackend`. Performs NO writes —
    it reads at most once.

    Behavior:

    - If the config does NOT exist (``backend.exists()`` is False) -> return
      ``None`` (the missing-config signal; D-52: missing != broken).
    - If the config exists -> return ``backend.read()`` (a parsed
      ``TOMLDocument``).
    - If ``backend.read()`` raises a tomlkit-native parse error (malformed
      TOML), translate it to :class:`ZaiCodexHelperError` so the handler stays
      catch-free and :func:`main`'s D-11 formatter owns the one-line
      ``error: <msg>`` + exit 1 (no traceback unless ``--debug``). Any
      already-:class:`ZaiCodexHelperError` is re-raised unchanged.

    Args:
        backend: A :class:`~zai_codex_helper.backends.toml.TomlBackend` (the
            concrete backend). Only ``backend.exists()`` and
            ``backend.read()`` are called — both read-only.

    Returns:
        A parsed ``TOMLDocument`` when the config exists, else ``None``.

    Raises:
        ZaiCodexHelperError: when ``backend.read()`` raises a non-
            :class:`ZaiCodexHelperError` (the malformed-TOML case), wrapping
            the parse message.
    """
    if not backend.exists():
        return None
    try:
        return backend.read()
    except ZaiCodexHelperError:
        # Already our error type — let it propagate unchanged.
        raise
    except Exception as e:  # noqa: BLE001 — tomlkit parse errors (and any
        # other read-time failure) are translated to ZaiCodexHelperError so
        # main()'s D-11 formatter owns the one-line `error:` + exit 1. We do
        # NOT catch ZaiCodexHelperError itself (handled above).
        raise ZaiCodexHelperError(f"config.toml is not parseable: {e}") from e


# Re-export the providers constants the handler uses for labels, so the status
# path imports everything from one place (the model/effort values shown when
# the config is missing/absent default to these canonical values).
_ = (ZAI_MODEL, ZAI_REASONING_EFFORT)  # re-export touch (avoid unused import)
