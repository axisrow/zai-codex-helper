# zai-codex-helper

`zai-codex-helper` is a pip-installable Python CLI for macOS that manages the
**Codex ⇄ Moon Bridge ⇄ Z.ai** link without hand-editing `~/.codex/config.toml`,
`~/.zshrc`, or `moonbridge-zai.yml`. One command makes Z.ai (`glm-5.2 xhigh`)
the default Codex provider, and another reverts to OpenAI.

> **Status:** early development. The package installs and the CLI parses, but
> the subcommands are stubs until later phases land real handlers.

## Install

```bash
pip install .
```

For development (editable install + test tooling):

```bash
pip install -e ".[dev]"
```

## Usage

```bash
zai-codex-helper --help          # show usage, exit 0
zai-codex-helper use zai         # make Z.ai the default (stub — not yet implemented)
zai-codex-helper use openai      # revert to OpenAI (stub — not yet implemented)
```

All subcommands (`setup`, `use zai`, `use openai`, `status`, `doctor`,
`install-service`, `uninstall-service`) currently print
`<command>: not implemented in this phase` to stderr and exit 0. Real behavior
arrives in subsequent phases.
