# Security policy

## Reporting

Please do not open a public issue. Report it privately with
[Report a vulnerability](https://github.com/mangow314/party-hud/security/advisories/new) on the Security tab.
Only the latest commit on `master` gets fixes.

## Scope

party-hud runs locally inside tmux and never uses the network. Issues that matter most:

- Parsing agent files: a crafted session, transcript or statusline file that makes party-hud run code, read files
  outside what [docs/integrations.md](docs/integrations.md) lists, or write anywhere outside its own runtime
  directory.
- Terminal output: agent-controlled text (session names, transcript text) that reaches the terminal as escape
  sequences.
- The crew subcommands (summon, send, dismiss, `--restore-end`): sending keys to or closing a pane other than the
  one the caller named.
