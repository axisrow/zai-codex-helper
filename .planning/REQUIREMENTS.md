# Requirements: zai-codex-helper

**Defined:** 2026-06-29
**Core Value:** Пользователь может одной командой (`use zai`) сделать Z.ai дефолтным провайдером Codex и одной командой (`use openai`) вернуть OpenAI — без ручной правки TOML/YAML/shell-файлов.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Packaging & Foundation

- [x] **PKG-01**: Пакет `zai-codex-helper` устанавливается через pip (Python 3.10+, `pyproject.toml` + hatchling, src/-layout)
- [x] **PKG-02**: CLI entrypoint `zai-codex-helper` доступен после установки как console script
- [x] **PKG-03**: Инъектируемый объект `Paths` определяет все пути (`~/.codex/*`, `~/.zshrc`, `~/Library/LaunchAgents/`) — тесты не трогают реальный HOME
- [x] **PKG-04**: pytest с маркерами tier-ов (unit/integration/smoke/e2e), фикстуры `tmp_path` + `monkeypatch.setenv('HOME')`
- [x] **PKG-05**: Читаемые ошибки без traceback (если не `--debug`), корректные exit codes

### Config Patching & Safety

- [x] **CONF-01**: Atomic write для всех мутаций (temp + fsync + os.replace), `0600` для секретов
- [x] **CONF-02**: Патч `config.toml` через tomlkit — сохраняет комментарии, порядок ключей и Codex project trust blocks на round-trip
- [x] **CONF-03**: Бэкап конфигов один раз на пользователя (sentinel-gated; повторный запуск не дублирует бэкап, если уже есть)
- [x] **CONF-04**: `restore` команда — откат к последнему бэкапу
- [x] **CONF-05**: Post-condition проверки после записи (provider resolves, has `base_url`, no reserved id redefined)
- [x] **CONF-06**: Идемпотентность — повторный `setup`/`use` даёт byte-идентичный результат (upsert, не append)
- [ ] **CONF-07**: `--dry-run` / diff preview перед изменением `~/.codex` и `~/.zshrc`

### Provider Switching (Core Value)

