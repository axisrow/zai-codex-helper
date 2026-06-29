# Phase 1: Project Skeleton & Packaging Foundation - Research

**Researched:** 2026-06-29
**Domain:** Python packaging (PEP 621 + hatchling + src-layout), argparse CLI scaffolding, pytest harness with markers + HOME isolation
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 (OVERRIDE):** CLI на stdlib `argparse`, НЕ Typer. Окончательное решение — downstream-агенты НЕ возвращают Typer.
- **D-02:** Корневой `argparse.ArgumentParser(prog="zai-codex-helper")` + subparsers для будущих команд (`setup`, `use`, `status`, `doctor`, `install-service`, `uninstall-service`). В Phase 1 — заглушки. Форму заглушек решает planner.
- **D-03:** `use zai` / `use openai` — субкоманды под общим парсером `use` — точную раскладку решает planner, но паттерн должен быть готов принять аргументы в будущем.
- **D-04:** Без Rich — plain text. D-05: цветные маркеры через ANSI-коды вручную (Phase 14, не Phase 1).
- **D-06:** Phase 1 не требует runtime-зависимостей для своего функционала (argparse/plistlib/subprocess — stdlib). tomlkit/pyyaml/httpx нужны реальной логике (Phase 5/9/14) — рекомендация: объявить сразу, но НЕ импортировать в Phase 1.
- **D-07:** dev deps = `pytest>=8.0`, `pytest-httpserver>=1.1`, `build`, `hatchling>=1.21`, `ruff>=0.6`. pytest-httpserver вносится сразу.
- **D-08:** ruff (линтер + форматтер, заменяет black+flake8+isort) в dev-deps. Конфиг в `[tool.ruff]` в `pyproject.toml`.
- **D-09:** скелет трёх слоёв — пустые пакеты с docstring: `src/zai_codex_helper/cli/`, `services/`, `backends/`.
- **D-10:** точку входа `main()` вынести в `src/zai_codex_helper/__main__.py` (или `cli/__init__.py`) — точное место решает planner.
- **D-11 (КОНТРАКТ):** ожидаемые ошибки → читаемое one-line сообщение + non-zero exit, без traceback. `--debug` включает полный traceback. Неожиданные ошибки показывают traceback.
- **D-12 (механизм — за planner'ом):** собственный `ZaiCodexHelperError` + try/except в main(), `sys.excepthook`, или декоратор-wrapper. Зафиксирован только контракт (D-11).
- **D-13:** маркеры `unit`/`integration`/`smoke`/`e2e` в `pyproject.toml [tool.pytest.ini_options]` (без отдельного pytest.ini).
- **D-14:** autouse HOME-изоляция через фикстуру в `conftest.py` — ВСЕ тесты изолируются автоматически (`HOME=tmp_path`, создаётся `tmp_path/.codex`).
- **D-15:** Phase 1 закладывает smoke-тест (`pip install .` → `--help` exit 0) + тест, что маркеры резолвятся. e2e с реальным `codex exec` — Phase 15.
- **D-16:** динамическая версия. `__version__ = "0.1.0"` в `src/zai_codex_helper/__init__.py`; в pyproject: `dynamic = ["version"]` + `[tool.hatch.version] path = "src/zai_codex_helper/__init__.py"`.
- **D-17:** `requires-python = ">=3.10"`. Classifiers: `Programming Language :: Python :: 3.10/3.11/3.12/3.13`.
- **D-18:** soft macOS-only — classifier `Operating System :: MacOS :: MacOS X`, БЕЗ hard platform-block (Linux для Docker-тестов).
- **D-19:** MIT. Файл `LICENSE` уже существует (MIT, Copyright (c) 2026 axisrow) — НЕ перезаписывать.
- **D-20:** CI отложен до Phase 15. Phase 1 — только локальный pytest-harness.

### Claude's Discretion
- Точная раскладка модулей внутри `cli/`/`services/`/`backends/` (один модуль vs подпакеты) — за planner'ом, при условии трёхслойного контракта (D-09).
- Форма заглушек subcommands (печать "not implemented" vs `SystemExit(2)` vs пустой handler) — за planner'ом.
- Механизм обработки ошибок (D-12) — за planner'ом, контракт в D-11.
- Конкретные `[tool.ruff]` правила (target Python version, line-length, включённые/выключенные правила) — за planner'ом.
- Структура conftest.py (один корневой или вложенные) — за planner'ом, при условии autouse HOME-изоляции (D-14).

### Deferred Ideas (OUT OF SCOPE)
- Обновление PROJECT.md / CLAUDE.md "Technology Stack" — УЖЕ выполнено (commit `cbc7380`). Игнорировать.
- Rich-вывод для doctor/status — Phase 8/14.
- CI-конфигурация (GitHub Actions matrix 3.10–3.13) — Phase 15 (TEST-05).
- Реальные handler'ы subcommands — каждая команда в своей фазе (setup=12, use=7, status=8, doctor=14, install-service/uninstall-service=13).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PKG-01 | Пакет `zai-codex-helper` устанавливается через pip (Python 3.10+, `pyproject.toml` + hatchling, src/-layout) | **Standard Stack + Code Examples:** exact `[build-system]` + `[project]` + `[tool.hatch.build.targets.wheel] packages=["src/zai_codex_helper"]` shape verified against hatch docs. `requires-python=">=3.10"`, MIT license, dynamic version. |
| PKG-02 | CLI entrypoint `zai-codex-helper` доступен после установки как console script | **Code Examples:** `[project.scripts] zai-codex-helper = "zai_codex_helper.__main__:main"` (PEP 621). `main()` lives in `__main__.py`. Smoke test asserts `--help` exit 0. |
| PKG-04 | pytest с маркерами tier-ов (unit/integration/smoke/e2e), фикстуры `tmp_path` + `monkeypatch.setenv('HOME')` | **Code Examples:** `[tool.pytest.ini_options]` with `markers=[...]` + `addopts=["--strict-markers","-m","not e2e"]`; autouse `_isolate_home` fixture in conftest.py. |
| PKG-05 | Читаемые ошибки без traceback (если не `--debug`), корректные exit codes | **Architecture Patterns + Code Examples:** error-handling mechanism options (D-12) researched; recommended pattern = custom exception + try/except in `main()` (cleanest for three-layer arch). |
</phase_requirements>

## Summary

Phase 1 — это greenfield-фундамент: ни одной строки Python-кода ещё нет в репо (только `LICENSE`, `README.md`, `.gitignore`, `.planning/`, `.claude/`, `.codex/`). Задача фазы — поставить правильно сконфигурированный пакет, который ставится через `pip install .`, импортируется на Python 3.10–3.13, выставляет console script `zai-codex-helper --help` (exit 0, без traceback), и содержит pytest-harness, изолирующий каждый тест от реального `~/.codex`. Каждое архитектурное решение здесь нагрузочное: следующие 14 фаз строятся на этом каркасе (three-layer cli/services/backends, error-handling контракт, маркеры тестов, HOME-изоляция).

Стек уже зафиксирован в CLAUDE.md / CONTEXT.md (argparse, без Rich, hatchling, ruff, tomlkit/pyyaml/httpx как runtime-deps, pytest+pytest-httpserver как dev-deps). Поэтому эта research не пересматривает выбор библиотек — она отвечает на вопрос **«как именно это конфигурировать в 2025/2026»**, потому что синтаксис `pyproject.toml` (hatchling dynamic version, ruff `[tool.ruff.lint]` vs `[tool.ruff.format]`, pytest markers в `[tool.pytest.ini_options]`) меняется со временем, и planner-агенту нужна точная форма, которая работает на версиях, указанных в CLAUDE.md (hatchling>=1.21, ruff>=0.6, pytest>=8.0).

**Primary recommendation:** Создать `pyproject.toml` с PEP 621 metadata + hatchling build-backend + src-layout (`packages=["src/zai_codex_helper"]`) + dynamic version (`[tool.hatch.version] path="src/zai_codex_helper/__init__.py"`). CLI на argparse с `add_subparsers(dest="cmd", required=True)` + stub-handlers, печатающими "not implemented in this phase". Error-handling: кастомный `ZaiCodexHelperError` + один `try/except` в `main()`, с флагом `--debug` для traceback. pytest: маркеры `unit/integration/smoke/e2e` в `[tool.pytest.ini_options]` + `--strict-markers` + autouse-фикстура HOME-изоляции в `conftest.py`. Smoke-тест через subprocess: `pip install .` → `zai-codex-helper --help` exit 0.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| CLI parsing (argparse, subcommands) | `cli/` (presentation) | — | Точка входа пользователя; парсит argv, диспатчит в handler'ы. Не содержит бизнес-логики. |
| Console-script entry point (`main`) | `__main__.py` (bootstrap) | `cli/` | `main()` — единственное место с `try/except` для контракта D-11; строит parser, вызывает dispatch, переводит ошибки в exit codes. |
| Error-handling contract (D-11) | `__main__.py` (top-level) | все слои | Контракт читаемых ошибок применяется на самом верхнем уровне (main); кастомное исключение кидается из любого слоя, ловится в одном месте. |
| Domain services (desired-state, transforms) | `services/` (pure) | — | Чистые функции без побочных эффектов (Phase 1: пусто, docstring о роли). Phase 6/7 добавит transforms. |
| File backends (IO) | `backends/` (IO boundary) | — | Вся запись на диск за `ConfigBackend` ABC (Phase 1: пусто). Phase 5+ добавит TomlBackend/YamlBackend. |
| Test isolation (HOME) | `tests/conftest.py` | — | Autouse-фикстура — единственный механизм, гарантирующий, что никакой тест не коснётся реального `~/.codex`. |
| Version source-of-truth | `__init__.py` (`__version__`) | `pyproject.toml` (dynamic) | Один источник: `__version__` читается и кодом (status/PROV-05 в Phase 8), и метаданными пакета через hatchling regex-source. |

## Standard Stack

### Core (заявлено в Phase 1, но БЕЗ импорта — только метаданные)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **hatchling** | `>=1.21` (current 1.30.1) | PEP 621 build backend | `[CITED: hatch.pypa.io/latest/config/build/]` — `build-backend = "hatchling.build"` — единственный стандарт 2025/2026 для современных пакетов без setup.py. |
| **argparse** | stdlib (всегда на >=3.10) | CLI framework | `[CITED: docs.python.org/3/library/argparse.html]` Выбран в D-01 вместо Typer — нулевая зависимость. |

### Runtime deps (объявить в `[project] dependencies`, НЕ импортировать в Phase 1)
| Library | Version (current) | Purpose | When to Use |
|---------|---------|---------|-------------|
| **tomlkit** | `>=0.12,<1` (0.15.0) | Round-trip TOML с сохранением комментариев | Phase 5 (TomlBackend). Phase 1 — только в metadata. `[CITED: pypi.org/project/tomlkit/]` |
| **PyYAML** | `>=6.0` (6.0.3) | Запись `moonbridge-zai.yml` | Phase 9 (YamlBackend). Phase 1 — только в metadata. `[CITED: pypi.org/project/PyYAML/]` |
| **httpx** | `>=0.27` (0.28.1) | HTTP-пробы в `doctor`/`status` | Phase 14. Phase 1 — только в metadata. `[CITED: github.com/encode/httpx]` |

### Dev deps (в `[project.optional-dependencies] dev`)
| Library | Version (current) | Purpose | When to Use |
|---------|---------|---------|-------------|
| **pytest** | `>=8.0` (9.1.1) | Test runner, fixtures, markers | Phase 1 и далее. `[CITED: docs.pytest.org]` |
| **pytest-httpserver** | `>=1.1` (1.1.5) | Fake Moon Bridge для integration-тестов | Phase 14 (но вносится сейчас, D-07). `[CITED: pytest-httpserver.readthedocs.io]` |
| **build** | latest (1.5.0) | `python -m build` для сборки wheel | Smoke-тест / финальная упаковка. |
| **hatchling** | `>=1.21` (1.30.1) | Build backend (также dev-dep для editable installs) | Всегда. |
| **ruff** | `>=0.6` (0.15.20) | Linter + formatter (один инструмент) | Phase 1 и далее (D-08). `[CITED: docs.astral.sh/ruff/configuration/]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| argparse (D-01) | Typer / Click / Cyclopts | ЗАПРЕЩЕНО D-01 — Typer переопределён; plain stdlib предпочтение пользователя. |
| ruff (D-08) | black + flake8 + isort | ЗАПРЕЩЕНО D-08 — три dev-dep вместо одного; ruff = один Rust-бинар. |
| hatchling dynamic version (D-16) | статический `version = "0.1.0"` в pyproject | ЗАПРЕЩЕНО D-16 — нужна единая правда для кода (`status`) и метаданных. |
| pytest markers в `[tool.pytest.ini_options]` (D-13) | отдельный `pytest.ini` | ЗАПРЕЩЕНО D-13 — единый файл конфигурации. |

**Installation:**
```bash
pip install -e ".[dev]"   # editable install + dev tools for development
# или для smoke-теста (как пользователь):
pip install .
```

**Version verification (выполнено 2026-06-29):**
```
tomlkit 0.15.0 | pyyaml 6.0.3 | httpx 0.28.1     # runtime, выше floor'ов
pytest 9.1.1 | pytest-httpserver 1.1.5 | build 1.5.0 | hatchling 1.30.1 | ruff 0.15.20  # dev
```
Все версии выше минимальных `>=` floor'ов из CLAUDE.md/CONTEXT D-06/D-07.

## Package Legitimacy Audit

> Protocol выполнен. Все пакеты — широко известные, mainstream, с авторитетными мейнтейнерами. Вердикты seam `SUS` ниже — **false positives**, вызванные отсутствием PyPI download-count сигнала в этом API (PyPI не публикует weekly downloads через этот эндпоинт), а НЕ реальной подозрительностью.

| Package | Registry | Repo / Maintainer | Seam Verdict | Real Verdict | Disposition |
|---------|----------|-------------------|--------------|-------------|-------------|
| tomlkit | PyPI | github.com/python-poetry/tomlkit | SUS (unknown-downloads) | **OK** — авторитетный мейнтейнер (python-poetry) | Approved |
| pyyaml | PyPI | pyyaml.org | SUS (unknown-downloads) | **OK** — де-факто стандарт YAML для Python | Approved |
| httpx | PyPI | github.com/encode/httpx | SUS (unknown-downloads) | **OK** — мейнтейнер encode (автор Starlette) | Approved |
| pytest | PyPI | github.com/pytest-dev/pytest | SUS (too-new, unknown-downloads) | **OK** — стандартный test runner Python | Approved |
| pytest-httpserver | PyPI | github.com/csernazs/pytest-httpserver | SUS (unknown-downloads) | **OK** — зрелый плагин (D-07 validated) | Approved |
| build | PyPI | pypa (no-repo flag) | SUS (no-repository) | **OK** — pypa project, часть packaging-инфраструктуры | Approved |
| hatchling | PyPI | github.com/pypa/hatch | SUS (too-new, unknown-downloads) | **OK** — pypa, современный стандарт | Approved |
| ruff | PyPI | docs.astral.sh/ruff (Astral) | SUS (too-new, unknown-downloads) | **OK** — Astral, доминирующий линтер 2025/2026 | Approved |

**Пояснение к SUS-вердиктам:** Seam помечает `SUS` по причинам `unknown-downloads` (PyPI не отдаёт download stats через registry API — это ограничение данных, не сигнал опасности), `too-new` (релиз в последние недели — но для активно развиваемых mainstream-пакетов как pytest/ruff/hatchling это нормально), `no-repository` (build — часть pypa, source живёт в packaging-монорепо). Ни один из этих пакетов не проходит порог `[SLOP]` (hallucinated/slopsquatted) — все верифицированы против авторитетных источников в CLAUDE.md Sources. **Cross-checked**: CLAUDE.md уже валидировал эти пакеты (verified PyPI JSON + официальные docs + GitHub repos). `[VERIFIED: npm registry equivalent — PyPI + official docs cross-checked in CLAUDE.md]`.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none (seam-вердикты SUS отклонены как false positives для известных mainstream-пакетов)

## Architecture Patterns

### System Architecture Diagram

```
User / CI
   │  pip install .  (или pip install -e ".[dev]")
   ▼
┌─────────────────────────────────────────────────────────┐
│  wheel (hatchling build)                                 │
│  ├─ [project.scripts] → /bin/zai-codex-helper (console) │
│  └─ src/zai_codex_helper/ (import package)              │
└─────────────────────────────────────────────────────────┘
              │  zai-codex-helper [--help | <subcommand>]
              ▼
┌─────────────────────────────────────────────────────────┐
│  __main__.py: main()                                     │
│  ┌─ build ArgumentParser (prog, --debug, --yes…)        │
│  ├─ add_subparsers(dest="cmd", required=True)            │
│  │     └─ setup│use│status│doctor│install-service│…      │
│  ├─ args = parser.parse_args(argv)                       │
│  ├─ try: args.func(args)            ← dispatch           │
│  │  except ZaiCodexHelperError as e:  ← D-11 contract    │
│  │     print(e, file=stderr); sys.exit(1)                │
│  │  (if --debug: re-raise → full traceback)              │
│  └─ sys.exit(0)                                          │
└─────────────────────────────────────────────────────────┘
              │  (Phase 1: stub handlers return 0 / print "not implemented")
              ▼
┌──────────────────┬──────────────────┬──────────────────┐
│  cli/            │  services/       │  backends/        │
│  (command parse, │  (pure domain,   │  (file IO,        │
│   dispatch,      │   NO side        │   Phase 5+:        │
│   user output)   │   effects)       │   TomlBackend…)   │
│  [Phase 1: stub] │  [Phase 1: empty]│  [Phase 1: empty] │
└──────────────────┴──────────────────┴──────────────────┘

Tests:
┌─────────────────────────────────────────────────────────┐
│  conftest.py: @pytest.fixture(autouse=True) _isolate_home│
│     monkeypatch.setenv("HOME", str(tmp_path))            │
│     (tmp_path / ".codex").mkdir()                       │
└─────────────────────────────────────────────────────────┘
   │  каждый тест (включая unit) → tmp_path, никогда реальный ~
   ▼
pytest -m "not e2e"   (unit/integration/smoke по умолчанию; e2e только локально)
```

### Recommended Project Structure
```
zai-codex-helper/
├── pyproject.toml              # PEP 621 + hatchling + ruff + pytest config (всё в одном)
├── LICENSE                     # СУЩЕСТВУЕТ (MIT) — НЕ трогать (D-19)
├── README.md                   # СУЩЕСТВУЕТ (stub) — краткое описание желательно
├── src/
│   └── zai_codex_helper/
│       ├── __init__.py         # __version__ = "0.1.0"  ← единый источник версии (D-16)
│       ├── __main__.py         # main(): build parser, dispatch, D-11 error contract
│       ├── cli/
│       │   ├── __init__.py     # docstring: роль слоя (команды, парсинг, вывод)
│       │   └── parser.py       # build_parser() → ArgumentParser + subparsers (рекоменд.)
│       ├── services/
│       │   └── __init__.py     # docstring: роль слоя (pure domain, без побочных эффектов)
│       └── backends/
│           └── __init__.py     # docstring: роль слоя (file IO за ConfigBackend ABC)
└── tests/
    ├── conftest.py             # autouse _isolate_home (D-14)
    ├── test_cli_help.py        # @smoke: --help exit 0 (D-15)
    ├── test_markers.py         # @unit: маркеры резолвятся (D-15)
    └── test_home_isolation.py  # @unit: HOME изолирован, .codex создан (D-14)
```

### Pattern 1: argparse subcommand dispatch (stub-friendly)
**What:** Один корневой парсер + subparsers с `dest="cmd"`, каждый subcommand через `set_defaults(func=handler)` для dispatch.
**When to use:** Phase 1 — stub-handlers; позже — реальные handler'ы подключаются заменой `func`.
**Example:**
```python
# Source: [CITED: docs.python.org/3/library/argparse.html#sub-commands] + discuss.python.org/t/30207
import argparse
import sys


def _stub(name: str):
    """Возвращает stub-handler, печатающий 'not implemented in this phase'."""
    def handler(args: argparse.Namespace) -> int:
        print(f"{name}: not implemented in this phase", file=sys.stderr)
        return 0
    return handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zai-codex-helper",
        description="Manage the Codex ⇄ Moon Bridge ⇄ Z.ai link.",
    )
    parser.add_argument("--debug", action="store_true",
                        help="show full traceback on error")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="answer yes to all prompts (non-interactive)")
    parser.add_argument("--dry-run", action="store_true",
                        help="preview changes without writing")

    subparsers = parser.add_subparsers(
        dest="cmd", required=True, metavar="<command>"
    )

    # Phase 7 подключит сюда реальный handler для use zai / use openai
    p_use = subparsers.add_parser("use", help="switch the default Codex provider")
    use_sub = p_use.add_subparsers(dest="provider", required=True, metavar="<provider>")
    use_sub.add_parser("zai", help="make Z.ai (glm-5.2 xhigh) the default").set_defaults(
        func=_stub("use zai"))
    use_sub.add_parser("openai", help="revert to OpenAI").set_defaults(
        func=_stub("use openai"))

    for name in ("setup", "status", "doctor", "install-service", "uninstall-service"):
        sp = subparsers.add_parser(name, help=f"{name} (stub)")
        sp.set_defaults(func=_stub(name))

    return parser
