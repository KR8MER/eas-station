# shellcheck shell=bash
# scripts/lib/ui.sh — shared terminal UI primitives for EAS Station's
# install.sh and update.sh.
#
# Goals:
#   * Modern look (ANSI gradient banner, braille spinner, animated progress
#     bars, real apt/pip progress) without adding hard new dependencies.
#   * Works over plain SSH and on Raspberry Pi OS Lite (no GUI, no Sixel
#     required). Degrades cleanly when stdout isn't a TTY.
#   * 100% backward compatible: every function name historically defined
#     inline in install.sh / update.sh (color codes, `_tty`, `echo_step`,
#     `echo_info`, `whiptail` wrapper, `cleanup_on_exit`, `show_celebration`,
#     `format_duration`, `draw_box`, `show_spinner`, etc.) is provided here
#     with the same signature, so sourcing this file replaces the old inline
#     preamble with no other edits required.
#
# Conventions:
#   * Public helpers are prefixed `ui_`.
#   * Legacy names kept (no prefix) to preserve existing callers.
#   * All TUI output goes to /dev/tty so it survives the `exec 1>>LOG 2>&1`
#     redirect both scripts perform after the root check.
#
# Copyright (c) 2025-2026 Timothy Kramer (KR8MER)
# Licensed under AGPL v3 or Commercial License

# Guard against double-sourcing.
if [ -n "${_EAS_UI_LOADED:-}" ]; then return 0 2>/dev/null || exit 0; fi
_EAS_UI_LOADED=1

# ── Color / style codes ─────────────────────────────────────────────────────
RED=$'\033[1;31m'
GREEN=$'\033[1;32m'
YELLOW=$'\033[1;33m'
CYAN=$'\033[1;36m'
WHITE=$'\033[1;37m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
NC=$'\033[0m'
BLUE=$'\033[0;34m'
MAGENTA=$'\033[0;35m'

# 256-color shades used by the banner (graceful fallback if terminal doesn't
# support 256 — they just render as approximate ANSI colors).
_UI_C1=$'\033[38;5;39m'    # bright cyan-blue
_UI_C2=$'\033[38;5;33m'    # blue
_UI_C3=$'\033[38;5;27m'    # deep blue
_UI_C4=$'\033[38;5;75m'    # sky
_UI_C5=$'\033[38;5;81m'    # cyan
_UI_C6=$'\033[38;5;220m'   # amber accent
_UI_GREY=$'\033[38;5;245m'

# ── Step tracking (kept as global state for backward compatibility) ────────
STEP_NUM=${STEP_NUM:-0}
TOTAL_STEPS=${TOTAL_STEPS:-1}
CURRENT_DESC=${CURRENT_DESC:-"Initializing..."}
START_TIME=${START_TIME:-$(date +%s)}

# Honour NO_COLOR (https://no-color.org/) and non-TTY destinations.
_ui_tty_supports_color() {
    [ -z "${NO_COLOR:-}" ] && { [ -t 1 ] || [ -w /dev/tty ]; }
}

# Write a single line directly to the terminal, bypassing any log redirect.
_tty() { printf '%s\n' "$1" >/dev/tty 2>/dev/null || printf '%s\n' "$1"; }

# Write raw bytes (no trailing newline) directly to the terminal.
_tty_raw() { printf '%s' "$1" >/dev/tty 2>/dev/null || printf '%s' "$1"; }

# ── whiptail wrapper ───────────────────────────────────────────────────────
# Forces TUI output to /dev/tty so ncurses is never swallowed by the install
# log redirect. Callers that capture user input still use the standard
# "3>&1 1>&2 2>&3" fd-swap trick; >/dev/tty only overrides fd1, leaving fd2
# (the captured result) untouched.
whiptail() {
    command whiptail "$@" >/dev/tty
    local _ret=$?
    stty sane </dev/tty 2>/dev/null || true
    return $_ret
}

