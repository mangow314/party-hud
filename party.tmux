#!/usr/bin/env bash
# party-hud entry point. TPM runs this file when tmux starts; you can also run it from tmux.conf:
#   run-shell ~/path/to/party-hud/party.tmux
# Keys can be changed with options set BEFORE this runs, e.g.  set -g @party_key_toggle 'C-t'
dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
party="python3 $(printf %q "$dir/party.py")" # quoted: the path may contain spaces

opt() { # opt <name> <default>
  local v
  v=$(tmux show-option -gqv "$1")
  echo "${v:-$2}"
}

# Images are sent to the outer terminal through tmux passthrough (Kitty graphics protocol).
# "on" only lets the visible pane pass sequences through. Set @party_art to "off" to skip this.
if [ "$(opt @party_art auto)" != "off" ]; then
  tmux set -g allow-passthrough on
fi
# Colored underlines are the HP / SP bars. tmux only forwards underline color when the terminal declares usstyle.
tmux set -as terminal-features ',xterm-ghostty:usstyle,xterm-kitty:usstyle'

tmux bind-key "$(opt @party_key_popup P)" display-popup -E -w 36 -h 85% -T " Party " "$party --watch"
tmux bind-key "$(opt @party_key_toggle C-t)" run-shell -b "$party --toggle"
tmux bind-key "$(opt @party_key_next a)" run-shell -b "$party --next"
# After dragging a pane border: if it was a sidebar, remember the width and apply it to every sidebar
tmux bind-key -n MouseDragEnd1Border run-shell -b "$party --remember-width"