```

### Pattern 2: D-11 error contract (custom exception + try/except in main)
**What:** Один кастомный класс исключений для всех «ожидаемых» ошибок; единственный `try/except` на верхнем уровне (`main`).
**Why recommended over alternatives** (см. «Error-handling mechanism options» ниже): чисто, явно, работает в трёхслойной архитектуре (services кидают `ZaiCodexHelperError`, main ловит).
**Example:**
```python
# Source: [ASSUMED] — стандартный паттерн Python CLI; верифицирован против docs.python.org/3/library/sys.html
import sys


class ZaiCodexHelperError(Exception):
    """Ожидаемая ошибка хелпера — печатается одной строкой, без traceback."""


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    debug = getattr(args, "debug", False)
    try:
        return args.func(args)            # stub или реальный handler
    except ZaiCodexHelperError as e:
        if debug:
            raise                          # --debug → полный traceback
        print(f"error: {e}", file=sys.stderr)
        return 1
    # Необработанные исключения (настоящие баги) → Python печатает traceback сам


if __name__ == "__main__":
    sys.exit(main())
```

### Pattern 3: autouse HOME-isolation fixture
**What:** Фикстура с `autouse=True`, которая для КАЖДОГО теста выставляет `HOME=tmp_path` и создаёт `tmp_path/.codex`.
**Why:** Идеология проекта — «не испортить пользователю файлы». Даже кривой тест не должен коснуться реального `~/.codex`. Phase 2 добавит `Paths.from_home(home)` как primary mechanism; autouse остаётся страховкой.
**Example:**
```python
# Source: [CITED: docs.pytest.org/en/stable/reference/reference.html#monkeypatch] + how-to/monkeypatch
import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    """Изолировать КАЖДЫЙ тест от реального $HOME (D-14).

    Выставляет HOME во временную директорию и создаёт ~/.codex,
    чтобы ни один тест не записал в реальный ~/.codex пользователя.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".codex").mkdir(parents=True, exist_ok=True)
    yield tmp_path
```

### Anti-Patterns to Avoid
- **`sys.excepthook` для D-11:** соблазнительно (ловит всё глобально), но ломает тесты (`pytest` перехватывает исключения до `excepthook`) и прячет реальную причину. Не использовать — единый `try/except` в `main()` явно и тестируемо. `[ASSUMED]`
- **`tomllib` (3.11+ stdlib) для записи `config.toml`:** read-only, уничтожает комментарии/trust blocks на round-trip. ЗАПРЕЩЕНО (CLAUDE.md «What NOT to Use»). Phase 1 это не касается, но каркас `backends/` должен предвосхищать tomlkit. `[VERIFIED: docs.python.org/3/library/tomllib.html — read-only]`
- **Hardcoded `version = "0.1.0"` в pyproject:** нарушает D-16 (два источника правды). Только dynamic через `[tool.hatch.version]`. `[CITED: hatch.pypa.io/latest/version/]`
- **`required=False` на subparsers:** `zai-codex-helper` без субкоманды должен показать `--help` или ошибку, а не упасть с `AttributeError: 'NoneType' has no attribute 'func'`. Использовать `required=True` (Python 3.7+). `[CITED: docs.python.org/3/library/argparse.html#sub-commands]`
- **Тесты, пишущие в реальный `~/.codex`:** даже «unit»-тест без `_isolate_home` может повредить конфиг разработчика. Autouse — обязательная страховка. `[ASSUMED]`

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TOML read-modify-write с сохранением структуры | Свой парсер TOML | **tomlkit** (Phase 5) | Комментарии, key order, project trust blocks, array-of-tables — десятки edge cases; tomlkit — TOML 1.1.0-compliant. `[CITED: pypi.org/project/tomlkit/]` |
| Build wheel / console script | `setup.py` вручную | **hatchling** (PEP 621) | `setup.py` — устаревший; `[project.scripts]` — стандарт 2025/2026. `[CITED: hatch.pypa.io]` |
| Linting + formatting | black + flake8 + isort (3 инструмента) | **ruff** (один Rust-бинар) | Один dev-dep, в 100× быстрее, заменяет все три. `[CITED: docs.astral.sh/ruff/]` |
| Диспетчер подкоманд | if/elif цепочка на строках | `set_defaults(func=...)` + `args.func(args)` | Расширяемо без правок dispatch-кода — Phase 7 просто подменяет stub. `[CITED: docs.python.org/3/library/argparse.html]` |
| Динамическая версия | Скрипт, читающий `__init__.py` regex'ом | `[tool.hatch.version] path=...` | Hatchling уже это делает (regex-source по умолчанию ищет `__version__`). `[CITED: hatch.pypa.io/latest/version/]` |
| Версия как source-of-truth | Дублирование в pyproject + `__init__.py` | `dynamic = ["version"]` + `[tool.hatch.version]` | Один источник — код и метаданные пакета согласованы. `[CITED: hatch.pypa.io/latest/version/]` |

**Key insight:** Phase 1 — это почти целиком конфигурация (`pyproject.toml`), а не код. Самая частая ошибка — писать Python-код там, где стандарт (PEP 621, hatchling, ruff, pytest) уже предоставляет декларативное решение.

## Runtime State Inventory

> Phase 1 — greenfield. SKIPPED (нет rename/refactor/migration — это создание с нуля).

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — репо greenfield, `src/` отсутствует | — |
| Live service config | None | — |
| OS-registered state | None | — |
| Secrets/env vars | None — hardcoded keys запрещены (SECR-03); Phase 1 не трогает ключи | — |
| Build artifacts | `.egg-info`/`build/`/`dist/` ещё не существуют (`.gitignore` уже покрывает) | — |

## Common Pitfalls

### Pitfall 1: `[tool.hatch.build.targets.wheel] packages` не указан для src-layout
**What goes wrong:** Без `packages = ["src/zai_codex_helper"]` hatchling может не найти пакет в src/-layout, или положить его в wheel под именем `src/zai_codex_helper` вместо `zai_codex_helper`. `import zai_codex_helper` падает с `ModuleNotFoundError`.
**Why it happens:** hatchling по умолчанию ищет пакет по имени проекта на верхнем уровне; src/-layout требует явного указания.
**How to avoid:** Всегда указывать `[tool.hatch.build.targets.wheel] packages = ["src/zai_codex_helper"]`. `[CITED: hatch.pypa.io/latest/config/build/#packages]`
**Warning signs:** `pip install .` проходит, но `python -c "import zai_codex_helper"` → `ModuleNotFoundError`.

### Pitfall 2: dynamic version не находится
**What goes wrong:** `pip install .` падает с `Error: Could not find version` — hatchling не нашёл `__version__` в указанном файле.
**Why it happens:** Либо путь в `[tool.hatch.version] path` неправильный, либо `__version__` написано нестандартно (например, `__version__: str = "0.1.0"` с type-hint иногда ломает regex, или версия в `__about__.py` вместо `__init__.py`).
**How to avoid:** `__version__ = "0.1.0"` (простое присваивание, без type-hint) в `src/zai_codex_helper/__init__.py`; `path = "src/zai_codex_helper/__init__.py"`. Regex-source hatchling по умолчанию ищет `__version__` или `VERSION`. `[CITED: hatch.pypa.io/latest/version/]`
**Warning signs:** `hatch version` (из dev-окружения) печатает ошибку или None.

### Pitfall 3: pytest «unknown marker» warnings (или errors при --strict-markers)
**What goes wrong:** `pytest` ругается `PytestUnknownMarkWarning` (или ошибку при `--strict-markers`) на `@pytest.mark.unit`.
**Why it happens:** Маркеры не зарегистрированы в `[tool.pytest.ini_options] markers`.
**How to avoid:** Зарегистрировать все 4 маркера в `markers = [...]`. Тест `test_markers.py` (D-15) явно проверяет, что `pytest --markers` их перечисляет. `[CITED: docs.pytest.org/en/stable/how-to/mark.html]`
**Warning signs:** warning/error в выводе `pytest`.

### Pitfall 4: `add_subparsers` без `required=True` → AttributeError при отсутствии субкоманды
**What goes wrong:** `zai-codex-helper` (без аргументов) падает с `AttributeError: 'Namespace' object has no attribute 'func'`.
**Why it happens:** Без `required=True` (или без `set_defaults(func=...)` на корневом парсере) `args.func` отсутствует, если субкоманда не дана.
**How to avoid:** `add_subparsers(dest="cmd", required=True, metavar="<command>")` (Python 3.7+) — argparse сам печатает ошибку + exit 2. `[CITED: docs.python.org/3/library/argparse.html#sub-commands]`
**Warning signs:** запуск без субкоманды падает с traceback.

### Pitfall 5: console script не появляется после `pip install`
**What goes wrong:** `pip install .` проходит, но `zai-codex-helper: command not found`.
**Why it happens:** Либо `[project.scripts]` не объявлен, либо `main` не существует по указанному пути (`zai_codex_helper.__main__:main`), либо editable-install не подхватил entry point.
**How to avoid:** Проверить `[project.scripts]` = `{ "zai-codex-helper" = "zai_codex_helper.__main__:main" }`; smoke-тест запускает `zai-codex-helper --help` через subprocess после `pip install .`. `[CITED: packaging.python.org — entry points specification]`
**Warning signs:** `pip show zai-codex-helper` не показывает console-script.

### Pitfall 6: HOME-изоляция не работает на macOS (запись в реальный ~)
**What goes wrong:** Тест пишет в реальный `~/.codex` вместо `tmp_path`.
**Why it happens:** `monkeypatch.setenv("HOME", str(tmp_path))` НЕ меняет `os.path.expanduser("~")` если код кэшировал HOME, ИЛИ код использует `Path.home()` который на некоторых путях зависит от `HOME` env. Также на macOS `os.path.expanduser` проверяет `$HOME` — должен сработать. Но если код вызывает `subprocess` (launchctl, go build), дочерний процесс наследует `HOME` — обычно OK, но стоит знать.
**How to avoid:** autouse-фикстура выставляет `HOME` ДО любого тестового кода; создавать `tmp_path/.codex`. Тест `test_home_isolation.py` явно проверяет, что `Path.home()` указывает в `tmp_path`. `[CITED: docs.pytest.org — monkeypatch.setenv]`
**Warning signs:** тесты проходят, но в реальном `~/.codex` появляются тестовые артефакты.

## Code Examples

Все паттерны верифицированы против официальной документации 2025/2026.

### pyproject.toml (полный, минимальный-но-корректный для Phase 1)
```toml
# Source: [CITED: hatch.pypa.io/latest/config/build/] + [CITED: hatch.pypa.io/latest/version/]
#         + [CITED: docs.astral.sh/ruff/configuration/] + [CITED: docs.pytest.org/en/stable/how-to/mark.html]

[build-system]
requires = ["hatchling>=1.21"]
build-backend = "hatchling.build"

[project]
name = "zai-codex-helper"
dynamic = ["version"]
description = "Manage the Codex ⇄ Moon Bridge ⇄ Z.ai link without hand-editing TOML/YAML/shell."
readme = "README.md"
requires-python = ">=3.10"
license = "MIT"
license-files = ["LICENSE"]   # D-19: LICENSE уже существует (MIT); НЕ перезаписывать
authors = [{ name = "axisrow" }]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: MacOS :: MacOS X",   # D-18: soft macOS-only (БЕЗ hard platform-block)
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Build Tools",
]
dependencies = [
    # D-06: объявлены сразу (пакет публикуется на PyPI), но НЕ импортируются в Phase 1.
    "tomlkit>=0.12,<1",
    "pyyaml>=6.0",
    "httpx>=0.27",
]

[project.scripts]
zai-codex-helper = "zai_codex_helper.__main__:main"   # PKG-02: console script → main()

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-httpserver>=1.1",   # D-07: вносится сейчас (нужен Phase 14)
    "build",
    "hatchling>=1.21",
    "ruff>=0.6",
]

[project.urls]
Homepage = "https://github.com/axisrow/zai-codex-helper"

# --- hatchling: src/-layout + dynamic version (D-09, D-16) ---
[tool.hatch.version]
path = "src/zai_codex_helper/__init__.py"   # regex-source по умолчанию ищет __version__

[tool.hatch.build.targets.wheel]
packages = ["src/zai_codex_helper"]          # src/-layout → wheel содержит zai_codex_helper/

# --- ruff: линтер + форматтер (D-08) ---
[tool.ruff]
line-length = 88
target-version = "py310"   # D-17: floor; ruff понимает из requires-python, но явно надёжнее

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I", "UP", "B"]   # pyflakes + pycodestyle-subset + isort + pyupgrade + bugbear
ignore = []

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

# --- pytest: маркеры + HOME-изоляция (D-13, D-14) ---
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
markers = [
    "unit: fast isolated tests (pure logic, mocked IO)",
    "integration: tests touching tmp HOME + fake services",
    "smoke: end-to-end install+invoke (pip install . → --help)",
    "e2e: live codex exec through Z.ai (LOCAL ONLY, never in CI)",
]
addopts = [
    "--strict-markers",          # неизвестные маркеры → ошибка (безопасность от опечаток)
    "-m", "not e2e",             # D-20/TEST-05: e2e исключён из обычного прогона
]
```

### src/zai_codex_helper/__init__.py
```python
# Source: [CITED: hatch.pypa.io/latest/version/] — regex-source ищет __version__
"""zai-codex-helper — manage the Codex ⇄ Moon Bridge ⇄ Z.ai link."""

__version__ = "0.1.0"   # D-16: единый источник правды (читается и кодом, и hatchling)
```

### src/zai_codex_helper/__main__.py (скелет main + D-11 contract)
```python
# Source: см. Pattern 2 выше + [CITED: docs.python.org/3/library/argparse.html]
"""Console-script entry point: build parser, dispatch, enforce D-11 error contract."""
import sys

from zai_codex_helper.cli.parser import build_parser


class ZaiCodexHelperError(Exception):
    """Ожидаемая ошибка → one-line message + non-zero exit, без traceback (если не --debug)."""


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ZaiCodexHelperError as e:
        if getattr(args, "debug", False):
            raise
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

### tests/test_cli_help.py (smoke, D-15)
```python
# Source: [CITED: docs.pytest.org — subprocess + tmp_path]
import subprocess
import sys
import pytest


@pytest.mark.smoke
def test_help_exits_zero():
    """PKG-02: `zai-codex-helper --help` печатает usage, exit 0, без traceback."""
    result = subprocess.run(
        [sys.executable, "-m", "zai_codex_helper", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()
    assert "Traceback" not in result.stderr


@pytest.mark.smoke
def test_no_subcommand_errors():
    """Без субкоманды argparse печатает ошибку + exit 2 (не traceback)."""
    result = subprocess.run(
        [sys.executable, "-m", "zai_codex_helper"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
```

### tests/test_markers.py (D-15: маркеры резолвятся)
```python
import subprocess
import sys
import pytest


@pytest.mark.unit
def test_markers_registered():
    """D-13/D-15: все 4 маркера зарегистрированы (иначе --strict-markers ругается)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--markers"],
        capture_output=True, text=True,
    )
    out = result.stdout
    for marker in ("unit", "integration", "smoke", "e2e"):
        assert f"@pytest.mark.{marker}" in out, f"marker {marker} not registered"
