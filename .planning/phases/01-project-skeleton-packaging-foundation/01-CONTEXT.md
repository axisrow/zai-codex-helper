# Phase 1: Project Skeleton & Packaging Foundation - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Фаза 1 доставляет **импортируемый Python-пакет `zai-codex-helper`** с:
- `pyproject.toml` (hatchling, src/-layout, PEP 621), устанавливаемый через `pip install .`
- console-script entry point `zai-codex-helper`, для которого `zai-codex-helper --help` печатает usage без traceback
- argparse-based CLI с одним корневым парсером и заглушками subcommands (без реальной логики — логика приходит в последующих фазах)
- архитектурный каркас трёх слоёв (`cli/`, `services/`, `backends/`) — пустые пакеты с docstring о роли слоя
- pytest-harness: маркеры `unit`/`integration`/`smoke`/`e2e`, autouse-фикстура HOME-изоляции, smoke-тест `--help`

**НЕ входит в Phase 1:** реальная логика команд (Paths — Phase 2, atomic write — Phase 3, TomlBackend — Phase 5, transforms/use — Phase 6/7 и т.д.), CI-конфигурация (Phase 15), Rich-вывод (Phase 8/14), HTTP-пробы doctor (Phase 14). Фаза 1 — фундамент: пакет ставится, импортируется, `--help` работает, тесты изолированы от реального `~/.codex`.

</domain>

<decisions>
## Implementation Decisions

