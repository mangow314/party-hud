#!/usr/bin/env bash
# Feed Claude Code's statusline JSON to party-hud (HP max, model name, transcript path).
#
# Claude Code pipes a JSON object to your statusLine command on every refresh. Pass that same JSON here:
#
#   input=$(cat)
#   printf '%s' "$input" | ~/.tmux/plugins/party-hud/integrations/claude-statusline.sh
#   ... the rest of your statusline ...
#
# Writes $XDG_RUNTIME_DIR/party-hud/<pane>.json (falls back to ~/.cache/party-hud). Prints nothing.
# Outside tmux, or without jq, it does nothing. Failures never break your statusline.
# Field reference: docs/integrations.md
[[ "${TMUX_PANE:-}" =~ ^%[0-9]+$ ]] || exit 0
command -v jq >/dev/null 2>&1 || exit 0

dir="${XDG_RUNTIME_DIR:-$HOME/.cache}/party-hud"
mkdir -p "$dir" 2>/dev/null || exit 0
file="$dir/${TMUX_PANE#%}.json"

# jq builds the JSON, so names and paths are escaped correctly. Only ASCII-safe values are kept.
jq -c --argjson now "$(date +%s)" '{
  updated: $now,
  session_id: (.session_id // "" | if test("^[A-Za-z0-9_-]+$") then . else "" end),
  ctx_left: (.context_window.used_percentage // null | if . == null then null else (100 - round) end),
  ctx_size: (.context_window.context_window_size // null),
  transcript: (.transcript_path // "" | if test("\\.jsonl$") then . else "" end),
  model: (.model.display_name // "" | sub(" \\(.*$"; ""))
}' >"$file.$$" 2>/dev/null && mv -f "$file.$$" "$file" 2>/dev/null
rm -f "$file.$$" 2>/dev/null
exit 0