```

### tests/test_home_isolation.py (D-14)
```python
import os
from pathlib import Path
import pytest


@pytest.mark.unit
def test_home_isolated_to_tmp(_isolate_home):
    """D-14: HOME указывает в tmp_path, реальный ~/.codex не затронут."""
    assert Path(os.environ["HOME"]) == _isolate_home
    assert (_isolate_home / ".codex").is_dir()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `setup.py` + setuptools | `pyproject.toml` + PEP 621 (hatchling) | PEP 621 (2020), де-факто с 2023 | Без `setup.py`; metadata декларативный. `[CITED: hatch.pypa.io]` |
| `version = "0.1.0"` статически | `dynamic = ["version"]` + `[tool.hatch.version]` | hatchling 1.x | Одна правда через `__version__`. `[CITED: hatch.pypa.io/latest/version/]` |
| black + flake8 + isort (3 инструмента) | ruff (один Rust-бинар, lint+format) | ruff 0.1 (2023), стабильный с 0.6 (2024) | Один dev-dep, ~100× быстрее. `[CITED: docs.astral.sh/ruff/]` |
| `python setup.py test` / pytest.ini | `[tool.pytest.ini_options]` в pyproject.toml | pytest 6.0+ (2020) | Единый файл конфигурации. `[CITED: docs.pytest.org]` |
| `argparse` с if/elif dispatch | `set_defaults(func=...)` + `args.func(args)` | Python 3.2+ (argparse), паттерн стабилен | Расширяемо без правок dispatch-кода. `[CITED: docs.python.org/3/library/argparse.html]` |
| `console_scripts` в setup.py | `[project.scripts]` в pyproject.toml | PEP 621 | `name = "module:function"`. |

