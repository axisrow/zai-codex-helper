"""Project-wide exception types.

``ZaiCodexHelperError`` is the single expected-error sentinel raised by the
services/backends layers and caught once in ``__main__.main`` to enforce the
D-11 / PKG-05 contract: a one-line ``error: <message>`` on stderr plus a
non-zero exit, with no traceback unless ``--debug`` is passed.

It lives in its own module (not in ``__main__``) so that the class object is
identical regardless of how the package is invoked — ``python -m
zai_codex_helper`` runs ``__main__.py`` as the ``__main__`` module, which would
otherwise create a *second* ``ZaiCodexHelperError`` distinct from the one
imported by ``backends``/``services``. That identity split would defeat the
single ``except`` in ``main()`` and leak a traceback in production (D-11
violation). One module, one class.
"""


class ZaiCodexHelperError(Exception):
    """Expected helper error → one-line message + non-zero exit, no traceback.

    Raised by services/backends layers when an anticipated failure occurs
    (file not found, TOML invalid, provider unresolvable, key missing).
    Caught once in :func:`zai_codex_helper.__main__.main`. The D-11 contract:
    print ``error: <msg>`` to stderr and exit non-zero; under ``--debug``
    re-raise so Python emits the full traceback for debugging.
    """
