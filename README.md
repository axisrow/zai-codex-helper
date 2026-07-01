# zai-codex-helper

`zai-codex-helper` is a pip-installable Python CLI for macOS that manages the
**Codex ⇄ Moon Bridge ⇄ Z.ai** link without hand-editing `~/.codex/config.toml`,
`~/.zshrc`, or `moonbridge-zai.yml`. One command makes Z.ai (`glm-5.2 xhigh`)
the default Codex provider (CLI **and** Desktop app), and another reverts to
OpenAI.

## Requirements

- macOS (the LaunchAgent + `.zshrc` integration is macOS-only).
- Python 3.10+.
- Go 1.25+ — Moon Bridge is built from source on your machine (never vendored).
  `install` / `setup` print the `brew install go` one-liner if it's missing.

## Install

```bash
pip install .
```

For development (editable install + test tooling):

```bash
pip install -e ".[dev]"
```

## Usage

**Turn Z.ai on/off end-to-end** — the Core Value, one command each:

```bash
zai-codex-helper install     # Z.ai ON: setup + config + Moon Bridge LaunchAgent
zai-codex-helper uninstall   # Z.ai OFF: revert config, stop Moon Bridge, rm yml
zai-codex-helper             # no subcommand → interactive arrow-key TUI menu
```

**Switch the provider** (config only, no service changes):

```bash
zai-codex-helper use zai      # make Z.ai (glm-5.2 xhigh) the default
zai-codex-helper use openai   # revert to OpenAI
```

**Onboarding & maintenance:**

```bash
zai-codex-helper setup               # guided end-to-end onboarding
zai-codex-helper set-key             # replace the Z.ai API key in moonbridge-zai.yml
zai-codex-helper status              # current provider, config paths, version
zai-codex-helper doctor              # diagnose the Codex ⇄ Moon Bridge ⇄ Z.ai chain
zai-codex-helper restore             # restore config from the one-time backup
zai-codex-helper install-service     # install the Moon Bridge LaunchAgent
zai-codex-helper uninstall-service   # uninstall the Moon Bridge LaunchAgent
```

After `install` (or `use zai`), a bare `codex` — no flags, env, or profile, what
both Codex CLI and the Desktop app read — starts on Z.ai.

## Flags

Global flags are accepted **both before and after** the subcommand:

- `--dry-run` — preview a change as a diff instead of writing it, for the
  config-mutating commands (`use`, `setup`, `install`, `uninstall`, `set-key`).
  Note: `restore` ignores it and rolls back immediately.
- `--debug` — print a full traceback instead of the one-line `error: <msg>`.
- `--yes` / `--no-input` — headless mode for the interactive flows (`setup`,
  `install`): skip all prompts, taking the key from `ZAI_API_KEY` in the
  environment. Only `setup` and `install` read these flags; every other command
  ignores them.

`install` and `install-service` are **convergent**: a repeat run on a healthy,
already-installed setup does nothing (it won't bounce a running Moon Bridge).
Pass `--force` to reinstall the LaunchAgent unconditionally.

Secrets are never echoed: the API key comes from `ZAI_API_KEY` or a hidden
prompt, and `moonbridge-zai.yml` is written at mode `0600`.
