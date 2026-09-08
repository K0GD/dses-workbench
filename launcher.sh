#!/usr/bin/env bash
# launcher.sh - locate a Radioconda/conda env with UHD and launch the DSES Radio Astronomy Workbench.
# Used directly on Linux; on macOS, launcher.command is a thin wrapper that exec's this.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MAIN_SCRIPT="$SCRIPT_DIR/dses_workbench.py"

case "$(uname)" in
    Darwin)
        CONFIG_DIR="$HOME/Library/Application Support/DSES_Analyzer"
        ;;
    *)
        CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dses-analyzer"
        ;;
esac
CONFIG_FILE="$CONFIG_DIR/radioconda_root"

is_radioconda() {
    # A usable env is any conda/Radioconda prefix whose python can import
    # GNU Radio. We deliberately do NOT require the B210 UHD FPGA image:
    # this is a multi-radio app (SDRPlay, RTL-SDR, etc. need no UHD images),
    # and some Radioconda builds don't ship the images until
    # uhd_images_downloader is run.
    local p="${1:-}"
    [ -z "$p" ] && return 1
    [ -x "$p/bin/python" ] || return 1
    "$p/bin/python" -c "import gnuradio" >/dev/null 2>&1
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
    printf 'Enter path to Radioconda install (e.g. ~/radioconda; blank to abort): '
    read -r USER_PATH
    if [ -z "$USER_PATH" ]; then
        echo "Aborted. Install Radioconda from https://github.com/radioconda/radioconda-installer/releases" >&2
        exit 1
    fi
    # Expand a leading ~ — bash 'read' does not do tilde expansion itself.
    USER_PATH="${USER_PATH/#\~/$HOME}"
    if ! is_radioconda "$USER_PATH"; then
        echo "Invalid path: '$USER_PATH' is not a GNU Radio environment (its bin/python can't 'import gnuradio')." >&2
        exit 1
    fi
    mkdir -p "$CONFIG_DIR"
    printf '%s\n' "$USER_PATH" > "$CONFIG_FILE"
    ROOT="$USER_PATH"
fi

# Preflight: the app needs a few packages that stock Radioconda doesn't ship
# (the GUI/plotting stack). Give a clear instruction instead of a traceback.
if ! "$ROOT/bin/python" -c "import PySide6, pyqtgraph, scipy" >/dev/null 2>&1; then
    echo "Missing required packages (PySide6, pyqtgraph, and/or scipy)." >&2
    echo "Install them into Radioconda once, from a shell showing (base):" >&2
    echo "    conda install -c conda-forge pyside6 pyqtgraph scipy" >&2
    echo "(see section 2.4 of the installation guide)." >&2
    exit 1
fi

# Linux headless-display fix. When no monitor is connected (e.g. the box is
# viewed over Splashtop/RDP with HDMI disconnected), the X server has a
# framebuffer but no *connected* RandR output, so Qt reports a 0x0 screen —
# which collapses every popup (dropdowns, menus) and breaks window geometry.
# If RandR reports no monitors, synthesize one spanning the framebuffer so Qt
# sees a real screen. Skipped when a real monitor is attached (Monitors >= 1);
# a no-op on macOS and where xrandr is absent. Uses ${fbw}/${fbh} locals so it
# never clobbers "$@" (passed through to the app below).
if [ "$(uname)" = "Linux" ] && [ -n "${DISPLAY:-}" ] && command -v xrandr >/dev/null 2>&1; then
    if xrandr --listmonitors 2>/dev/null | head -1 | grep -q '^Monitors: 0'; then
        fbdim="$(xrandr -q 2>/dev/null | sed -n 's/.*current \([0-9]\{2,\}\) x \([0-9]\{2,\}\).*/\1 \2/p' | head -1)"
        if [ -n "$fbdim" ]; then
            fbw="${fbdim% *}"; fbh="${fbdim#* }"
            xrandr --setmonitor DSES-VIRT "${fbw}/508x${fbh}/286+0+0" none 2>/dev/null \
                && echo "launcher: no monitor connected — synthesized a ${fbw}x${fbh} virtual screen so Qt popups/geometry work." >&2
        fi
    fi
fi

cd "$SCRIPT_DIR"
exec "$ROOT/bin/python" "$MAIN_SCRIPT" "$@"
