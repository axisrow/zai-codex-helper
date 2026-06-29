# zai-codex-helper

## What This Is

`zai-codex-helper` — это pip-installable Python CLI для macOS, который управляет связкой **Codex ⇄ Moon Bridge ⇄ Z.ai** без ручного редактирования `~/.codex/config.toml`, `~/.zshrc` и `moonbridge-zai.yml`. Позволяет одной командой переключать дефолтный провайдер Codex (CLI и Desktop App) между Z.ai (`glm-5.2 xhigh`) и OpenAI, и обратно. Предназначен для разработчиков, использующих Codex вместе с моделями Z.ai.

## Core Value

Пользователь может **одной командой** (`zai-codex-helper use zai`) сделать Z.ai дефолтным провайдером Codex CLI и Desktop App, и одной командой (`use openai`) вернуть OpenAI — без ручной правки TOML/YAML/shell-файлов. Если это работает, всё остальное вторично.

## Business Context

- **Customer**: Разработчики, использующие Codex (CLI/Desktop) вместе с Z.ai GLM-моделями
- **Revenue model**: Open-source, бесплатно (PyPI)
- **Success metric**: Пакет публикуется в PyPI, `setup` → `use zai` → Codex отвечает через Z.ai «из коробки» на macOS
- **Strategy notes**: Автоматизация уже работающей у автора ручной конфигурации

## Requirements

### Validated

<!-- Ручная CLI-настройка уже работает у автора — это валидированный baseline. -->

- ✓ Связка Codex CLI ⇄ Moon Bridge ⇄ Z.ai работает вручную — existing (CLI only)
- ✓ Moon Bridge слушает `127.0.0.1:38440` и проксирует запросы в Z.ai upstream — existing
- ✓ `codex exec` через профиль `zai-glm` отвечает на `glm-5.2 xhigh` — existing
- ✓ pip-installable пакет `zai-codex-helper` с CLI entrypoint (Python 3.10+, `pyproject.toml` + hatchling, src-layout, dynamic version, console script `zai-codex-helper`) — Validated in Phase 1: Project Skeleton & Packaging Foundation (PKG-01/02). Команды пока stab'ы, реальная логика в последующих фазах.
- ✓ Инъектируемый frozen `Paths` объект (`Paths.from_home`/`Paths.default`, 7 путей через один injected home) — Validated in Phase 2: Injectable Paths Object (PKG-03). Тесты провалируемо не трогают реальный `$HOME`.
- ✓ Atomic-write helper (`atomic_write(path, data, mode=None)`: temp+fsync+os.replace, `0600` для секретов) — Validated in Phase 3: Atomic Write Helper (CONF-01). Единственный механизм записи для всех будущих backends.
- ✓ BackupCoordinator (sentinel-gated one-shot `.bak`) + `ConfigBackend` ABC (read/exists/write_canonical/backup_once) + `restore` CLI (первая реальная команда) — Validated in Phase 4: Backup Coordinator & ConfigBackend ABC (CONF-03/CONF-04). `ZaiCodexHelperError` поднят в `errors.py` (фикс D-11 identity-сплита под `python -m`).
- ✓ `TomlBackend` (config.toml через tomlkit, lossless round-trip: комментарии + порядок ключей + `[project_*]` trust-блоки выживают) + `upsert_block` (replace-not-append) — Validated in Phase 5: TomlBackend (CONF-02). Load-bearing фаза проекта — byte-identical round-trip доказан. *Tech debt: atomic_write(mode=None) не сохраняет режим (os.replace) — D-DEFERRED-01, для Phase 3/9.*
- ✓ Canonical desired-state transforms `apply_zai`/`apply_openai` (pure, exact-inverse, idempotent; `wire_api="responses"` на `zai-moonbridge`; flat `model_reasoning_effort`) + `check_postconditions` (reserved-id/provider/base_url) — Validated in Phase 6: Canonical Templates & Provider Transforms (PROV-03/CONF-05). Семантическое ядро продукта.
- ✓ **CORE VALUE ДОСТАВЛЕН** — `zai-codex-helper use zai` делает Z.ai дефолтом (`glm-5.2`/`zai-moonbridge`/`xhigh`/`wire_api=responses`), `use openai` возвращает OpenAI (`gpt-5.5`, Z.ai-блок сохранён). Restart warning на stderr. Идемпотентно (byte-identical). — Validated in Phase 7: CLI use zai / use openai (PROV-01/02/04, CONF-06). Доказано end-to-end через subprocess против throwaway HOME.
- ✓ `zai-codex-helper status` (read-only: текущий провайдер + 5 config-путей + версия; доказано не мутирует — snapshot byte-identical до/после; missing≠broken) — Validated in Phase 8: CLI status (PROV-05).