# Branding line shown as the whiptail backtitle on every dialog.
whiptail_footer() {
    echo "Copyright (c) 2025-2026 Timothy Kramer (KR8MER) | AGPL v3 / Commercial License"
}

# ── Time formatting ────────────────────────────────────────────────────────
format_duration() {
    local seconds=$1
    local hours=$((seconds / 3600))
    local minutes=$(( (seconds % 3600) / 60 ))
    local secs=$((seconds % 60))
    if [ "$hours" -gt 0 ]; then
        printf "%dh %dm %ds" "$hours" "$minutes" "$secs"
    elif [ "$minutes" -gt 0 ]; then
        printf "%dm %ds" "$minutes" "$secs"
    else
        printf "%ds" "$secs"
    fi
}

# ── Banner ─────────────────────────────────────────────────────────────────
# A multi-line gradient ASCII-art logo. Hand-crafted (no figlet dep) so it
# renders identically everywhere. Suitable for both install and update flows
# via the optional subtitle argument.
#
# Usage: ui_banner "Bare Metal Installer"
ui_banner() {
    local subtitle="${1:-Emergency Alert System}"
    local version_line="${2:-}"
    local log_line="${3:-}"

    # Clear and home cursor.
    _tty_raw $'\033[2J\033[H'

    if _ui_tty_supports_color; then
        {
            printf '\n'
            printf '%s ███████╗ █████╗ ███████╗   ███████╗████████╗ █████╗ ████████╗██╗ ██████╗ ███╗   ██╗%s\n' "$_UI_C1" "$NC"
            printf '%s ██╔════╝██╔══██╗██╔════╝   ██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝██║██╔═══██╗████╗  ██║%s\n' "$_UI_C4" "$NC"
            printf '%s █████╗  ███████║███████╗   ███████╗   ██║   ███████║   ██║   ██║██║   ██║██╔██╗ ██║%s\n' "$_UI_C5" "$NC"
            printf '%s ██╔══╝  ██╔══██║╚════██║   ╚════██║   ██║   ██╔══██║   ██║   ██║██║   ██║██║╚██╗██║%s\n' "$_UI_C2" "$NC"
            printf '%s ███████╗██║  ██║███████║██╗███████║   ██║   ██║  ██║   ██║   ██║╚██████╔╝██║ ╚████║%s\n' "$_UI_C3" "$NC"
            printf '%s ╚══════╝╚═╝  ╚═╝╚══════╝╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝  ╚═══╝%s\n' "$_UI_C3" "$NC"
            printf '\n'
            printf '   %s%s%s   %s•%s   %sEmergency Alert System%s\n' \
                "$BOLD" "$subtitle" "$NC" "$_UI_GREY" "$NC" "$_UI_C6" "$NC"
            if [ -n "$version_line" ]; then
                printf '   %s%s%s\n' "$_UI_GREY" "$version_line" "$NC"
            fi
            if [ -n "$log_line" ]; then
                printf '   %sLog:%s %s\n' "$DIM" "$NC" "$log_line"
            fi
            printf '   %sCopyright (c) 2025-2026 Timothy Kramer (KR8MER) — AGPL v3 / Commercial%s\n' \
                "$DIM" "$NC"
            printf '\n'
        } >/dev/tty 2>/dev/null || true
    else
        {
            printf '\n'
            printf '  EAS STATION\n'
            printf '  %s — Emergency Alert System\n' "$subtitle"
            [ -n "$version_line" ] && printf '  %s\n' "$version_line"
            [ -n "$log_line" ] && printf '  Log: %s\n' "$log_line"
            printf '  Copyright (c) 2025-2026 Timothy Kramer (KR8MER) — AGPL v3 / Commercial\n'
            printf '\n'
        } >/dev/tty 2>/dev/null || true
    fi
}

