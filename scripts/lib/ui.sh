# shellcheck shell=bash
# scripts/lib/ui.sh — shared terminal UI primitives for EAS Station's
# install.sh and update.sh.
#
# Goals:
#   * Old-school DOS-installer look: flat 16-color EGA/VGA palette (no
#     256-color gradients), double-line CP437 box art, classic `| / - \`
#     spinner, single-glyph status gutter. Blue-background "screens" are
#     used only at the two moments the script fully owns the terminal
#     (the opening banner, right after a screen clear, and the closing
#     completion card) — everywhere else runs on the terminal's own
#     background because real subprocess output (apt-get, pip, git,
#     alembic) is interleaved there and can emit its own color resets;
#     forcing a persistent blue background across that would silently
#     break the moment any of those tools resets SGR state.
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
# Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)
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

# Flat 16-color EGA/VGA text-mode palette — deliberately no 256-color codes
# anywhere in this file. This is the whole point of the DOS-installer look:
# a handful of flat, saturated colors, not a gradient.
_DOS_WHITE=$'\033[1;37m'   # bright white  — titles, emphasis
_DOS_YELLOW=$'\033[1;33m'  # bright yellow — subtitle, percentages, bar fill
_DOS_CYAN=$'\033[1;36m'    # light cyan    — secondary emphasis, spinner
_DOS_GREEN=$'\033[1;32m'   # bright green  — success glyph
_DOS_RED=$'\033[1;31m'     # bright red    — error glyph
_DOS_GREY=$'\033[0;37m'    # light grey    — box art, copyright, dim text
_DOS_BLUEBG=$'\033[44m'    # blue background — banner / completion screens only

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

# Run a command with its output visible on the terminal AND still captured
# in the log file. Both install.sh and update.sh redirect stdout/stderr to
# LOG_FILE early on (`exec 1>>"$LOG_FILE" 2>&1`), which silently swallows
# any subprocess that isn't explicitly re-routed like this one is -- a
# long-running step (pip install, apt-get install, alembic migrations)
# would otherwise print a "this may take a while, output shown below"
# message and then show nothing for its entire duration: indistinguishable
# from a hang, and in alembic's case defeating the point of running it
# uncaptured in the first place (so Ctrl+C can interrupt it).
#
# Falls back to running the command unmodified (log-only, i.e. today's
# behavior) when /dev/tty isn't writable, same as _tty()'s own fallback --
# e.g. a fully detached/unattended run.
#
# Exit code is the wrapped command's, not tee's -- relies on PIPESTATUS,
# which is bash-specific (both callers are already #!/bin/bash).
ui_stream() {
    if [ -w /dev/tty ] 2>/dev/null; then
        # `-w /dev/tty` only checks permission bits, not whether a real
        # controlling terminal is attached (e.g. under some service/sandbox
        # contexts /dev/tty exists and is "writable" but has no backing
        # terminal). tee's own stderr is silenced so that case degrades to
        # "log-only" quietly instead of printing "tee: /dev/tty: No such
        # device or address" on every line; the wrapped command's real
        # stderr is unaffected since it was already merged into stdout by
        # the `2>&1` before the pipe.
        "$@" 2>&1 | tee -a /dev/tty 2>/dev/null
        return "${PIPESTATUS[0]}"
    fi
    "$@"
}

# Echo an already-captured block of text (e.g. `git fetch` output stashed in
# a variable for error handling) to both stdout -- which is the log file,
# via the install/update scripts' `exec 1>>LOG 2>&1` -- and the terminal.
# Unlike ui_stream(), there's no live command to pipe here; the output was
# already captured earlier (often filtered with `head -N` first), so this
# just fans the same already-truncated text out to /dev/tty too. Same silent
# log-only fallback as _tty()/ui_stream() when /dev/tty isn't writable.
# Usage: echo "$CAPTURED_OUTPUT" | head -20 | _tty_block
_tty_block() {
    local block
    block=$(cat)
    echo "$block"
    if [ -w /dev/tty ] 2>/dev/null; then
        printf '%s\n' "$block" >>/dev/tty 2>/dev/null
    fi
}

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
    echo "Copyright (c) 2025-2026 EAS Station, LLC (KR8MER) | AGPL v3 / Commercial License"
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

# ── Fully-closed double-line box helpers ────────────────────────────────────
# A real DOS-era box (Turbo Vision, Norton Commander) closes on both sides --
# every content line ends with a right border aligned under the top/bottom
# rule. The rule length and each line's padding both derive from
# _DOS_BOX_WIDTH so they can never drift out of sync with each other.
#
# _dos_box_line takes the PLAIN (uncolored) text separately from the STYLED
# text actually printed, because padding has to be computed from visible
# character count -- ANSI color codes have zero visible width but do count
# toward a naive ${#string}, which would silently under-pad and misalign
# the right border the moment any content line used color.
_DOS_BOX_WIDTH=70