### Active

<!-- Текущий скоуп v1. Гипотезы до публикации и валидации. -->

- [ ] Команды: `setup`, `use zai`, `use openai`, `status`, `doctor`, `install-service`, `uninstall-service`
- [ ] `setup` — интерактивный онбординг (default provider, shell helpers, LaunchAgent, установка/настройка Moon Bridge)
- [ ] `use zai` выставляет Z.ai дефолтом в `~/.codex/config.toml` (`glm-5.2`, `zai-moonbridge`, `xhigh`)
- [ ] `use openai` возвращает OpenAI дефолтом (`gpt-5.5`), Z.ai-блок сохраняется
- [ ] Desktop App наследует дефолт из `config.toml` (новая Terra — не настроено вручную)
- [ ] `doctor` — диагностика всей цепочки (binary, порт, `/v1/models`, `/v1/responses`, models_cache, текущий дефолт)
- [ ] `install-service`/`uninstall-service` — macOS LaunchAgent для автозапуска Moon Bridge
- [ ] Обновление `models_cache.json` записью `glm-5.2` (убирает warning о missing model metadata)
- [ ] Бэкап конфигов: один раз на пользователя при первом изменении (не на каждый запуск)
- [ ] Никаких захардкоженных ключей — только интерактивный ввод / `ZAI_API_KEY` из окружения, права `0600`
- [ ] Полный набор тестов: unit, integration, smoke (CI) + e2e (локально, вне CI), TDD-подход

### Out of Scope

- **Windows** — нативная поддержка не планируется (Out of Scope)
- **Linux нативный systemd-сервис** — не делаем; Linux покрыт через Docker только для тестирования (см. Constraints)
- **Desktop App acceptance как автотест** — restart Codex Desktop и визуальная проверка `glm-5.2 xhigh` остаются мануальным чек-листом приёмки
- **e2e-тесты в CI** — требуют живого `ZAI_API_KEY` + запущенного Moon Bridge; прогоняются локально автором перед релизом
- **«Обнаружить и синхронизировать» существующие настройки** — `setup` всегда приводит файлы к каноничному виду (с бэкапом), а не пытается мержить
- **Бэкап перед каждым изменением** — устаревший пункт из исходного issue; заменён на «один раз на пользователя»

## Context

