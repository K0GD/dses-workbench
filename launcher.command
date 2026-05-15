#!/usr/bin/env bash
# launcher.command - macOS Finder-double-clickable entry. Delegates to launcher.sh.
exec "$(cd "$(dirname "$0")" && pwd)/launcher.sh" "$@"