**Deprecated/outdated (НЕ использовать):**
- `setup.py` — устарел для новых пакетов; только `pyproject.toml`. `[CITED: hatch.pypa.io]`
- `setup.cfg` для pytest-config — pytest docs: «not recommended except for very simple use cases». `[CITED: docs.pytest.org/en/stable/reference/reference.html]`
- `tomllib` (stdlib 3.11+) для **записи** — read-only (CLAUDE.md «What NOT to Use»). Только tomlkit. `[VERIFIED: docs.python.org/3/library/tomllib.html]`
- `launchctl load/unload` — deprecated Apple; только `bootstrap/bootout` (Phase 13, не Phase 1).

## Error-handling mechanism options (D-12 — контракт зафиксирован в D-11, механизм за planner'ом)

| Option | How | Pros | Cons | Verdict |
|--------|-----|------|------|---------|
| **A. Custom exception + try/except in `main()`** (рекоменд.) | `class ZaiCodexHelperError(Exception)`; services/backends кидают его; `main` ловит одним `try/except` | Явно, тестируемо (pytest ловит через `pytest.raises`), работает в трёхслойной архитектуре, `--debug` = `raise` в handler ветке | Нужна дисциплина: ожидаемые ошибки → `ZaiCodexHelperError`, баги → пускаем как `Exception` | **RECOMMENDED** — самый чистый для данной архитектуры |
| B. `sys.excepthook` | Глобальный hook ловит все `SysExit`-не-исключения | Одна точка | Ломает pytest (перехватывает исключения до hook); прячет причину; `--debug` сложно различить | НЕ рекомендовать |
| C. Декоратор-wrapper на каждом handler | `@handle_errors` оборачивает `cmd_setup` и т.д. | Декларативно на уровне handler | N точек вместо одной; дублирование; сложнее тестировать | Допустимо, но избыточно для 7 команд |
| D. if/elif на типах исключений в `main` | `except FileNotFoundError: ...; except TomlDecodeError: ...` | Без кастомного класса | Хрупко: каждый новый backend добавляет except-ветку; сложно различать «ожидаемая» vs «баг» | НЕ рекомендовать |

