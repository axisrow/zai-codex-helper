# Phase 1: Project Skeleton & Packaging Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-29
**Phase:** 1-Project Skeleton & Packaging Foundation
**Areas discussed:** CLI framework, Rich/HTTP-mock dependencies, Architecture skeleton, Error handling/--debug, pytest harness, pyproject.toml metadata + formatter + CI

---

## CLI Framework

| Option | Description | Selected |
|--------|-------------|----------|
| Typer (как зафиксировано) | 7 подкоманд + Rich-вывод + нестандартные exit codes; снимает шаблонный код. Цена: ~3 транзитивных депенденси | |
| argparse (stdlib) | 0 зависимостей для CLI. Подкоманды + --help + Rich-таблицы потребуют шаблонного кода | ✓ |
| Click raw | Движок Typer напрямую, меньше слоёв, но тот же шаблонный код без типизации | |
| Начать с argparse, добавить Typer если понадобится | Минимальный CLI для вертикали Phase 7, Typer втягивается по необходимости | |

**User's choice:** argparse (stdlib)
**Notes:** Пользователь постановил, что Typer избыточен для данного приложения. Это **переопределяет** зафиксированный в `.claude/CLAUDE.md`/`PROJECT.md` выбор Typer (D-01 в CONTEXT.md). Скепсис к "избыточным" инструментам — сквозная тема обсуждения.

---

## Rich (вывод doctor/status)

| Option | Description | Selected |
|--------|-------------|----------|
| Без Rich — plain text | Цветные маркеры через ANSI-коды вручную. 0 зависимостей. Соответствует выбору argparse | ✓ |
| Rich как явная зависимость | rich>=13 для Panel/Table. Цена: 1 явная зависимость (Typer больше не тянет его транзитивно) | |

**User's choice:** Без Rich — plain text
**Notes:** Цветные маркеры `[✓]`/`[!]`/`[✗]` (DIAG-04, Phase 14) — через ANSI вручную. Переопределяет CLAUDE.md "Recommended Stack" (D-04).

---

## pytest-httpserver (HTTP mock)

| Option | Description | Selected |
|--------|-------------|----------|
| Отложить до Phase 14 | Не нужен в Phase 1 (тут нет HTTP). dev-deps минимальны до doctor | |
| Внести сразу | Реальный локальный HTTP-сервер в процессе (настоящие сокеты) для doctor-проб /v1/models и /v1/responses; код-путь теста = продакшн | ✓ |

**User's choice:** Внести сразу
**Notes:** Пользователь изначально усомнился ("не ясно зачем"). После пояснения, что `responses` патчит транспорт (код-путь ≠ продакшн), а pytest-httpserver даёт реальные сокеты — решил внести сразу, чтобы pyproject был полным.

---

## Architecture Skeleton (three-layer)

| Option | Description | Selected |
|--------|-------------|----------|
| Минимальный: только main() | Только __init__.py + __main__.py + main(). Пакеты слоёв появляются в своих фазах (YAGNI) | |
| Скелет трёх слоёв (пустые пакеты) | cli/ services/ backends/ — пустые __init__.py с docstring о роли слоя. Зафиксировать архитектурный контракт заранее | ✓ |
| Решит planner | В CONTEXT отметить three-layer как цель, раскладку файлов оставить planner'у | |

**User's choice:** Скелет трёх слоёв (пустые пакеты)
**Notes:** Архитектурный контракт (STATE.md three-layer) фиксируется в Phase 1, чтобы последующие фазы клали код в готовые места.

---

## Error Handling / --debug (PKG-05)

| Option | Description | Selected |
|--------|-------------|----------|
| Свой класс исключений + try/except в main() | ZaiCodexHelperError для ожидаемых; --debug перевыпускает | |
| sys.excepthook | Один раз переопределяем обработчик. Риски в тестах (глобален) | |
| Декоратор/wrapper команд | Централизованный try/except без классов | |
| Решит planner | Зафиксировать только контракт | ✓ |

**User's choice:** Решит planner
**Notes:** Зафиксирован контракт (D-11): ожидаемые ошибки → one-line + non-zero без traceback; `--debug` включает traceback. Механизм (D-12) — на усмотрение planner'а.

---

## pytest Harness (PKG-04)

### Маркеры тестов

| Option | Description | Selected |
|--------|-------------|----------|
| В pyproject.toml [tool.pytest] | Единый файл конфигурации, современная практика | ✓ |
| Отдельный pytest.ini | Проще найти глазами, но ещё один файл | |
| Решит planner | Зафиксировать только набор маркеров | |