# ── Step / status output ───────────────────────────────────────────────────
# Each helper logs a plain-text line to the redirected stdout (the log file)
# AND prints a styled line to /dev/tty.
echo_step() {
    STEP_NUM=$((STEP_NUM + 1))
    CURRENT_DESC="$1"
    local pct=$((STEP_NUM * 100 / TOTAL_STEPS))
    echo "--- Step $STEP_NUM/$TOTAL_STEPS: $1 ---"
    _tty ""
    # Header bar with a tiny inline progress meter.
    local bar_width=20
    local filled=$(( pct * bar_width / 100 ))
    [ $filled -gt $bar_width ] && filled=$bar_width
    local bar=""
    local i
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=filled; i<bar_width; i++)); do bar+="░"; done
    _tty "$(printf '\033[1;34m▌\033[0m \033[1m[%d/%d]\033[0m %s%s%s \033[1;34m%3d%%\033[0m  \033[1m%s\033[0m' \
        "$STEP_NUM" "$TOTAL_STEPS" "$_UI_C5" "$bar" "$NC" "$pct" "$1")"
}

echo_info()     { echo "[INFO]  $1"; _tty "$(printf '  \033[0;36m[INFO]\033[0m  %s' "$1")"; }
echo_success()  { echo "[ OK ]  $1"; _tty "$(printf '  \033[1;32m[ OK ]\033[0m  %s' "$1")"; }
echo_warning()  { echo "[WARN]  $1"; _tty "$(printf '  \033[1;33m[WARN]\033[0m  %s' "$1")"; }
echo_error()    { echo "[ERROR] $1"; _tty "$(printf '  \033[1;31m[ERR!]\033[0m  %s' "$1")"; }
echo_progress() { echo "  >>    $1"; _tty "$(printf '  \033[0;37m  >>  \033[0m  %s' "$1")"; }
echo_header()   { echo ""; echo "=== $1 ==="; echo ""; _tty "$(printf '\033[1m=== %s ===\033[0m' "$1")"; }
echo_operation() { echo_progress "${1}${2:+ (~$2)}"; }

# Legacy no-op shims kept for callers that referenced them.
draw_box()       { echo_success "$1"; }
draw_separator() { :; }
show_progress_bar() { :; }
show_elapsed_time() { :; }