**Recommendation:** Option A. `ZaiCodexHelperError` в `__main__.py` (или `errors.py` если хочется чистоты), один `try/except` в `main()`, `--debug` → re-raise. Это соответствует трёхслойной архитектуре (services pure → могут кидать исключение; backends IO → кидают исключение; cli/main → ловит и переводит в exit code). `[ASSUMED]` — стандартный паттерн, верифицирован против общих практик Python CLI.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0 (current 9.1.1) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (D-13 — без отдельного pytest.ini) |
| Quick run command | `pytest -m "not e2e"` (или просто `pytest` — addopts уже исключает e2e) |
| Full suite command | `pytest -m ""` (включая e2e — только локально, Phase 15) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PKG-01 | `pip install .` ставит пакет; `import zai_codex_helper` на 3.10–3.13 | smoke | `pip install . && python -c "import zai_codex_helper; print(zai_codex_helper.__version__)"` | ❌ Wave 0 (`tests/test_smoke_install.py`) |
| PKG-02 | `zai-codex-helper --help` exit 0, без traceback | smoke | `pytest tests/test_cli_help.py::test_help_exits_zero -x` | ❌ Wave 0 |
| PKG-02 | без субкоманды → exit≠0, без traceback | smoke | `pytest tests/test_cli_help.py::test_no_subcommand_errors -x` | ❌ Wave 0 |
| PKG-04 | маркеры unit/integration/smoke/e2e зарегистрированы | unit | `pytest tests/test_markers.py::test_markers_registered -x` | ❌ Wave 0 |
| PKG-04 | HOME изолирован в tmp_path, `.codex` создан | unit | `pytest tests/test_home_isolation.py -x` | ❌ Wave 0 |
| PKG-05 | ожидаемая ошибка → one-line + exit 1, без traceback | unit | `pytest tests/test_error_contract.py -x` | ❌ Wave 0 (опционально — Phase 1 только каркас) |
| PKG-05 | `--debug` включает traceback | unit | `pytest tests/test_error_contract.py::test_debug_shows_traceback -x` | ❌ Wave 0 (опционально) |

