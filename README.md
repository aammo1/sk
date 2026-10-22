# sk — agent skills backup

Every skill I use, in the `SKILL.md` format shared by DSH (DeepSeek Harness), Claude Code and OpenCode.

```
.opencode/skills/<name>/SKILL.md    loadable skills
.opencode/archive/                  reference material, not loadable
install.sh                          link the skills into ~/.agents/skills
```

## Install

```sh
git clone https://github.com/aammo1/sk ~/Skills/sk
~/Skills/sk/install.sh --list                     # what can I install?
~/Skills/sk/install.sh seo-optimizer nextjs       # install just these
```

`install.sh` symlinks skills into `~/.agents/skills`, the one root all three agents read.

| Usage | Effect |
|---|---|
| `./install.sh` | install every skill |
| `./install.sh name [name...]` | install only the named skills |
| `./install.sh --all` | install every skill, explicitly |
| `./install.sh --list` | list installable names, install nothing |
| `--copy` | copy instead of symlinking |
| `--force` | replace an existing real directory (default: skip and keep it) |
| `--dest=DIR` | install elsewhere |
| `AGENTS_SKILLS=DIR` | same as `--dest` |

Names are validated before anything is touched: an unknown name exits 2 and prints the available list. A selective run only touches the skills you named, so it can top up an existing root without disturbing anything already installed.

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

DSH does **not** read `.opencode/skills` or `~/.claude/skills`, so cloning this repo is not enough on its own. Run `install.sh`.

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