- **CLI уже работает вручную у автора** — целевое состояние файлов (`config.toml`, `moonbridge-zai.yml`, `.zshrc`, `models_cache.json`), команды, ключи и пути известны из практики. Это сильно снижает риск проектирования.
- **Desktop App — новая Terra:** ручная настройка через `config.toml` для Desktop App ещё не проверена. Требует отдельной acceptance-проверки (restart Desktop, новый thread показывает `glm-5.2 xhigh`, нет warning'а о model metadata).
- **Moon Bridge:** слушает `127.0.0.1:38440`, `server.auth_token` удаляется (локальный слушатель не требует `MOONBRIDGE_API_KEY`), `codex_tool_proxy.enabled = true`, upstream `https://api.z.ai/api/coding/paas/v4/chat/completions`.
- **Установка Moon Bridge:** скорее готовый бинарник, но нужен research доступных опций (релизные бинарники с GitHub, `~/.codex/moon-bridge`, сборка из Go-исходников как фоллбэк).
- **Зависимость от Go:** если Moon Bridge требует сборки — проверяем Go на машине пользователя. Нет Go → предлагаем `brew install go`; нет brew → предлагаем установить brew. Если найден готовый бинарник — Go не нужен.
- **Тестирование:** TDD. Слои — unit (патч TOML/YAML, идемпотентность, бэкап — tmp/mocks), integration (запись во временный `HOME`, `doctor` против фейк-сервиса Moon Bridge), smoke (полный `setup → doctor` без вызова модели), e2e (живой `codex exec` через Z.ai, локально).
- **Docker:** используется только для воспроизводимого прогона тестов; для финального пользователя не требуется, не является опцией пакета и не входит в зависимости.
- **CLI-стек (Phase 1):** `argparse` (stdlib) вместо Typer; без Rich (plain text); ruff как линтер+форматтер. См. Key Decisions и `01-CONTEXT.md`. Подробный prescriptive-stack в `.claude/CLAUDE.md` обновлён соответственно.

## Constraints

- **Платформа**: macOS — основная и единственная поддерживаемая платформа v1 (LaunchAgent, `~/Library/LaunchAgents/`, `.zshrc`) — пользователи на macOS
- **Python**: 3.10+ (минимальная поддерживаемая версия)
- **Упаковка**: `pyproject.toml` + hatchling (стандартный современный стек)
- **Linux**: только через Docker для тестирования; нативная поддержка out of scope
- **Windows**: out of scope
- **CI**: прогоняет unit + integration + smoke; e2e прогоняется локально автором (требует живого ключа и сервиса)
- **Безопасность**: никаких захардкоженных ключей в пакете; ключ пользователя хранится с правами `0600`
- **Идемпотентность**: повторный `setup` даёт тот же результат поверх существующего; бэкап — один раз на пользователя
- **Сохранение структуры**: `tomlkit` для `config.toml` (сохраняет project trust blocks и комментарии), `PyYAML` для `moonbridge-zai.yml`

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Имя пакета `zai-codex-helper` (не `codex-zai-config` из issue) | Пользовательское именование; issue #1 содержит устаревшее имя | — Pending |
| `setup` = перезапись по шаблону, не мерж | «Обнаружить и синхронизировать» неосмысленно для того, чего ещё нет; простейший честный вариант — привести к каноничному виду | — Pending |
| Бэкап один раз на пользователя (не на каждое изменение) | Страховка пользовательских настроек; исходный пункт issue («перед каждым изменением») устарел | — Pending |
| hatchling + `pyproject.toml` | Современный стандарт упаковки; доверенный автору выбор | — Pending |
| **CLI на `argparse` (stdlib), НЕ Typer** | Пользователь постановил, что Typer избыточен; предпочтение нулевых/минимальных зависимостей. Переопределяет изначально предложенный Typer | Decided (Phase 1 CONTEXT D-01) |
| **Без Rich — plain text** | Раз Typer убран, Rich больше не приходит транзитивно; цветные маркеры `doctor` (DIAG-04) через ANSI-коды вручную. Переопределяет изначально предложенный Rich | Decided (Phase 1 CONTEXT D-04) |
| **ruff (линтер+форматтер в одном)** | Заменяет black+flake8+isort одним инструментом; один dev-dep вместо трёх | Decided (Phase 1 CONTEXT D-08) |
| **Динамическая версия через hatch.version** | Единый источник правды: `__version__` в `__init__.py` читается и кодом (`status`/PROV-05), и метаданными пакета | Decided (Phase 1 CONTEXT D-16) |
| **CI отложен до Phase 15** | Phase 1 доставляет только локальный pytest-harness; полный CI-matrix (Python 3.10–3.13) — Phase 15 (TEST-05) | Decided (Phase 1 CONTEXT D-20) |
| **Soft macOS-only classifiers** | Classifier сигнализирует macOS, но без hard platform-block (Linux нужен для Docker-тестов и будущего CI) | Decided (Phase 1 CONTEXT D-18) |
| **Three-layer каркас закладывается в Phase 1** | Пустые пакеты `cli/` `services/` `backends/` с docstring; архитектурный контракт фиксируется заранее | Decided (Phase 1 CONTEXT D-09) |
| TDD + 4 слоя тестов; e2e вне CI | Покрытие без хрупких живых вызовов в публичном CI | — Pending |
| Docker только для тестов, не для пользователя | Воспроизводимость тестов; нулевая нагрузка на финального пользователя | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-29 after Phase 2 completion — frozen `Paths` dataclass delivered (PKG-03 verified); Paths requirement moved to Validated*
