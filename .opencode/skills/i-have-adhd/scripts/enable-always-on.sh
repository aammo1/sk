#!/usr/bin/env bash
set -euo pipefail

# Enable always-on ADHD output rules across Antigravity, Claude Code, Codex, and OpenCode.
# Safe to re-run: appends only when missing and never overwrites existing CLAUDE.md/AGENTS.md content.

read -r -d '' RULE_BLOCK <<'EOF' || true
## Output style

The reader has ADHD. Shape every response so it can be acted on (turn off for the current session when the reader says "stop adhd mode" or "normal mode"):

1. Lead with the answer or next action: command, path, or snippet first.
2. Number multi-step work; one bounded action per step.
3. End with one next action doable in under two minutes.
4. Finish the current issue before raising a new one.
5. Restate progress each turn ("step 3 of 5 done").
6. Give time estimates in concrete units, never "a bit".
7. After a change, show what now works.
8. Errors: state location, cause, and fix. No drama.
9. Cap lists to 5 items.
10. No preamble, no recaps, no closers.

Exceptions: explain fully when asked to explain. Confirm before destructive actions. After three failed fixes, stop and name the doubtful assumption. If the request is ambiguous, ask one short question. If a rule fights the harness/system prompt, the harness wins and the shape stays.
EOF

MARKER="The reader has ADHD."

install_rule_file() {
  local target="$1"
  mkdir -p "$(dirname "$target")"
  if [[ -f "$target" ]] && grep -qF "$MARKER" "$target"; then
    echo "already configured: $target"
    return
  fi
  if [[ -s "$target" ]]; then
    printf '\n%s\n' "$RULE_BLOCK" >>"$target"
    echo "appended: $target"
  else
    printf '%s\n' "$RULE_BLOCK" >"$target"
    echo "created: $target"
  fi
}

# Antigravity global plugin (toggleable via `agy plugin disable i-have-adhd`)
AGY_PLUGIN_DIR="${HOME}/.gemini/config/plugins/i-have-adhd"
mkdir -p "${AGY_PLUGIN_DIR}/rules"
cat >"${AGY_PLUGIN_DIR}/plugin.json" <<'EOF'
{
  "name": "i-have-adhd",
  "displayName": "I Have ADHD (Always-On)",
  "version": "1.0.0",
  "description": "Always-on ADHD-friendly output style rules across every session."
}
EOF
printf '%s\n' "$RULE_BLOCK" >"${AGY_PLUGIN_DIR}/rules/AGENTS.md"
echo "configured: ${AGY_PLUGIN_DIR}"

# Claude Code, Codex, OpenCode
install_rule_file "${HOME}/.claude/CLAUDE.md"
install_rule_file "${HOME}/.codex/AGENTS.md"
install_rule_file "${XDG_CONFIG_HOME:-${HOME}/.config}/opencode/AGENTS.md"
