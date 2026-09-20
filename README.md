# NoMercy Labs skills

[![skills.sh](https://skills.sh/b/NoMercyLabs/skills)](https://skills.sh/NoMercyLabs/skills)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-spec%20compliant-0a0a0a)](https://agentskills.io)
[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-d97757)](#install-as-a-claude-code-plugin)
[![License: MIT](https://img.shields.io/github/license/NoMercyLabs/skills)](LICENSE)

[Agent Skills](https://agentskills.io) from NoMercy Labs. Each one reads the repository in front of it instead of assuming, and each ships with the checks that prove it did.

| Skill | What it does | Docs |
| --- | --- | --- |
| [`atlas`](skills/atlas) | Maps a whole project and documents it as one system, in one voice. Every claim is grounded in the code, every page passes a fact-check and a reader review, and a checker refuses to call the set delivered until every page does. | [README](skills/atlas/README.md) · [SKILL.md](skills/atlas/SKILL.md) |
| [`devbox-anywhere`](skills/devbox-anywhere) | Builds a containerized development environment for any project: VS Code in the browser, Dev Containers and Remote-SSH, with the toolchain detected from the repo and no host secret forwarded in. | [README](skills/devbox-anywhere/README.md) · [SKILL.md](skills/devbox-anywhere/SKILL.md) |

## Install

### With the skills CLI

Claude Code, Codex, Cursor, OpenCode, Copilot and 70 more agents. All skills:

```bash
npx skills add NoMercyLabs/skills
```

One skill:

```bash
npx skills add NoMercyLabs/skills --skill atlas
npx skills add NoMercyLabs/skills --skill devbox-anywhere
```

### Install as a Claude Code plugin

One plugin carries every skill, namespaced as `/nomercylabs:atlas` and `/nomercylabs:devbox-anywhere`:

```
/plugin marketplace add NoMercyLabs/skills
/plugin install nomercylabs@nomercylabs
```

### By hand

```bash
git clone https://github.com/NoMercyLabs/skills /tmp/nomercylabs-skills \
  && cp -r /tmp/nomercylabs-skills/skills/atlas ~/.claude/skills/
```

Or copy the skill folder into your project's `.claude/skills/` to share it with the repo.

### On claude.ai

Every SKILL.md uses only the six spec frontmatter fields, so a skill folder packages and uploads as a personal skill without edits:

```bash
python package_skill.py skills/atlas   # from anthropics/skills
```

## Layout

```
skills/
├── atlas/              SKILL.md, agents/, references/, scripts/check_docs.py
└── devbox-anywhere/    SKILL.md, assets/, references/
```

Each skill folder is self-contained and carries its own README and LICENSE. The repo root is also a Claude Code plugin, so the same tree serves both install paths.

## History

`atlas` and `devbox-anywhere` started as one repo each. Both are archived and point here. Their release history stays on the old repos.

## License

MIT, see [LICENSE](LICENSE).