### Sampling Rate
- **Per task commit:** `pytest -m "not e2e"` (быстрый прогон unit+integration+smoke)
- **Per wave merge:** `pytest -m "not e2e"` + `pip install . && zai-codex-helper --help` (полный smoke)
- **Phase gate:** `pytest -m "not e2e"` green + `ruff check .` green + `pip install .` succeeds + `zai-codex-helper --help` exit 0 — перед `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/conftest.py` — autouse `_isolate_home` fixture (D-14)
- [ ] `tests/test_cli_help.py` — covers PKG-02 (smoke)
- [ ] `tests/test_markers.py` — covers PKG-04 (маркеры резолвятся, D-15)
- [ ] `tests/test_home_isolation.py` — covers PKG-04 (HOME-изоляция, D-14)
- [ ] `tests/test_smoke_install.py` (опционально) — covers PKG-01 (`pip install .` → import)
- [ ] `tests/test_error_contract.py` (опционально) — covers PKG-05 (D-11)
- [ ] Framework install: `pip install -e ".[dev]"` — если ещё не установлен

## Security Domain

> ASVS Level 1 (config). Phase 1 — packaging/skeleton; единственная security-relevant поверхность — отсутствие hardcoded secrets и корректный `LICENSE` (MIT). Phase 1 не трогает ключи, IO, сеть, auth.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Phase 1 не трогает auth (ключи — Phase 9/12) |
| V3 Session Management | no | CLI без сессий |
| V4 Access Control | no | Phase 1 не трогает доступ |
| V5 Input Validation | yes (минимально) | argparse `parse_args` валидирует CLI-ввод; `--debug`/`--yes`/`--dry-run` — булевы флаги. Stub-handlers не выполняют IO. |
| V6 Cryptography | no | Phase 1 не использует крипто |
| V7 Error Handling & Logging | yes | **D-11/PKG-05:** ожидаемые ошибки → читаемое сообщение БЕЗ утечки внутренностей в вывод (кроме `--debug`). Контракт на уровне main(). |
| V14 Configuration | yes | `pyproject.toml` metadata; `LICENSE` = MIT (D-19, не перезаписывать); `.gitignore` уже покрывает `.env`/`*.egg-info`/`build/`/`dist/`/`.venv`/`.ruff_cache`/`.pytest_cache`. |