- [x] **PROV-01**: `use zai` выставляет Z.ai дефолтом в `~/.codex/config.toml` (`model = "glm-5.2"`, `model_provider = "zai-moonbridge"`, `model_reasoning_effort = "xhigh"`)
- [x] **PROV-02**: `use openai` возвращает OpenAI дефолтом (`model = "gpt-5.5"`, `model_provider` убирается/reverts к `openai`), Z.ai provider block сохраняется (обратимо)
- [x] **PROV-03**: Canonical-значение `wire_api = "responses"` закреплено для провайдера `zai-moonbridge` (Codex шлёт Responses API → Moon Bridge конвертит в Chat → Z.ai)
- [x] **PROV-04**: Предупреждение о необходимости рестарта Codex Desktop App после каждой записи (Desktop не live-reload'ит config.toml)
- [x] **PROV-05**: `status` — read-only сводка: текущий дефолтный провайдер, пути к конфигам, версия пакета

### Secrets

- [ ] **SECR-01**: `ZAI_API_KEY` читается из env или вводится интерактивно (never echoed)
- [x] **SECR-02**: Ключ хранится в `~/.codex/moonbridge-zai.yml` с правами `0600`
- [ ] **SECR-03**: Никаких захардкоженных ключей в пакете; ключи не логируются и не попадают в git

### Diagnostics (`doctor`)

- [ ] **DIAG-01**: `doctor` проверяет всю цепочку: Moon Bridge binary → `moonbridge-zai.yml` parseable → порт `127.0.0.1:38440` → `GET /v1/models` → `POST /v1/responses` с `glm-5.2` → `models_cache.json` → текущий дефолт → LaunchAgent loaded → права ключа `0600`
- [ ] **DIAG-02**: HTTP-пробы (`/v1/models` AND `/v1/responses`) с жёстким timeout — порт открыт ≠ auth корректен
- [ ] **DIAG-03**: Detection запущенного Codex Desktop (`pgrep -x Codex`) с предупреждением о потенциально stale config
- [ ] **DIAG-04**: Цветные маркеры `[✓]`/`[!]`/`[✗]` + "To fix:" per failure; exit non-zero только на `✗`

### Service Lifecycle

- [ ] **SERV-01**: `install-service` создаёт LaunchAgent (`~/Library/LaunchAgents/`, современный `launchctl bootstrap gui/<UID>`, `KeepAlive`/`RunAtLoad`, абсолютный путь к binary)
- [ ] **SERV-02**: `uninstall-service` (`launchctl bootout` + удаление plist; idempotent, graceful EIO/"already booted out")
- [ ] **SERV-03**: `install-service`/`uninstall-service` делят общий plist Label constant (не осиротят агент)
- [ ] **SERV-04**: Post-install верификация (`launchctl print` + port probe, не только exit 0)

### Dependency Detection & Moon Bridge Install

- [ ] **DEPS-01**: Detection Go / brew / Moon Bridge binary через `shutil.which` (runtime resolution Apple Silicon `/opt/homebrew/bin` vs `/usr/local/bin`)
- [ ] **DEPS-02**: Offer-to-install Go/brew с явным согласием (never auto-install system toolchains)
- [ ] **DEPS-03**: `setup` ставит Moon Bridge build-from-source: Go 1.25+ check → brew bootstrap suggestion → `git clone` pinned commit SHA → `go build -o ~/.codex/moon-bridge ./cmd/moonbridge` → `chmod 0755`
- [ ] **DEPS-04**: Moon Bridge pinned к known-good commit SHA (НЕ `main` — релизов нет); binary НЕ вендорится в wheel (GPL v3)

### Setup Onboarding

- [ ] **SETUP-01**: `setup` — интерактивный онбординг: default provider (zai/openai), API key из `ZAI_API_KEY`/stdin, shell helpers opt-in, LaunchAgent, Moon Bridge install
- [ ] **SETUP-02**: Полностью scriptable через `--yes` / `--no-input` (единый `confirm()` helper)
- [ ] **SETUP-03**: Идемпотентный (run twice → identical output)

### Secondary Files

- [x] **SEC-01**: Shell helpers `codex-zai()` / `codex-openai()` в `.zshrc` (opt-in, marker-fenced `# >>> zai-codex-helper >>>` / `# <<<`, clean removal)
- [ ] **SEC-02**: `models_cache.json` update записью `glm-5.2` (silence metadata warning) — GATED на schema spike (проверить реальную схему; рассмотреть `model_catalog_json` как non-clobberable альтернативу)

### Testing & Quality

- [ ] **TEST-01**: Unit-тесты: патч TOML сохраняет trust blocks, `use zai`/`use openai` корректны, идемпотентность, backup-once
- [ ] **TEST-02**: Integration-тесты: запись во временный `HOME`, `doctor` против фейк-сервиса Moon Bridge (pytest-httpserver)
- [ ] **TEST-03**: Smoke: полный `setup → doctor` без вызова модели
- [ ] **TEST-04**: e2e harness: `use zai` → живой `codex exec "Respond exactly: OK"` → `use openai` → снова `codex exec` (локально, вне CI, требует живого ключа)
- [ ] **TEST-05**: CI прогоняет unit + integration + smoke; e2e исключён из CI (маркер `pytest -m e2e`)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Polish & Extras

- **POL-01**: `version` команда + optional неблокирующая подсказка о доступной новой версии (без self-update; отложить апгрейды на pip/pipx)

### Future Platform Support

- **PLAT-01**: Linux нативная поддержка (systemd-сервис) — сейчас только macOS
- **PLAT-02**: Multi-provider поддержка помимо zai/openai

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Windows (нативная) | Out of Scope — v1 macOS-only; утроит test surface |
| Linux нативный systemd-сервис | v1 macOS-only; Linux покрыт через Docker только для тестирования |
| Desktop App acceptance как автотест | Restart Codex Desktop + визуальная проверка `glm-5.2 xhigh` — мануальный чек-лист приёмки, не автотестируемо |
| e2e-тесты в CI | Требуют живого `ZAI_API_KEY` + запущенного Moon Bridge; хрупкие, локально только |
| Self-update (`upgrade` команда) | Anti-pattern для pip-installed CLIs; ломается под pipx-изоляцией |
| "Detect and sync" smart-merge | `setup` перезаписывает по каноничному шаблону, не мержит (простейший честный вариант) |
| Backup per mutation (каждое изменение) | Устаревший пункт из issue #1; заменён на один раз на пользователя |
| Auto-install Go/brew без подтверждения | Нарушает user trust; только offer-to-install с явным согласием |
| Vendoring Moon Bridge binary в wheel | GPL v3 + размер + воспроизводимость; бинарник строится из исходников |
| Захардкоженные API-ключи | Security incident на публичном PyPI |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PKG-01 | Phase 1 | Complete |
| PKG-02 | Phase 1 | Complete |
| PKG-03 | Phase 2 | Complete |
| PKG-04 | Phase 1 | Complete |
| PKG-05 | Phase 1 | Complete |
| CONF-01 | Phase 3 | Complete |
| CONF-02 | Phase 5 | Complete |
| CONF-03 | Phase 4 | Complete |
| CONF-04 | Phase 4 | Complete |
| CONF-05 | Phase 6 | Complete |
| CONF-06 | Phase 7 | Complete |
| CONF-07 | Phase 15 | Pending |
| PROV-01 | Phase 7 | Complete |
| PROV-02 | Phase 7 | Complete |
| PROV-03 | Phase 6 | Complete |
| PROV-04 | Phase 7 | Complete |
| PROV-05 | Phase 8 | Complete |
| SECR-01 | Phase 12 | Pending |
| SECR-02 | Phase 9 | Complete |
| SECR-03 | Phase 15 | Pending |
| DIAG-01 | Phase 14 | Pending |
| DIAG-02 | Phase 14 | Pending |
| DIAG-03 | Phase 14 | Pending |
| DIAG-04 | Phase 14 | Pending |
| SERV-01 | Phase 13 | Pending |
| SERV-02 | Phase 13 | Pending |
| SERV-03 | Phase 13 | Pending |
| SERV-04 | Phase 13 | Pending |
| DEPS-01 | Phase 10 | Pending |
| DEPS-02 | Phase 10 | Pending |
| DEPS-03 | Phase 11 | Pending |
| DEPS-04 | Phase 11 | Pending |
| SETUP-01 | Phase 12 | Pending |
| SETUP-02 | Phase 12 | Pending |
| SETUP-03 | Phase 12 | Pending |
| SEC-01 | Phase 9 | Complete |
| SEC-02 | Phase 15 | Pending |
| TEST-01 | Phase 15 | Pending |
| TEST-02 | Phase 15 | Pending |
| TEST-03 | Phase 15 | Pending |
| TEST-04 | Phase 15 | Pending |
| TEST-05 | Phase 15 | Pending |

**Coverage:**

- v1 requirements: 42 total
- Mapped to phases: 42
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-29*
*Last updated: 2026-06-29 after roadmap creation (traceability populated)*