# ── Spinner ─────────────────────────────────────────────────────────────────
# Watches an existing background PID and prints a braille-spinner with the
# elapsed time + supplied label until the PID exits. Returns the watched
# command's exit code. Backward-compatible signature: `show_spinner PID`
# (no label) still works.
show_spinner() {
    local pid="$1"
    local label="${2:-Working}"
    local frames=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
    local i=0
    local start
    start=$(date +%s)

    # If not a TTY, just wait.
    if ! [ -w /dev/tty ]; then
        wait "$pid" 2>/dev/null
        return $?
    fi

    while kill -0 "$pid" 2>/dev/null; do
        local elapsed=$(( $(date +%s) - start ))
        local f=${frames[i % ${#frames[@]}]}
        printf '\r  \033[1;36m%s\033[0m %s \033[2m(%ds)\033[0m\033[K' \
            "$f" "$label" "$elapsed" >/dev/tty 2>/dev/null || true
        i=$((i + 1))
        sleep 0.1
    done
    wait "$pid" 2>/dev/null
    local rc=$?
    # Clear the spinner line.
    printf '\r\033[K' >/dev/tty 2>/dev/null || true
    return $rc
}

# Run a command silently with a spinner; on failure dump tail of captured
# output. Output is fully logged to the install log.
#
# Usage: ui_spinner_run "Installing python3-pip" apt-get install -y python3-pip
ui_spinner_run() {
    local label="$1"; shift
    local tmpout
    tmpout=$(mktemp /tmp/eas-ui.XXXXXX) || tmpout=/tmp/eas-ui.$$
    ( "$@" ) >"$tmpout" 2>&1 &
    local pid=$!
    show_spinner "$pid" "$label"
    local rc=$?
    # Tee captured output into the log (stdout is the log after redirect).
    cat "$tmpout"
    if [ $rc -eq 0 ]; then
        echo_success "$label"
    else
        echo_error "$label (exit $rc)"
        _tty "  $(printf '\033[2m─ last 10 lines ───────────────\033[0m')"
        tail -n 10 "$tmpout" | while IFS= read -r line; do
            _tty "  $(printf '\033[2m%s\033[0m' "$line")"
        done
    fi
    rm -f "$tmpout"
    return $rc
}

# ── Inline ANSI progress bar (single-line, overwrite) ──────────────────────
# Prints a styled bar to /dev/tty using \r so consecutive calls update in
# place. Pass `ui_progress_end` once done to advance the cursor.
ui_progress_bar() {
    local pct="$1"
    local label="${2:-}"
    [ -z "$pct" ] && pct=0
    [ "$pct" -lt 0 ] && pct=0
    [ "$pct" -gt 100 ] && pct=100
    local width=32
    local filled=$(( pct * width / 100 ))
    local bar="" i
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=filled; i<width; i++)); do bar+="░"; done
    printf '\r  \033[1;36m%s\033[0m \033[1m%3d%%\033[0m  %s\033[K' \
        "$bar" "$pct" "$label" >/dev/tty 2>/dev/null || true
}
ui_progress_end() { printf '\n' >/dev/tty 2>/dev/null || true; }

# ── apt-get install with real progress ─────────────────────────────────────
# Uses `-o APT::Status-Fd=3` to get machine-parseable status from apt.
# Lines look like:
#   pmstatus:pkg:42.0000:Configuring pkg
#   dlstatus:1:30.4566:Retrieving file 1 of 5
# We render a progress bar based on those percentages.
#
# Usage: ui_apt_install pkg1 pkg2 ...
# Honours $APT_EXTRA_FLAGS (e.g. "--no-install-recommends").
ui_apt_install() {
    if [ $# -eq 0 ]; then return 0; fi
    local label="apt: ${*}"
    [ ${#label} -gt 60 ] && label="apt: ${1} (+$(( $# - 1 )) more)"
    echo_progress "Installing $# package(s): $*"

    # If not a TTY, fall back to plain apt-get install.
    if ! [ -w /dev/tty ]; then
        # shellcheck disable=SC2086
        DEBIAN_FRONTEND=noninteractive apt-get install -y ${APT_EXTRA_FLAGS:-} "$@"
        return $?
    fi

    # Run apt with status fd 3, pipe fd 3 to a parser.
    local rc=0
    {
        # shellcheck disable=SC2086
        DEBIAN_FRONTEND=noninteractive apt-get install -y \
            -o APT::Status-Fd=3 \
            -o Dpkg::Use-Pty=0 \
            ${APT_EXTRA_FLAGS:-} "$@" 3>&1 1>&2 2>&1 | \
        while IFS=: read -r kind pkg pct msg; do
            case "$kind" in
                pmstatus|dlstatus)
                    local p=${pct%%.*}
                    [ -z "$p" ] && p=0
                    ui_progress_bar "$p" "$kind ${pkg}: ${msg}"
                    ;;
                *)
                    : # ignore everything else
                    ;;
            esac
        done
    }
    rc=${PIPESTATUS[0]:-0}
    ui_progress_end
    if [ "$rc" -eq 0 ]; then
        echo_success "$label"
    else
        echo_error "$label failed (exit $rc)"
    fi
    return $rc
}

# ── pip install with progress ──────────────────────────────────────────────
# Pip's own --progress-bar is line-based; we just stream its stderr to the
# terminal so users see "Collecting / Downloading / Installing collected
# packages: …" in real time, while the log captures the full transcript.
#
# Usage: ui_pip_install -r requirements.txt
#        ui_pip_install some-package==1.2.3
# Requires $PIP to be set to the pip executable (defaults to "pip").
ui_pip_install() {
    local pip_bin="${PIP:-pip}"
    echo_progress "pip install $*"
    if ! [ -w /dev/tty ]; then
        "$pip_bin" install --progress-bar on "$@"
        return $?
    fi
    # Tee through awk so each line is also styled on /dev/tty.
    local rc=0
    "$pip_bin" install --progress-bar on "$@" 2>&1 | \
        while IFS= read -r line; do
            # Log full line.
            printf '%s\n' "$line"
            # Mirror styled summary lines to TTY.
            case "$line" in
                Collecting*|Downloading*|Installing*|Successfully*|Requirement*|Using*|Building*)
                    _tty "  $(printf '\033[2m▸\033[0m %s' "$line")"
                    ;;
                ERROR:*|*[Ww]arning:*)
                    _tty "  $(printf '\033[1;33m▸\033[0m %s' "$line")"
                    ;;
            esac
        done
    rc=${PIPESTATUS[0]:-0}
    if [ "$rc" -eq 0 ]; then
        echo_success "pip install $* — complete"
    else
        echo_error "pip install $* failed (exit $rc)"
    fi
    return $rc
}