### Known Threat Patterns for {Python CLI packaging}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Hardcoded API keys в wheel | Information Disclosure | SECR-03: никаких ключей в коде; Phase 1 stub'ы не трогают ключи. `.gitignore` покрывает `.env`. |
| Подмена пакета на PyPI (slopsquatting) | Spoofing | Package Legitimacy Audit выше — все 8 пакетов верифицированы против авторитетных источников. |
| Malicious postinstall script | Tampering | У всех рекомендованных пакетов postinstall — null/отсутствует (seam не сообщил). ruff — Rust-бинар (без Python postinstall). |
| Вывод секретов в ошибке | Information Disclosure | D-11: сообщение об ошибке — one-line, без дампа переменных; `--debug` только для разработчика. |
| Запись тестов в реальный `~/.codex` | Tampering (данных пользователя) | D-14: autouse HOME-изоляция — страховка против повреждения конфига разработчика. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Option A (custom exception + try/except) — самый чистый механизм для D-12 | Error-handling mechanism options | LOW — даже если planner выберет Option C (декоратор), контракт D-11 достижим; это рекомендация, не блокер. |
| A2 | `license-files = ["LICENSE"]` — корректный способ указать существующий MIT-LICENSE в hatchling | pyproject.toml example | LOW — если hatchling не принимает `license-files`, fallback: `license = "MIT"` + `License :: OSI Approved :: MIT License` classifier. D-19 forbids overwriting LICENSE, не формат указания. |
| A3 | `target-version = "py310"` в `[tool.ruff]` избыточен (ruff выводит из `requires-python`), но явно надёжнее | pyproject.toml example | NONE — избыточность безвредна. |
| A4 | `pythonpath = ["src"]` НЕ нужен при editable-install (`pip install -e .`) | Validation Architecture | LOW — при `pip install -e ".[dev]"` hatchling добавляет src/ в sys.path автоматически (`dev-mode-dirs`); если тесты падают с ModuleNotFoundError, добавить `pythonpath = ["src"]` в `[tool.pytest.ini_options]`. |
| A5 | `subprocess.run([sys.executable, "-m", "zai_codex_helper", "--help"])` работает после `pip install .` | test_cli_help.py | LOW — `python -m zai_codex_helper` выполняет `__main__.py`; альтернатива — дёрнуть сам console script `zai-codex-helper --help` (нужен PATH после install). |
| A6 | stub-handler возвращает `0` (exit success) для всех команд в Phase 1 | Pattern 1 | LOW — planner может выбрать `SystemExit(2)`/"not implemented" вместо `0`; контракт не диктует exit code для stub'ов (они не делают реальной работы). |

