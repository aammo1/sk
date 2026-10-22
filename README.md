# sk — agent skills backup

Every skill I use, in the `SKILL.md` format shared by DSH (DeepSeek Harness), Claude Code and OpenCode.

```
.opencode/skills/<name>/SKILL.md    loadable skills
.opencode/archive/                  reference material, not loadable
```

The `skills` CLI finds a `SKILL.md` anywhere in the repo, so the `.opencode/skills` directory name is cosmetic, not a requirement.

## Install

Use the [`skills` CLI](https://github.com/vercel-labs/skills) (Node 22.20+). It prompts for which skills and which agents, then records what it installed in `skills-lock.json` so it can update or remove them later.

```sh
npx skills add aammo1/sk                     # choose skills and agents
npx skills add aammo1/sk -g                  # global, available in every project
npx skills add aammo1/sk --skill coolify-deploy -a claude-code   # non-interactive

npx skills list                              # what is installed
npx skills check                             # update anything changed upstream
npx skills remove <skill>                    # uninstall
```

Select an agent that targets `~/.agents/skills/` when installing globally (Codex, Cline, Universal, or any of the others that share that path). That is the one root DSH reads, so it is what makes a skill visible to DSH, Claude Code and OpenCode at the same time.

`npx skills check` is not a dry run: it applies the updates it finds.

A fresh Omarchy machine ends up with the repo's skills plus `diagnose-crash` and `omarchy`, which live in `/usr/share/omarchy/default/agents/skills` and are intentionally not duplicated here.

## Which root each agent reads

| Root | DSH | Claude Code | OpenCode |
|---|---|---|---|
| `<project>/.dsh/skills` | yes | no | no |
| `<project>/.agents/skills` | yes | no | yes |
| `~/.dsh/skills` | yes | no | no |
| `~/.agents/skills` | yes | no | yes |
| `~/.claude/skills` | no | yes | yes |
| `~/.config/opencode/skills` | no | no | yes |

DSH does **not** read `.opencode/skills` or `~/.claude/skills`, so cloning this repo is not enough on its own. Install through the `skills` CLI so the files land in a root your agent actually reads.

## Authoring rules

A skill is `<name>/SKILL.md` with YAML frontmatter:

```yaml
---
name: kebab-case-name        # must match the directory name
description: What it does and when to use it.
---
```

- Quote or block-scalar the description if it contains `: `, `#`, or starts with `-`, `{`, `[`. An unquoted colon silently breaks the YAML.
- `name` must match `^[a-z0-9]+(-[a-z0-9]+)*$` and equal the directory name.
- Keep the description under 1024 characters so OpenCode loads it too.
- DSH drops an invalid skill with only a host-log warning, so validate before committing:

```sh
uv run --script ~/.dsh/tools/skill_check.py .opencode/skills
```

Exit code 1 means DSH would skip that skill.
