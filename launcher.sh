#!/usr/bin/env bash
# launcher.sh - locate a Radioconda/conda env with UHD and launch the spectrum analyzer.
# Used directly on Linux; on macOS, launcher.command is a thin wrapper that exec's this.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MAIN_SCRIPT="$SCRIPT_DIR/dses_spectrum_analyzer.py"

case "$(uname)" in
    Darwin)
        CONFIG_DIR="$HOME/Library/Application Support/DSES_Analyzer"
        ;;
    *)
        CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dses-analyzer"
        ;;
esac
CONFIG_FILE="$CONFIG_DIR/radioconda_root"
MARKER="share/uhd/images/usrp_b210_fpga.bin"

is_radioconda() {
    local p="${1:-}"
    [ -z "$p" ] && return 1
    [ -x "$p/bin/python" ] && [ -f "$p/$MARKER" ]
}

find_radioconda() {
    # 1. Env var override
    if [ -n "${RADIOCONDA_ROOT:-}" ] && is_radioconda "$RADIOCONDA_ROOT"; then
        printf '%s' "$RADIOCONDA_ROOT"; return 0
    fi
    # 2. Already-activated conda env
    if [ -n "${CONDA_PREFIX:-}" ] && is_radioconda "$CONDA_PREFIX"; then
        printf '%s' "$CONDA_PREFIX"; return 0
    fi
    # 3. Standard install paths
    local p
    for p in "$HOME/radioconda" "/opt/radioconda"; do
        if is_radioconda "$p"; then
            printf '%s' "$p"; return 0
        fi
    done
    # 4. Cached config (from a previous first-run prompt)
    if [ -f "$CONFIG_FILE" ]; then
        local cached
        cached="$(cat "$CONFIG_FILE")"
        if is_radioconda "$cached"; then
            printf '%s' "$cached"; return 0
        fi
    fi
    # 5. conda on PATH
    if command -v conda >/dev/null 2>&1; then
        local base
        base="$(conda info --base 2>/dev/null || true)"
        if is_radioconda "$base"; then
            printf '%s' "$base"; return 0
        fi
    fi
    return 1
}

if ! ROOT="$(find_radioconda)"; then
    echo "Radioconda not found in standard locations." >&2
    echo "Searched:" >&2
    echo "  - \$RADIOCONDA_ROOT" >&2
    echo "  - \$CONDA_PREFIX" >&2
    echo "  - \$HOME/radioconda" >&2
    echo "  - /opt/radioconda" >&2
    echo "  - $CONFIG_FILE" >&2
    echo "  - conda on PATH" >&2
    echo >&2
    printf 'Enter path to Radioconda install (blank to abort): '
    read -r USER_PATH
    if [ -z "$USER_PATH" ]; then
        echo "Aborted. Install Radioconda from https://github.com/ryanvolz/radioconda/releases" >&2
        exit 1
    fi
    if ! is_radioconda "$USER_PATH"; then
        echo "Invalid path: '$USER_PATH' does not contain bin/python and the B210 FPGA image." >&2
        exit 1
    fi
    mkdir -p "$CONFIG_DIR"
    printf '%s\n' "$USER_PATH" > "$CONFIG_FILE"
    ROOT="$USER_PATH"
fi

cd "$SCRIPT_DIR"
exec "$ROOT/bin/python" "$MAIN_SCRIPT" "$@"