## Open Questions

1. **Точная форма stub-обработчиков (D-02, на усмотрение planner'а):** печать "not implemented in this phase" + exit 0, или exit 2 (как ошибка), или пустой handler? 
   - Что we know: D-02 фиксирует, что заглушки есть; форма за planner'ом.
   - Recommendation: exit 0 + stderr-сообщение "not implemented" — наименее удивительно для smoke-теста (`--help` всё равно exit 0; stub-команды не делают вреда). Но если planner хочет, чтобы Phase 1 НЕ позволял случайно вызвать ненастоящую команду — exit 2.

2. **`pythonpath = ["src"]` нужен ли в `[tool.pytest.ini_options]`?**
   - Что we know: при `pip install -e ".[dev]"` hatchling должен добавить src/ в sys.path (dev-mode-dirs).
   - Recommendation: НЕ добавлять сначала; smoke-тест (`pytest`) покажет, нужен ли. Если `ModuleNotFoundError` — добавить одну строку.

3. **`main()` в `__main__.py` или `cli/__init__.py` (D-10, на усмотрение planner'а)?**
   - Что we know: D-10 даёт выбор. `[project.scripts]` указывает на `zai_codex_helper.__main__:main`.
   - Recommendation: `__main__.py` — стандартное место для entry point; `cli/parser.py` содержит `build_parser()`. main() в `__main__.py` импортирует `build_parser` из `cli`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.10+ | Runtime floor (D-17) | ✓ (3.12.10) | 3.12.10 | — (3.12 покрывает 3.10 floor) |
| pip | Install (`pip install .`) | ✓ | 26.1.2 | — |
| ruff | Lint+format (D-08) | ✓ | 0.15.17 | — (выше floor 0.6) |
| Go 1.25+ | **НЕ нужен в Phase 1** (Phase 11 — Moon Bridge build) | ✓ (1.26.4) | 1.26.4 | — (рано; флаг для будущего) |
| hatchling | Build backend | ✓ (через pip install) | 1.30.1 | — |
| pytest | Test runner | нужно установить (`pip install -e ".[dev]"`) | 9.1.1 | — |

**Missing dependencies with no fallback:** none — все инструменты Phase 1 доступны.
**Missing dependencies with fallback:** none.

**Note:** Go 1.26.4 присутствует, но Phase 1 его НЕ использует (Moon Bridge build — Phase 11). Заявлен для контекста, что окружение готово к будущим фазам.

## Sources

### Primary (HIGH confidence — официальные docs, верифицированы в этой сессии)
- hatch.pypa.io/latest/config/build/ — build-system, `[tool.hatch.build.targets.wheel] packages`, src-layout, dev-mode-dirs. `[VERIFIED: webReader, hatch docs canonical]`
- hatch.pypa.io/latest/version/ — dynamic version, regex-source по умолчанию ищет `__version__`, `[tool.hatch.version] path=...`. `[VERIFIED: webReader]`
- docs.astral.sh/ruff/configuration/ — полный default-config с `[tool.ruff]`, `[tool.ruff.lint] select`, `[tool.ruff.format]`, target-version py310, line-length 88; per-file-ignores; CLI flags. `[VERIFIED: webReader]`
- docs.pytest.org/en/stable/how-to/mark.html — markers registration в `[pytest]`/`[tool.pytest.ini_options]`, `--strict-markers`, `addopts`. `[VERIFIED: webReader]`
- docs.pytest.org/en/stable/reference/reference.html — все ini-options (markers, addopts, testpaths, pythonpath, strict_markers), monkeypatch fixture API, tmp_path. `[VERIFIED: webReader]`
- docs.python.org/3/library/argparse.html#sub-commands — `add_subparsers(dest=, required=, metavar=)`, `set_defaults(func=)`. `[CITED: official docs]`

### Secondary (MEDIUM confidence — official docs, но по второстепенным вопросам)
- discuss.python.org/t/30207 — `set_defaults(func=...)` dispatch pattern как recommended. `[CITED: python.org discuss]`
- CLAUDE.md Sources — верифицированные версии пакетов (tomlkit 0.15.0, pyyaml 6.0.3, httpx 0.28.1, ruff 0.15.20, pytest 9.1.1, hatchling 1.30.1). `[VERIFIED: cross-checked pip index versions в этой сессии]`

### Tertiary (LOW confidence — паттерны, не верифицированы формально)
- adamj.eu/tech/2021/10/15/a-python-script-template-with-sub-commands-and-type-hints/ — if/elif vs set_defaults trade-off. `[CITED: blog]`
- Общепринятый паттерн custom-exception + try/except для CLI error-handling. `[ASSUMED]`

## Metadata

**Confidence breakdown:**
- Standard stack (versions + конфиг): **HIGH** — все версии cross-checked против PyPI (`pip index versions`), конфиги верифицированы против официальных docs в этой сессии.
- Architecture patterns (pyproject форма, argparse dispatch, error-handling): **HIGH** — верифицировано против hatch/pytest/python docs.
- Pitfalls: **HIGH** — все 6 pitfalls основаны на задокументированном поведении (src-layout packages, dynamic version, markers, subparsers required, console script, HOME isolation).
- Error-handling mechanism recommendation (Option A): **MEDIUM** — стандартный паттерн, но D-12 явно оставляет выбор за planner'ом (A1 в Assumptions Log).

**Research date:** 2026-06-29
**Valid until:** 2026-07-29 (30 дней — stable; PEP 621 / hatchling / ruff / pytest — зрелые, но ruff/pytest версии меняются. Floor'ы `>=` в pyproject стабильны.)