### CLI Framework — argparse, НЕ Typer (OVERRIDE)
- **D-01 (OVERRIDE):** CLI строится на **stdlib `argparse`**, а не на Typer. Это **осознанное переопределение** зафиксированного в `.claude/CLAUDE.md` / `PROJECT.md` выбора Typer. Пользователь на обсуждении постановил, что Typer избыточен для данного приложения. Решение окончательное — downstream-агенты НЕ должны возвращать Typer.
- **D-02:** Корневой парсер `argparse.ArgumentParser(prog="zai-codex-helper")` + subparsers для будущих команд (`setup`, `use`, `status`, `doctor`, `install-service`, `uninstall-service`). В Phase 1 subparsers регистрируются как заглушки (минимальные `add_parser` без реальных handler'ов или с handler'ами, печатающими "not implemented in this phase"). Конкретную форму заглушек решает planner.
- **D-03:** `use zai` / `use openai` — две субкоманды под общим парсером `use` (или два отдельных subparser'а) — точную раскладку решает planner, но паттерн должен быть готов принять аргументы в будущем.

### Rich — НЕ используем (plain text)
- **D-04:** **Без Rich.** Вывод `doctor`/`status` (появятся в Phase 8/14) — plain text. Поскольку Typer убран, Rich больше не приходит «бесплатно», и проект выбирает нулевую зависимость для оформления вывода.
- **D-05:** Цветные маркеры `[✓]`/`[!]`/`[✗]` (требование DIAG-04, Phase 14) реализуются через **ANSI-коды вручную** (stdlib), а не через Rich. Phase 1 это не касается — фиксируется как контракт для будущего.

### Dependencies (runtime + dev)
- **D-06 (runtime deps для Phase 1):** Phase 1 не требует runtime-зависимостей для своего функционала (argparse/plistlib/subprocess — stdlib). tomlkit/pyyaml/httpx нужны реальной логике (Phase 5/9/14) — planner решает, объявить ли их в `pyproject.toml [project] dependencies` сразу или по мере фаз. Рекомендация: объявить сразу (пакет публикуется на PyPI в конце milestone), но не импортировать в Phase 1.
- **D-07 (dev deps):** `pytest>=8.0`, `pytest-httpserver>=1.1`, `build`, `hatchling>=1.21`, `ruff>=0.6`. pytest-httpserver вносится **сразу, несмотря на то что нужен только в Phase 14** (doctor делает реальные HTTP-пробы к Moon Bridge через настоящие сокеты; `responses` патчит транспорт — код-путь теста отличался бы от продакшна).
- **D-08:** **ruff** (линтер + форматтер в одном инструменте, заменяет black + flake8 + isort) в dev-зависимостях. Конфиг в `[tool.ruff]` в `pyproject.toml`.

### Architecture Skeleton (three-layer)
- **D-09:** В Phase 1 закладывается **скелет трёх слоёв** — пустые пакеты с docstring о роли слоя:
  - `src/zai_codex_helper/cli/` — слой команд (argparse handlers; точка входа пользователя)
  - `src/zai_codex_helper/services/` — чистые доменные сервисы (pure functions: desired-state computation, transforms — без побочных эффектов)
  - `src/zai_codex_helper/backends/` — file backends (TomlBackend, YamlBackend, JsonBackend, ShellBackend, PlistBackend — все за `ConfigBackend` ABC, приходят в своих фазах)
- **D-10:** Точку входа `main()` вынести в `src/zai_codex_helper/__main__.py` (или модуль `cli/__init__.py`) — точное место решает planner. Console script `[project.scripts] zai-codex-helper = "zai_codex_helper.__main__:main"` (или эквивалент).

### Error Handling (PKG-05) — контракт, механизм за planner'ом
- **D-11 (КОНТРАКТ):** Ожидаемые ошибки (файл не найден, TOML невалиден, провайдер не резолвится, ключ отсутствует) → **читаемое one-line сообщение + non-zero exit code, без traceback**. `--debug` включает полный traceback. Неожидаемые ошибки (настоящие баги) показывают traceback (точное поведение — за planner'ом).
- **D-12 (механизм — на усмотрение planner'а):** Planner выбирает механизм: собственный класс исключений `ZaiCodexHelperError` + `try/except` в `main()`, `sys.excepthook`, или декоратор-wrapper. Зафиксирован только контракт (D-11), а не реализация.

### pytest Harness (PKG-04)
- **D-13:** Маркеры тестов `unit`/`integration`/`smoke`/`e2e` регистрируются в **`pyproject.toml [tool.pytest.ini_options]`** (единый файл конфигурации, без отдельного `pytest.ini`).
- **D-14:** **HOME-изоляция через autouse-фикстуру** в `conftest.py` — ВСЕ тесты (включая unit) изолируются от реального `$HOME` автоматически (выставляет `HOME=tmp_path`, создаёт `tmp_path/.codex`). Железная страховка от случайной записи в реальный `~/.codex`. Phase 2 введёт `Paths.from_home(home)` как **основной** механизм изоляции (через него проходит весь prod-код); autouse остаётся вторичной страховкой.
- **D-15:** В Phase 1 закладывается: smoke-тест (`pip install .` → `zai-codex-helper --help` печатает usage, exit 0) + один тест, что маркеры резолвятся. e2e-маркер с реальным `codex exec` — Phase 15.

### pyproject.toml metadata
- **D-16 (версия):** **Динамическая версия.** `__version__ = "0.1.0"` в `src/zai_codex_helper/__init__.py`; в `pyproject.toml`: `dynamic = ["version"]` + `[tool.hatch.version] path = "src/zai_codex_helper/__init__.py"`. Единый источник правды (версия доступна и из кода для `status`/PROV-05 в Phase 8, и из метаданных пакета).
- **D-17 (Python floor):** `requires-python = ">=3.10"`. Classifiers: `Programming Language :: Python :: 3.10/3.11/3.12/3.13`.
- **D-18 (платформа):** **Soft macOS-only** — classifier `Operating System :: MacOS :: MacOS X` сигнализирует платформу, но **БЕЗ hard platform-block** (Environment markers в dependencies). Обоснование: Linux нужен для Docker-тестирования; жёсткий блок помешал бы будущему CI и Docker. Нативная Linux-поддержка остаётся out of scope — macOS-only обеспечивается поведением команд (LaunchAgent/.zshrc), а не метаданными пакета.
- **D-19 (лицензия):** **MIT** (`License :: OSI Approved :: MIT License`). Файл `LICENSE` уже существует (MIT, Copyright (c) 2026 axisrow) — НЕ перезаписывать. MIT корректен для Python-хелпера; GPL v3 касается только Moon Bridge (отдельный Go-бинарник, билдится из исходников, НЕ вендорится в wheel) — MIT-пакет вызывает его как subprocess, конфликта лицензий нет.
- **D-20 (CI):** **CI отложен до Phase 15.** Phase 1 доставляет только локальный pytest-harness. Установка пакета и `--help` проверяются локально (smoke-тест), но не на CI-matrix. Полный CI (unit+integration+smoke gate, Python 3.10–3.13) — Phase 15 (TEST-05).

### Claude's Discretion
- Точная раскладка модулей внутри `cli/`/`services/`/`backends/` (один модуль vs подпакеты) — за planner'ом, при условии соблюдения трёхслойного контракта (D-09).
- Форма заглушек subcommands в Phase 1 (печать "not implemented" vs `SystemExit(2)` vs пустой handler) — за planner'ом.
- Механизм обработки ошибок (D-12) — за planner'ом, контракт в D-11.
- Конкретные `[tool.ruff]` правила (target Python version, line-length, включённые/выключенные правила) — за planner'ом.
- Структура conftest.py (один корневой или вложенные) — за planner'ом, при условии autouse HOME-изоляции (D-14).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project foundation (stack + constraints)
- `.planning/PROJECT.md` — Core Value, Constraints (macOS-only, Python 3.10+, hatchling+pyproject), Key Decisions table. **ВНИМАНИЕ:** "Technology Stack" / Key Decisions там зафиксированы Typer и Rich — эти пункты **переопределены** решениями D-01/D-04 выше (argparse, без Rich). При конфликте CONTEXT.md Phase 1 имеет приоритет для этой фазы; рассинхронизацию с PROJECT.md/CLAUDE.md нужно устранить (см. Deferred — обновить PROJECT.md после фазы).
- `.planning/REQUIREMENTS.md` — Phase 1 покрывает **PKG-01, PKG-02, PKG-04, PKG-05** (см. Traceability). PKG-03 (Paths) — Phase 2, не Phase 1.
- `.claude/CLAUDE.md` — OVERRIDING инструкции проекта. **ВНИМАНИЕ:** разделы "Technology Stack", "What NOT to Use", "Stack Patterns" зафиксировали Typer/Rich/pytest-httpserver. D-01 переопределяет Typer→argparse, D-04 переопределяет Rich→plain-text. pytest-httpserver остаётся (D-07). Это рассинхронизация, которую надо задокументировать.

### Roadmap
- `.planning/ROADMAP.md` §"Phase 1: Project Skeleton & Packaging Foundation" — Goal, Success Criteria (4 пункта), Requirements mapping. **Phase 1 Goal:** developer/CI может `pip install .` → `zai-codex-helper --help`, и каждый последующий компонент юнит-тестируется через tier-marked pytest с tmp-HOME fixtures.
- `.planning/STATE.md` — three-layer архитектура (CLI → pure domain services → file backends) как "compiler whose target is the user's filesystem"; tomlkit как load-bearing зависимость.

### Existing repo files (greenfield — но уже есть)
- `LICENSE` — уже MIT (Copyright (c) 2026 axisrow). D-19: НЕ перезаписывать, использовать как есть.
- `.gitignore` — уже покрывает `.env`, `*.egg-info`, `build/`, `dist/`, `.pytest_cache/`, `.venv`, `.ruff_cache/`. **Не требует правок** для Phase 1 (но planner должен проверить покрытие `auth.json`/`*.env` для будущего — SECR-03/Phase 15).
- `README.md` — заглушка (`# zai-codex-helper`). Обновление README — не обязательно в Phase 1, но желательно краткое описание для `--help`/pip.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Зелёное поле.** Исходного кода Python в репо нет (`src/` отсутствует). Только `.gitignore`, `LICENSE`, `README.md`, `.planning/`, `.claude/`, `.codex/`. Нечего переиспользовать — Phase 1 создаёт всё с нуля.
- `.gitignore` — уже готовый стандартный Python-template (включая ruff/pytest/venv/build) — не дублировать.

### Established Patterns
- **Three-layer architecture** (из STATE.md): CLI → pure domain services → file backends. Phase 1 закладывает этот контракт в структуру пакетов (D-09), даже если сами слои пока пусты. Это архитектурный якорь для всех 15 фаз.
- **"Compiler whose target is the user's filesystem"** (из STATE.md) — desired-state вычисляется декларативно, применяется как атомарные мутации файлов. Phase 1 пока не вычисляет и не применяет ничего, но каркас должен это предвосхищать (services/ = pure, backends/ = IO).

### Integration Points
- `src/zai_codex_helper/__main__.py:main()` → точка входа, вызывается console script `zai-codex-helper` (Phase 7+ подключит сюда реальную логику `use zai`/`use openai`).
- `tests/conftest.py` autouse-фикстура → изоляция HOME (Phase 2 подключит сюда `Paths.from_home(home)`).
- `pyproject.toml [project.scripts]` → `zai-codex-helper` console script.

</code_context>

<specifics>
## Specific Ideas

- Пользователь ценит **минимализм и нулевые/минимальные зависимости** — отсюда argparse вместо Typer, plain-text вместо Rich, ruff (один инструмент) вместо black+flake8+isort. downstream-агенты должны тяготеть к stdlib и избегать зависимостей там, где stdlib достаточен.
- **Идеология проекта — "не испортить пользователю файлы"** — autouse HOME-изоляция (D-14) выбрана именно как воплощение этой идеологии в тестах: даже кривой тест не должен коснуться реального `~/.codex`.
- Пользователь выразил скепсис к "избыточным" инструментам (Typer, вопросы про pytest-httpserver) — при планировании обосновывать каждую зависимость её конкретной ролью.

</specifics>

<deferred>
## Deferred Ideas

- **Обновить PROJECT.md / CLAUDE.md "Technology Stack"** — зафиксированные там Typer и Rich переопределены решениями D-01 (argparse) и D-04 (без Rich) в этой фазе. Это рассинхронизация: PROJECT.md Key Decisions помечены "Pending", CLAUDE.md — OVERRIDING. **Действие после фазы:** обновить PROJECT.md Key Decisions и `.claude/CLAUDE.md` Technology Stack, чтобы зафиксировать argparse/plain-text как новый канон. Не блокирует Phase 1, но должно быть сделано до/во время Phase 2, чтобы последующие фазы читали согласованный стек.
- **Rich-вывод для doctor/status** (Panel/Table, цветные маркеры) — отложен; если plain-text окажется неудобочитаемым при реализации Phase 8/14, можно пересмотреть добавление Rich как явной зависимости.
- **CI-конфигурация (GitHub Actions matrix Python 3.10–3.13)** — Phase 15 (TEST-05).
- **Реальные handler'ы subcommands** — каждая команда в своей фазе (setup=12, use=7, status=8, doctor=14, install-service/uninstall-service=13).

</deferred>

---

*Phase: 1-Project Skeleton & Packaging Foundation*
*Context gathered: 2026-06-29*