# ── Completion card ────────────────────────────────────────────────────────
# Renders a Unicode-box completion banner on /dev/tty AND shows the legacy
# whiptail "*** COMPLETE ***" msgbox if whiptail is available, so both look
# and feel benefit.
#
# Usage: show_celebration "Body text" [title]
show_celebration() {
    local body="$1"
    local title="${2:-*** INSTALLATION COMPLETE ***}"
    local elapsed; elapsed=$(format_duration $(( $(date +%s) - START_TIME )))
    local log_path="${LOG_FILE:-/var/log/eas-install.log}"

    # 1. ANSI Unicode-box card.
    if _ui_tty_supports_color; then
        {
            printf '\n'
            printf '%s╭──────────────────────────────────────────────────────────────────╮%s\n' "$_UI_C1" "$NC"
            printf '%s│%s  %s%s%s\n' "$_UI_C1" "$NC" "$BOLD" "$title" "$NC"
            printf '%s├──────────────────────────────────────────────────────────────────┤%s\n' "$_UI_C1" "$NC"
            # Print body, wrapped naively at ~62 chars.
            while IFS= read -r line; do
                printf '%s│%s  %s\n' "$_UI_C1" "$NC" "$line"
            done <<<"$body"
            printf '%s│%s\n' "$_UI_C1" "$NC"
            printf '%s│%s  %sTotal time:%s %s\n' "$_UI_C1" "$NC" "$DIM" "$NC" "$elapsed"
            printf '%s│%s  %sLog:%s         %s\n' "$_UI_C1" "$NC" "$DIM" "$NC" "$log_path"
            printf '%s╰──────────────────────────────────────────────────────────────────╯%s\n' "$_UI_C1" "$NC"
            printf '\n'
        } >/dev/tty 2>/dev/null || true
    fi

    # 2. Legacy whiptail msgbox (preserves the existing modal experience).
    if command -v whiptail >/dev/null 2>&1; then
        whiptail --title "$title" \
                 --backtitle "$(whiptail_footer)" \
                 --msgbox "$body\n\nTotal time: $elapsed\nLog: $log_path" 14 70 2>/dev/null || true
    fi
}

# ── Exit trap ──────────────────────────────────────────────────────────────
# Used by both install.sh and update.sh. They each set FAILURE_TITLE before
# sourcing this file (defaulting to a generic message).
FAILURE_TITLE="${FAILURE_TITLE:-Script Failed}"
cleanup_on_exit() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo "[ERROR] Script exited with code $exit_code"
        if command -v whiptail >/dev/null 2>&1; then
            whiptail --title "$FAILURE_TITLE" \
                     --backtitle "$(whiptail_footer)" \
                     --msgbox "Script exited with code $exit_code\n\nCheck log for details:\n${LOG_FILE:-/var/log/eas-install.log}" 10 65 2>/dev/null || true
        fi
    fi
    stty sane </dev/tty 2>/dev/null || true
}

# Public alias for callers who want to register the trap explicitly.
ui_install_traps() {
    trap cleanup_on_exit EXIT
    trap 'exit 130' INT TERM
}