# `tr` mangles multi-byte UTF-8 characters even in a UTF-8 locale (GNU tr's
# SET1/SET2 handling isn't reliably multi-byte-aware) -- caught this the
# same way the progress-bar fill/empty split caught the same class of bug:
# by actually rendering the output, not just eyeballing the source. A bash
# loop concatenating the literal character, like the block/shade progress
# bar already does below, has no such byte-vs-character ambiguity.
_dos_box_rule() {
    local corner_l="$1" corner_r="$2"
    local fill="" i
    for ((i=0; i<_DOS_BOX_WIDTH; i++)); do fill+="═"; done
    printf '%s%s%s%s%s\n' "$_DOS_GREY" "$corner_l" "$fill" "$corner_r" "$NC$_DOS_BLUEBG"
}

# Usage: _dos_box_line "plain text for width" "styled text to print"
_dos_box_line() {
    local plain="$1" styled="$2"
    local visible=$(( ${#plain} + 2 ))  # +2 for the two leading spaces
    local pad=$(( _DOS_BOX_WIDTH - visible ))
    [ "$pad" -lt 0 ] && pad=0
    printf '%s║%s  %s%*s%s║%s\n' \
        "$_DOS_GREY" "$NC$_DOS_BLUEBG" "$styled" "$pad" "" "$_DOS_GREY" "$NC$_DOS_BLUEBG"
}

# ── Banner ─────────────────────────────────────────────────────────────────
# A fully-closed double-line CP437-style box framing the banner content --
# title, subtitle, version, log path, copyright -- all inside the same
# right-bordered frame.
#
# Usage: ui_banner "Bare Metal Installer"
ui_banner() {
    local subtitle="${1:-Emergency Alert System}"
    local version_line="${2:-}"
    local log_line="${3:-}"

    # Clear and home cursor, then paint the screen blue for this one-shot
    # opening screen. Safe here specifically because nothing else writes to
    # /dev/tty until this function returns -- see the note at the top of
    # this file about why that's NOT true for the rest of the run.
    _tty_raw $'\033[2J\033[H'

    if _ui_tty_supports_color; then
        {
            printf '%s' "$_DOS_BLUEBG"
            printf '\n'
            _dos_box_rule '╔' '╗'
            _dos_box_line "E A S   S T A T I O N" \
                "$(printf '%sE A S   S T A T I O N%s' "$_DOS_WHITE" "$NC$_DOS_BLUEBG")"
            _dos_box_rule '╠' '╣'
            _dos_box_line "" ""
            _dos_box_line "${subtitle}  -  Emergency Alert System" \
                "$(printf '%s%s%s  -  %sEmergency Alert System%s' \
                    "$_DOS_YELLOW" "$subtitle" "$NC$_DOS_BLUEBG" "$_DOS_CYAN" "$NC$_DOS_BLUEBG")"
            if [ -n "$version_line" ]; then
                _dos_box_line "$version_line" \
                    "$(printf '%s%s%s' "$_DOS_GREY" "$version_line" "$NC$_DOS_BLUEBG")"
            fi
            if [ -n "$log_line" ]; then
                _dos_box_line "Log: $log_line" \
                    "$(printf '%sLog:%s %s' "$_DOS_GREY" "$NC$_DOS_BLUEBG" "$log_line")"
            fi
            _dos_box_line "(c) 2025-2026 EAS Station, LLC (KR8MER) - AGPL v3 / Commercial" \
                "$(printf '%s(c) 2025-2026 EAS Station, LLC (KR8MER) - AGPL v3 / Commercial%s' \
                    "$_DOS_GREY" "$NC$_DOS_BLUEBG")"
            _dos_box_rule '╚' '╝'
            printf '\n'
            # Reset all attributes including the background before handing
            # control back -- everything printed after this point (step
            # headers, real command output) must NOT inherit blue.
            printf '%s' "$NC"
        } >/dev/tty 2>/dev/null || true
    else
        {
            printf '\n'
            printf '  EAS STATION\n'
            printf '  %s — Emergency Alert System\n' "$subtitle"
            [ -n "$version_line" ] && printf '  %s\n' "$version_line"
            [ -n "$log_line" ] && printf '  Log: %s\n' "$log_line"
            printf '  Copyright (c) 2025-2026 EAS Station, LLC (KR8MER) — AGPL v3 / Commercial\n'
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
    # Header bar with a tiny inline progress meter. Filled and empty
    # portions are separate strings (not one string sliced visually) so
    # each can carry its own color -- yellow fill, grey empty.
    local bar_width=20
    local filled=$(( pct * bar_width / 100 ))
    [ $filled -gt $bar_width ] && filled=$bar_width
    local bar_filled="" bar_empty=""
    local i
    for ((i=0; i<filled; i++)); do bar_filled+="█"; done
    for ((i=filled; i<bar_width; i++)); do bar_empty+="░"; done
    _tty "$(printf '%s║%s %s[%d/%d]%s [%s%s%s%s%s] %s%3d%%%s  %s%s%s' \
        "$_DOS_GREY" "$NC" "$_DOS_WHITE" "$STEP_NUM" "$TOTAL_STEPS" "$NC" \
        "$_DOS_YELLOW" "$bar_filled" "$_DOS_GREY" "$bar_empty" "$NC" \
        "$_DOS_YELLOW" "$pct" "$NC" "$_DOS_CYAN" "$1" "$NC")"
}

echo_info()     { echo "[INFO]  $1"; _tty "$(printf '  %si%s  %s' "$_DOS_CYAN" "$NC" "$1")"; }
echo_success()  { echo "[ OK ]  $1"; _tty "$(printf '  %s*%s  %s' "$_DOS_GREEN" "$NC" "$1")"; }
echo_warning()  { echo "[WARN]  $1"; _tty "$(printf '  %s!%s  %s' "$_DOS_YELLOW" "$NC" "$1")"; }
echo_error()    { echo "[ERROR] $1"; _tty "$(printf '  %sX%s  %s' "$_DOS_RED" "$NC" "$1")"; }
echo_progress() { echo "  >>    $1"; _tty "$(printf '  %s>>%s  %s' "$_DOS_GREY" "$NC" "$1")"; }
echo_header()   { echo ""; echo "=== $1 ==="; echo ""; _tty "$(printf '%s=== %s ===%s' "$_DOS_WHITE" "$1" "$NC")"; }
echo_operation() { echo_progress "${1}${2:+ (~$2)}"; }

# Legacy no-op shims kept for callers that referenced them.
draw_box()       { echo_success "$1"; }
draw_separator() { :; }
show_progress_bar() { :; }
show_elapsed_time() { :; }

# ── Spinner ─────────────────────────────────────────────────────────────────
# Watches an existing background PID and prints a classic 4-frame ASCII
# spinner (the `| / - \` every DOS TSR and installer used, long before
# Unicode braille spinners existed) with the elapsed time + supplied label
# until the PID exits. Returns the watched command's exit code.
# Backward-compatible signature: `show_spinner PID` (no label) still works.
show_spinner() {
    local pid="$1"
    local label="${2:-Working}"
    local frames=('|' '/' '-' '\')
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
        printf '\r  %s%s%s %s %s(%ds)%s\033[K' \
            "$_DOS_CYAN" "$f" "$NC" "$label" "$_DOS_GREY" "$elapsed" "$NC" >/dev/tty 2>/dev/null || true
        i=$((i + 1))
        sleep 0.2
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
        _tty "  $(printf '%s%s%s' "$_DOS_GREY" "── last 10 lines ──────────────" "$NC")"
        tail -n 10 "$tmpout" | while IFS= read -r line; do
            _tty "  $(printf '%s%s%s' "$_DOS_GREY" "$line" "$NC")"
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
    printf '\r  [%s%s%s] %s%3d%%%s  %s\033[K' \
        "$_DOS_YELLOW" "$bar" "$NC" "$_DOS_YELLOW" "$pct" "$NC" "$label" >/dev/tty 2>/dev/null || true
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
                    _tty "  $(printf '%s▸%s %s' "$_DOS_GREY" "$NC" "$line")"
                    ;;
                ERROR:*|*[Ww]arning:*)
                    _tty "  $(printf '%s▸%s %s' "$_DOS_YELLOW" "$NC" "$line")"
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
# Renders a fully-closed double-line CP437-box completion banner on
# /dev/tty (same box helpers and blue-background screen as ui_banner) AND
# shows the legacy whiptail "*** COMPLETE ***" msgbox if whiptail is
# available, so both look and feel benefit.
#
# Usage: show_celebration "Body text" [title]
show_celebration() {
    local body="$1"
    local title="${2:-*** INSTALLATION COMPLETE ***}"
    local elapsed; elapsed=$(format_duration $(( $(date +%s) - START_TIME )))
    local log_path="${LOG_FILE:-/var/log/eas-install.log}"

    # 1. Double-line CP437 box card on a blue-background screen.
    if _ui_tty_supports_color; then
        {
            printf '%s' "$_DOS_BLUEBG"
            printf '\n'
            _dos_box_rule '╔' '╗'
            _dos_box_line "$title" \
                "$(printf '%s%s%s' "$_DOS_WHITE" "$title" "$NC$_DOS_BLUEBG")"
            _dos_box_rule '╠' '╣'
            # Print body, wrapped naively at ~62 chars.
            while IFS= read -r line; do
                _dos_box_line "$line" \
                    "$(printf '%s%s%s' "$_DOS_CYAN" "$line" "$NC$_DOS_BLUEBG")"
            done <<<"$body"
            _dos_box_line "" ""
            _dos_box_line "Total time: $elapsed" \
                "$(printf '%sTotal time:%s %s' "$_DOS_YELLOW" "$NC$_DOS_BLUEBG" "$elapsed")"
            _dos_box_line "Log:         $log_path" \
                "$(printf '%sLog:%s         %s' "$_DOS_YELLOW" "$NC$_DOS_BLUEBG" "$log_path")"
            _dos_box_rule '╚' '╝'
            printf '\n'
            printf '%s' "$NC"
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