**User's choice:** В pyproject.toml [tool.pytest.ini_options]

### HOME-изоляция

| Option | Description | Selected |
|--------|-------------|----------|
| autouse фикстура | Железная защита: даже кривой тест не тронет реальный ~/.codex. Соответствует идеологии "не испортить файлы" | ✓ |
| Shared explicit home_env | Явный: тест запрашивает home_env(tmp_path). DRY, но если забыл — попадёт в реальный HOME | |
| Per-test monkeypatch | Максимально явный, но шаблонный код, легко забыть | |

**User's choice:** autouse фикстура (после консультации)
**Notes:** Пользователь изначально ответил "Я не знаю, тут нужна консультация". После разбора (autouse = страховка от человеческой ошибки, соответствует идеологии проекта; Phase 2 введёт Paths.from_home как основной механизм) выбрал autouse (D-14).

### Что закладывать в Phase 1

| Option | Description | Selected |
|--------|-------------|----------|
| Smoke-тест --help + регистрация маркеров | Покрыть success criteria 1 и 3 Phase 1 | ✓ |
| Решит executor | Голый pytest с маркерами, конкретные тесты — executor | |

**User's choice:** Smoke-тест --help + регистрация маркеров

---

## pyproject.toml + formatter + CI

### Форматтер/линтер

| Option | Description | Selected |
|--------|-------------|----------|
| ruff (линтер+форматтер) | Один инструмент, заменяет black+flake8+isort. Конфиг [tool.ruff] | ✓ |
| black + ruff | ruff только линтер, black форматтер. 2 инструмента | |
| Без форматтера | Минимализм, добавить позже | |
| Решит planner | | |

**User's choice:** ruff (линтер+форматтер) (D-08)

### Управление версией

| Option | Description | Selected |
|--------|-------------|----------|
| Динамическая (hatch.version из __init__.py) | Единый источник правды; версия доступна из кода для status (PROV-05) | ✓ |
| Статическая в pyproject | Проще, но версия не читается из кода без парсинга | |

**User's choice:** Динамическая (hatch.version из __init__.py) (D-16)

### CI

| Option | Description | Selected |
|--------|-------------|----------|
| Базовый CI (install + --help) в Phase 1 | Покрыть success criteria 1 и 2 сразу | |
| CI отложен до Phase 15 | Phase 1 доставляет только локальный pytest-harness | ✓ |
| Решит planner | | |

**User's choice:** CI отложен до Phase 15 (D-20)

### Classifiers / requires-python / платформа

| Option | Description | Selected |
|--------|-------------|----------|
| macOS-only classifiers, requires-python>=3.10 | Soft: classifier сигнализирует платформу, но Linux работает (Docker-тесты, будущий CI) | ✓ |
| Жёсткий macOS-only (hard block) | platform-specific marker блокирует pip install на Linux/Windows | |
| Решит planner | | |

**User's choice:** macOS-only classifiers, requires-python>=3.10 (D-17, D-18)

### Лицензия

**User's choice:** MIT
**Notes:** Проверен существующий `LICENSE` — уже MIT (Copyright (c) 2026 axisrow). Не перезаписывать. GPL v3 касается только Moon Bridge (отдельный Go-бинарник, не вендорится) — MIT-пакет вызывает его как subprocess, конфликта нет (D-19).

---

## Claude's Discretion

- Точная раскладка модулей внутри cli//services//backends/ (при условии трёхслойного контракта D-09)
- Форма заглушек subcommands в Phase 1
- Механизм обработки ошибок (контракт в D-11, реализация свободна)
- Конкретные [tool.ruff] правила
- Структура conftest.py (при условии autouse HOME-изоляции D-14)
- Объявлять ли runtime-зависимости (tomlkit/pyyaml/httpx) сразу или по фазам (рекомендация — сразу)

---

## Deferred Ideas

- **Обновить PROJECT.md / CLAUDE.md "Technology Stack"** — зафиксированные там Typer и Rich переопределены (D-01 argparse, D-04 без Rich). Рассинхронизация: PROJECT.md Key Decisions помечены "Pending", CLAUDE.md — OVERRIDING. Действие после фазы: привести к канону до/во время Phase 2, чтобы последующие фазы читали согласованный стек.
- Rich-вывод для doctor/status — если plain-text окажется неудобочитаемым в Phase 8/14, можно пересмотреть.
- CI-конфигурация (GitHub Actions matrix Python 3.10–3.13) — Phase 15 (TEST-05).
- Реальные handler'ы subcommands — каждая команда в своей фазе.
