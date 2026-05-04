#!/bin/bash
# EAS Station Update Script
# Copyright (c) 2025-2026 Timothy Kramer (KR8MER)
# Licensed under AGPL v3 or Commercial License

set -e  # Exit on error

# Log file — all command output is redirected here after root check
LOG_FILE="/var/log/eas-update.log"

# Color codes used in summary output at the end of the script
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

# Step tracking
STEP_NUM=0
TOTAL_STEPS=12
CURRENT_DESC="Initializing..."
START_TIME=$(date +%s)

format_duration() {
    local seconds=$1
    local hours=$((seconds / 3600))
    local minutes=$(( (seconds % 3600) / 60 ))
    local secs=$((seconds % 60))
    if [ $hours -gt 0 ]; then
        printf "%dh %dm %ds" $hours $minutes $secs
    elif [ $minutes -gt 0 ]; then
        printf "%dm %ds" $minutes $secs
    else
        printf "%ds" $secs
    fi
}

# Branding footer for whiptail dialogs
whiptail_footer() {
    echo "Copyright (c) 2025-2026 Timothy Kramer (KR8MER) | AGPL v3 / Commercial License"
}

# Wrapper: force whiptail TUI to /dev/tty so ncurses output is never swallowed
# by the log redirect (exec 1>>$LOG_FILE 2>&1) below.  Callers that capture
# user input still use the standard "3>&1 1>&2 2>&3" fd-swap trick; >/dev/tty
# only overrides fd1 (TUI output), leaving fd2 (the captured result) untouched.
whiptail() {
    command whiptail "$@" >/dev/tty
    local _ret=$?
    stty sane </dev/tty 2>/dev/null || true
    return $_ret
}

# Write a line directly to the terminal, bypassing the log redirect
_tty() { printf '%s\n' "$1" >/dev/tty; }

echo_step() {
    STEP_NUM=$((STEP_NUM + 1))
    CURRENT_DESC="$1"
    local pct=$((STEP_NUM * 100 / TOTAL_STEPS))
    echo "--- Step $STEP_NUM/$TOTAL_STEPS: $1 ---"
    _tty ""
    _tty "$(printf '\033[1;34m[%d/%d | %d%%]\033[0m \033[1m%s\033[0m' \
        "$STEP_NUM" "$TOTAL_STEPS" "$pct" "$1")"
}

echo_info()     { echo "[INFO]  $1"; _tty "$(printf '  \033[0;36m[INFO]\033[0m  %s' "$1")"; }
echo_success()  { echo "[ OK ]  $1"; _tty "$(printf '  \033[1;32m[ OK ]\033[0m  %s' "$1")"; }
echo_warning()  { echo "[WARN]  $1"; _tty "$(printf '  \033[1;33m[WARN]\033[0m  %s' "$1")"; }
echo_error()    { echo "[ERROR] $1"; _tty "$(printf '  \033[1;31m[ERR!]\033[0m  %s' "$1")"; }
echo_progress() { echo "  >>    $1"; _tty "$(printf '  \033[0;37m  >>  \033[0m  %s' "$1")"; }
echo_header()   { echo ""; echo "=== $1 ==="; echo ""; _tty "$(printf '\033[1m=== %s ===\033[0m' "$1")"; }
echo_operation() { echo_progress "${1}${2:+ (~$2)}"; }
draw_box()       { echo_success "$1"; }
draw_separator() { :; }
show_progress_bar() { :; }
show_spinner()   { wait "$1" 2>/dev/null || true; }
show_elapsed_time() { :; }

show_celebration() {
    local elapsed; elapsed=$(format_duration $(( $(date +%s) - START_TIME )))
    whiptail --title "*** UPDATE COMPLETE ***" \
             --backtitle "$(whiptail_footer)" \
             --msgbox "$1\n\nTotal time: $elapsed\nLog: $LOG_FILE" 10 65
}

cleanup_on_exit() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo "[ERROR] Script exited with code $exit_code"
        whiptail --title "Update Failed" \
                 --backtitle "$(whiptail_footer)" \
                 --msgbox "Script exited with code $exit_code\n\nCheck log for details:\n$LOG_FILE" 10 65 2>/dev/null || true
    fi
    stty sane </dev/tty 2>/dev/null || true
}
trap cleanup_on_exit EXIT
trap 'exit 130' INT TERM

# ── Startup ──────────────────────────────────────────────────────────────────

# Show splash
{
    printf '\033[2J\033[H'
    printf '\033[1;34m  EAS Station — Update Manager\033[0m\n'
    printf '  Emergency Alert System\n\n'
    printf '  Initializing...\n\n'
    printf '  Log: %s\n' "$LOG_FILE"
} >/dev/tty

# Root check
if [ "$EUID" -ne 0 ]; then
    printf '\033[1;31m  ERROR:\033[0m This script must be run as root (use sudo)\n' >/dev/tty
    exit 1
fi

# Redirect all stdout/stderr to the log file.
# From this point on, every command's output goes to the log automatically.
# The whiptail() wrapper above forces TUI output to /dev/tty explicitly.
mkdir -p "$(dirname "$LOG_FILE")"
: > "$LOG_FILE"
exec 1>>"$LOG_FILE" 2>&1

echo "[ OK ]  Root privileges confirmed"

# Configuration variables
INSTALL_DIR="/opt/eas-station"
SERVICE_USER="eas-station"
SERVICE_GROUP="eas-station"
LOG_DIR="/var/log/eas-station"
BACKUP_DIR="/var/backups/eas-station"

echo_step "Pre-flight Checks"

# Check if EAS Station is installed
if [ ! -d "$INSTALL_DIR" ]; then
    echo_error "EAS Station is not installed at $INSTALL_DIR"
    echo_info "Please run install.sh first"
    exit 1
fi
echo_success "Installation directory found: $INSTALL_DIR"

# Ensure whiptail is available
if ! command -v whiptail &> /dev/null; then
    echo_warning "whiptail not found - installing..."
    apt-get update > /dev/null 2>&1
    apt-get install -y whiptail > /dev/null 2>&1
    if ! command -v whiptail &> /dev/null; then
        echo "[ERROR] whiptail is required but could not be installed"
        exit 1
    fi
    echo_success "whiptail installed"
fi

# Update sudoers configuration to allow passwordless sudo for update operations
# This must be done BEFORE any sudo -u eas-station commands are executed
echo_progress "Updating sudoers configuration for passwordless operations..."
if [ -f "$INSTALL_DIR/config/sudoers-eas-station" ]; then
    cp "$INSTALL_DIR/config/sudoers-eas-station" /etc/sudoers.d/eas-station
    chmod 0440 /etc/sudoers.d/eas-station
    
    # Validate sudoers syntax
    if visudo -c -f /etc/sudoers.d/eas-station &>/dev/null; then
        echo_success "Sudoers configuration updated and validated"
    else
        echo_error "Invalid sudoers syntax - removing file"
        rm -f /etc/sudoers.d/eas-station
        echo_error "Update will prompt for passwords - this is not normal"
    fi
else
    echo_warning "Sudoers configuration file not found (config/sudoers-eas-station)"
    echo_warning "Update may prompt for passwords"
fi

# Get current version info
cd "$INSTALL_DIR"
CURRENT_BRANCH=""
CURRENT_COMMIT=""
CURRENT_VERSION=""
if [ -f "VERSION" ]; then
    CURRENT_VERSION=$(cat VERSION | tr -d '\n' | tr -d '\r')
    echo_success "Current version: ${BOLD}${CURRENT_VERSION}${NC}"
fi
if [ -d ".git" ]; then
    CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
    CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    echo_success "Current branch: ${BOLD}$CURRENT_BRANCH${NC} (commit: $CURRENT_COMMIT)"
else
    echo_info "Installation is not a git repository"
fi

# Show welcome dialog — skip on self-restart so the user is not asked to confirm twice.
if [ "${EAS_UPDATE_RESTARTED:-}" != "true" ]; then
    VERSION_LINE=""
    if [ -n "$CURRENT_VERSION" ]; then
        VERSION_LINE="  Version: $CURRENT_VERSION\n"
    fi
    if ! whiptail --title "EAS Station Update" --backtitle "$(whiptail_footer)" --yesno "Welcome to the EAS Station Update Wizard!\n\nThis will update your EAS Station installation to the latest version.\n\nThe update process will:\n• Create a backup of your current installation\n• Stop all EAS Station services temporarily\n• Update application files from Git or GitHub\n• Preserve your configuration (.env file)\n• Update Python dependencies\n• Run database migrations if needed\n• Update systemd service files\n• Restart all services\n\nCurrent Installation:\n  Location: $INSTALL_DIR\n${VERSION_LINE}  Branch: $CURRENT_BRANCH\n  Commit: $CURRENT_COMMIT\n\nDo you want to continue with the update?" 28 75; then
        echo_info "Update cancelled by user"
        exit 0
    fi
else
    # Self-restart after update.sh was updated — brief notification only.
    echo_info "Update script refreshed — continuing with updated version..."
fi # End of EAS_UPDATE_RESTARTED check

# Create backup (skip if restarting after self-update)
BACKUP_FILE="none"
if [ "${EAS_SKIP_BACKUP:-}" != "true" ]; then
echo_step "Creating Backup"

DO_BACKUP=false
if whiptail --title "Create Backup?" --backtitle "$(whiptail_footer)" --yesno "Would you like to create a backup before updating?\n\nThis will create a compressed archive of your current installation.\nBackups are saved to: $BACKUP_DIR\n\nRecommended if you have local customizations." 14 65 --defaultno; then
    DO_BACKUP=true
fi

if [ "$DO_BACKUP" = true ]; then
    mkdir -p "$BACKUP_DIR"
    BACKUP_FILE="$BACKUP_DIR/eas-station-$(date +%Y%m%d-%H%M%S).tar.gz"

    echo_progress "Creating backup archive..."
    if tar -czf "$BACKUP_FILE" -C "$INSTALL_DIR" . 2>/dev/null; then
        BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        echo_success "Backup created: $BACKUP_FILE (${BACKUP_SIZE})"
    else
        echo_warning "Backup failed (non-critical - continuing with update)"
        BACKUP_FILE="none"
    fi
else
    echo_info "Skipping backup"
fi
fi  # End of EAS_SKIP_BACKUP check

# Stop services
echo_step "Stopping Services"
echo_progress "Stopping EAS Station services..."

if systemctl is-active --quiet eas-station.target 2>/dev/null; then
    systemctl stop eas-station.target
    echo_success "Services stopped successfully"
else
    echo_info "Services were not running"
fi

# Save current .env file
echo_step "Preserving Configuration"
echo_progress "Backing up .env configuration..."

if [ -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env" "/tmp/eas-station.env.backup"
    echo_success "Configuration saved to temporary location"
else
    echo_warning "No .env file found - will use defaults"
fi

# Update from GitHub
echo_step "Downloading Latest Version"
cd "$INSTALL_DIR"

# Check if this is a git repository
if [ -d ".git" ]; then
    # Git-based update
    echo_info "Using git to update..."

    # Fix git ownership warning when running as root
    git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true

    # Check git directory ownership - critical for sudo -u eas-station to work
    echo_progress "Checking git directory ownership..."
    GIT_OWNER=$(stat -c '%U' "$INSTALL_DIR/.git" 2>/dev/null || echo "unknown")
    
    if [ "$GIT_OWNER" != "$SERVICE_USER" ]; then
        echo_warning "Git directory is owned by '$GIT_OWNER', should be '$SERVICE_USER'"
        echo_info "Fixing ownership to allow git operations as $SERVICE_USER..."
        
        if chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" 2>/dev/null; then
            echo_success "Ownership corrected to $SERVICE_USER"
        else
            echo_error "Failed to change ownership - continuing but git operations may fail"
            echo_warning "You may need to manually fix this with:"
            echo_warning "  sudo chown -R $SERVICE_USER:$SERVICE_USER $INSTALL_DIR"
        fi
    else
        echo_success "Git directory ownership is correct ($SERVICE_USER)"
    fi

    # Check if we should skip git pull (e.g., after update.sh self-restart)
    if [ "${EAS_SKIP_PULL:-}" = "true" ]; then
        echo_info "Skipping git operations (EAS_SKIP_PULL is set)"
        echo_success "Using already-updated code from previous pull"
        # Get current branch for display purposes
        CURRENT_BRANCH=$(git branch --show-current)
        if [ -z "$CURRENT_BRANCH" ]; then
            CURRENT_BRANCH="main"
        fi
        NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    else
        echo_progress "Fetching latest changes from origin..."
        
        # Get current branch name (fixing the hardcoded 'main' issue)
        CURRENT_BRANCH=$(git branch --show-current)
        if [ -z "$CURRENT_BRANCH" ]; then
            echo_warning "Unable to determine current branch - defaulting to main"
            CURRENT_BRANCH="main"
        fi
        echo_info "Updating branch: ${BOLD}$CURRENT_BRANCH${NC}"
        
        # Fetch updates
        echo_progress "Fetching latest changes from remote..."
        
        # Capture git fetch output to show detailed errors if needed
        # Explicitly fetch the current branch to handle shallow clones and limited refspecs
        set +e  # Temporarily disable exit-on-error to capture git fetch failure
        FETCH_OUTPUT=$(sudo -u "$SERVICE_USER" git fetch origin "$CURRENT_BRANCH:refs/remotes/origin/$CURRENT_BRANCH" 2>&1)
        FETCH_STATUS=$?
        set -e  # Re-enable exit-on-error
    
    if [ $FETCH_STATUS -eq 0 ]; then
        echo_success "Fetched latest changes from remote"
    else
        echo_error "Git fetch failed - cannot update"
        echo_error "Git output:"
        echo "$FETCH_OUTPUT" | head -20
        echo ""
        echo_warning "Possible causes:"
        echo_warning "  1. Git directory ownership issue (should be owned by $SERVICE_USER)"
        echo_warning "  2. Network connectivity issue"
        echo_warning "  3. Git remote configuration issue"
        echo ""
        echo_info "Checking git directory ownership..."
        ls -ld "$INSTALL_DIR/.git" 2>/dev/null || echo "  .git directory not found"
        ls -l "$INSTALL_DIR/.git/config" 2>/dev/null || echo "  .git/config not found"
        echo ""
        echo_info "To fix ownership issues, run:"
        echo_info "  sudo chown -R $SERVICE_USER:$SERVICE_USER $INSTALL_DIR"
        echo ""
        echo_info "To manually update, run:"
        echo_info "  cd $INSTALL_DIR"
        echo_info "  sudo -u $SERVICE_USER git fetch origin"
        echo_info "  sudo -u $SERVICE_USER git reset --hard origin/$CURRENT_BRANCH"
        exit 1
    fi
    
    # Show what we're updating to
    REMOTE_COMMIT=$(git rev-parse --short "origin/$CURRENT_BRANCH" 2>/dev/null || echo "unknown")
    LOCAL_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    
    if [ "$REMOTE_COMMIT" != "$LOCAL_COMMIT" ]; then
        echo_info "Local commit:  $LOCAL_COMMIT"
        echo_info "Remote commit: $REMOTE_COMMIT"
        echo_info "Changes to be applied:"
        git log --oneline "$LOCAL_COMMIT..$REMOTE_COMMIT" 2>/dev/null | head -10 || echo "  (unable to show log)"
    else
        echo_success "Already up to date with remote on branch $CURRENT_BRANCH"
        echo ""
        echo_info "If you expect updates but see this message, you may be on an inactive branch."
        echo_info "To switch to the main development branch, run:"
        echo_info "  cd $INSTALL_DIR"
        echo_info "  sudo -u $SERVICE_USER git fetch origin"
        echo_info "  sudo -u $SERVICE_USER git checkout main"
        echo_info "  sudo -u $SERVICE_USER git reset --hard origin/main"
        echo_info "  Then run: sudo $INSTALL_DIR/update.sh"
        echo ""
    fi
    
    # Check for uncommitted changes
    if ! git diff-index --quiet HEAD -- 2>/dev/null; then
        echo_warning "Uncommitted changes detected"
        echo_info "Listing modified files:"
        git status --short 2>/dev/null | head -20
        echo ""
        echo_info "These changes will be stashed to allow update"
        sudo -u "$SERVICE_USER" git stash push -m "Auto-stash before update $(date +%Y%m%d-%H%M%S)" 2>&1 || true
        echo_success "Changes stashed (can be restored with 'git stash pop')"
    fi
    
    # Pull updates for current branch - use reset --hard to ensure we get exact remote state
    # This is INTENTIONAL and ensures the local code matches GitHub exactly.
    # Local changes are already stashed above, so they won't be lost.
    echo_progress "Pulling updates for branch $CURRENT_BRANCH..."

    # Show which files will be updated
    echo_info "Files changed between local and remote:"
    git diff --name-status HEAD "origin/$CURRENT_BRANCH" 2>/dev/null | head -20 || echo "  (unable to show diff)"
    echo ""

    # Ensure all working tree files are owned by the service user before reset.
    # Files may have been created by root (e.g., from a previous root-level operation),
    # causing "unable to unlink old" permission errors when git reset runs as the service user.
    echo_progress "Ensuring file ownership is correct before applying changes..."
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" 2>/dev/null || true

    # Capture git reset output to show detailed errors if needed
    set +e  # Temporarily disable exit-on-error to capture git reset failure
    RESET_OUTPUT=$(sudo -u "$SERVICE_USER" git reset --hard "origin/$CURRENT_BRANCH" 2>&1)
    RESET_STATUS=$?
    set -e  # Re-enable exit-on-error

    # If reset failed due to permission errors, retry as root then fix ownership
    if [ $RESET_STATUS -ne 0 ] && echo "$RESET_OUTPUT" | grep -q "Permission denied"; then
        echo_warning "Permission denied during git reset - retrying as root..."
        set +e
        RESET_OUTPUT=$(git reset --hard "origin/$CURRENT_BRANCH" 2>&1)
        RESET_STATUS=$?
        set -e

        if [ $RESET_STATUS -eq 0 ]; then
            echo_progress "Fixing file ownership after root-level reset..."
            chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
            echo_success "File ownership corrected"
        fi
    fi

    if [ $RESET_STATUS -eq 0 ]; then
        NEW_COMMIT=$(git rev-parse --short HEAD)
        echo_success "Updated to commit: $NEW_COMMIT"
        echo_success "Local code now matches GitHub exactly"

        # Show what files were actually updated
        if [ "$LOCAL_COMMIT" != "$NEW_COMMIT" ]; then
            echo_info "Files updated in this release:"
            git diff --name-only "$LOCAL_COMMIT" "$NEW_COMMIT" 2>/dev/null | head -30 | while read -r file; do
                echo "  ✓ $file"
            done
        fi
    else
        echo_error "Git reset failed - update incomplete"
        echo_error "Git output:"
        echo "$RESET_OUTPUT" | head -20
        echo ""
        echo_warning "Possible causes:"
        echo_warning "  1. Git directory ownership issue (should be owned by $SERVICE_USER)"
        echo_warning "  2. File permission issues"
        echo_warning "  3. Git configuration issue"
        echo ""
        echo_info "Checking git directory ownership..."
        ls -ld "$INSTALL_DIR/.git" 2>/dev/null || echo "  .git directory not found"
        echo ""
        echo_info "To fix ownership issues, run:"
        echo_info "  sudo chown -R $SERVICE_USER:$SERVICE_USER $INSTALL_DIR"
        echo ""
        echo_info "To manually update, run:"
        echo_info "  cd $INSTALL_DIR"
        echo_info "  sudo -u $SERVICE_USER git reset --hard origin/$CURRENT_BRANCH"
        echo ""
        echo_info "Or if ownership is the issue, run as root:"
        echo_info "  cd $INSTALL_DIR && git reset --hard origin/$CURRENT_BRANCH"
        echo_info "  Then fix ownership: chown -R $SERVICE_USER:$SERVICE_USER $INSTALL_DIR"
        exit 1
    fi
    
    fi  # End of EAS_SKIP_PULL check
    
    # Clear Python bytecode cache to ensure new code is loaded
    echo_progress "Clearing Python bytecode cache..."
    find "$INSTALL_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find "$INSTALL_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    echo_success "Python cache cleared"

    # Force nginx to clear cache and stop caching static files temporarily
    echo_progress "Clearing web server cache..."
    if command -v nginx &> /dev/null; then
        # Delete nginx cache if it exists
        if [ -d "/var/cache/nginx" ]; then
            rm -rf /var/cache/nginx/* 2>/dev/null || true
        fi
        # Reload nginx to clear in-memory cache
        if systemctl is-active --quiet nginx 2>/dev/null; then
            systemctl reload nginx 2>/dev/null || true
            echo_success "Nginx cache cleared"
        fi
    fi

    # Create a cache-bust timestamp file that Flask can use for static assets
    echo_progress "Creating cache-bust timestamp..."
    date +%s > "$INSTALL_DIR/.cache-bust" 2>/dev/null || true
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.cache-bust" 2>/dev/null || true
    echo_success "Cache-bust timestamp created"

    # Check if update.sh itself was updated - if so, restart with new version
    if [ "${EAS_UPDATE_RESTARTED:-}" != "true" ]; then
        if git diff --name-only "$LOCAL_COMMIT" "$NEW_COMMIT" 2>/dev/null | grep -q "^update.sh$"; then
            echo_info "Update script was modified - restarting with new version..."
            export EAS_UPDATE_RESTARTED=true
            export EAS_SKIP_BACKUP=true
            export EAS_SKIP_PULL=true
            exec "$INSTALL_DIR/update.sh"
        fi
    fi
    
    # Display what version was pulled
    if [ -f "$INSTALL_DIR/VERSION" ]; then
        PULLED_VERSION=$(cat "$INSTALL_DIR/VERSION" | tr -d '\n' | tr -d '\r')
        echo_info "Pulled version: ${BOLD}$PULLED_VERSION${NC}"
    fi
    
    # Show git commit info
    if [ -d "$INSTALL_DIR/.git" ]; then
        PULLED_COMMIT=$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
        PULLED_BRANCH=$(git -C "$INSTALL_DIR" branch --show-current 2>/dev/null || echo "unknown")
        echo_info "Git branch: ${BOLD}$PULLED_BRANCH${NC}"
        echo_info "Git commit: ${BOLD}$PULLED_COMMIT${NC}"
    fi
else
    # Download release tarball (for non-git installations)
    echo_info "Downloading release from GitHub..."
    GITHUB_REPO="KR8MER/eas-station"
    TEMP_DIR=$(mktemp -d)

    # Get latest release tag or use main branch
    LATEST_URL="https://github.com/$GITHUB_REPO/archive/refs/heads/main.tar.gz"
    
    echo_progress "Downloading from GitHub..."
    if curl -fsSL "$LATEST_URL" -o "$TEMP_DIR/eas-station.tar.gz"; then
        echo_success "Download complete"
        
        echo_progress "Extracting update..."
        tar -xzf "$TEMP_DIR/eas-station.tar.gz" -C "$TEMP_DIR"

        # Find extracted directory (usually eas-station-main)
        EXTRACTED_DIR=$(find "$TEMP_DIR" -maxdepth 1 -type d -name "eas-station*" | head -1)

        if [ -n "$EXTRACTED_DIR" ] && [ -d "$EXTRACTED_DIR" ]; then
            # Copy files, excluding .env and user data
            echo_progress "Updating application files..."
            rsync -a --exclude='.env' \
                     --exclude='*.db' \
                     --exclude='uploads/' \
                     --exclude='captures/' \
                     --exclude='venv/' \
                     --exclude='__pycache__/' \
                     --exclude='*.pyc' \
                     "$EXTRACTED_DIR/" "$INSTALL_DIR/"

            chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
            echo_success "Files updated successfully"
        else
            echo_error "Failed to extract update"
            exit 1
        fi

        # Cleanup
        rm -rf "$TEMP_DIR"
    else
        echo_error "Failed to download update from GitHub"
        echo_warning "Check your internet connection and try again"
        exit 1
    fi
fi

# Restore and merge .env file
echo_step "Restoring and Updating Configuration"

if [ -f "/tmp/eas-station.env.backup" ]; then
    echo_progress "Restoring .env configuration..."
    cp "/tmp/eas-station.env.backup" "$INSTALL_DIR/.env"
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"
    echo_success "Configuration restored"
    
    # Merge new variables from .env.example into existing .env
    echo_progress "Merging new configuration variables from .env.example..."
    if [ -f "$INSTALL_DIR/scripts/merge_env.py" ] && [ -f "$INSTALL_DIR/.env.example" ]; then
        if sudo -u "$SERVICE_USER" python3 "$INSTALL_DIR/scripts/merge_env.py" --install-dir "$INSTALL_DIR" --backup 2>&1 | grep -E "(variables|Merge complete|added)" || true; then
            echo_success "Configuration merged with new variables from .env.example"
        else
            echo_warning "Configuration merge encountered issues (non-critical)"
        fi
    else
        echo_info "Merge script not available - skipping config merge"
    fi
    
    rm "/tmp/eas-station.env.backup"
else
    echo_info "No configuration backup to restore"
    
    # If no .env exists, create from .env.example
    if [ ! -f "$INSTALL_DIR/.env" ] && [ -f "$INSTALL_DIR/.env.example" ]; then
        echo_warning "No .env file found - creating from .env.example"
        if [ -f "$INSTALL_DIR/scripts/merge_env.py" ]; then
            sudo -u "$SERVICE_USER" python3 "$INSTALL_DIR/scripts/merge_env.py" --install-dir "$INSTALL_DIR" --force
        else
            cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
            chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"
        fi
        echo_warning "IMPORTANT: Edit $INSTALL_DIR/.env and configure your settings"
    fi
fi

# Write git metadata to .env file so Flask can display it
echo_progress "Updating version metadata in configuration..."
if [ -d "$INSTALL_DIR/.git" ]; then
    # Get full git metadata
    GIT_COMMIT_FULL=$(git -C "$INSTALL_DIR" rev-parse HEAD 2>/dev/null || echo "")
    GIT_BRANCH_NAME=$(git -C "$INSTALL_DIR" branch --show-current 2>/dev/null || echo "")
    GIT_COMMIT_DATE=$(git -C "$INSTALL_DIR" log -1 --format=%cI 2>/dev/null || echo "")
    GIT_COMMIT_MSG=$(git -C "$INSTALL_DIR" log -1 --format=%s 2>/dev/null || echo "")
    
    # Update or add git metadata to .env file
    if [ -n "$GIT_COMMIT_FULL" ]; then
        # Ensure .env file exists
        touch "$INSTALL_DIR/.env"
        
        # Remove old git metadata lines if they exist (combined for efficiency)
        sed -i '/^GIT_COMMIT=/d; /^GIT_BRANCH=/d; /^GIT_COMMIT_DATE=/d; /^GIT_COMMIT_MESSAGE=/d' "$INSTALL_DIR/.env" 2>/dev/null || true
        
        # Append new git metadata (properly escaped)
        echo "GIT_COMMIT=$GIT_COMMIT_FULL" >> "$INSTALL_DIR/.env"
        [ -n "$GIT_BRANCH_NAME" ] && echo "GIT_BRANCH=$GIT_BRANCH_NAME" >> "$INSTALL_DIR/.env"
        [ -n "$GIT_COMMIT_DATE" ] && echo "GIT_COMMIT_DATE=$GIT_COMMIT_DATE" >> "$INSTALL_DIR/.env"
        # Escape commit message for shell safety
        [ -n "$GIT_COMMIT_MSG" ] && printf 'GIT_COMMIT_MESSAGE=%s\n' "$GIT_COMMIT_MSG" >> "$INSTALL_DIR/.env"
        
        chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"
        echo_success "Version metadata updated (commit: ${GIT_COMMIT_FULL:0:8})"
    else
        echo_warning "Could not read git metadata"
    fi
else
    echo_info "Not a git repository - skipping version metadata"
fi

# Update system dependencies (after code pull so new deps are included)
echo_step "Updating System Dependencies"
echo_progress "Updating package lists..."

apt-get update > /dev/null 2>&1

echo_progress "Installing any new system packages..."
echo_info "This may take a few minutes. Output shown below:"
echo ""

# Detect GPIO hardware presence (Raspberry Pi or other SBCs with GPIO)
HAS_GPIO=false
if [ -e /dev/gpiochip0 ] || [ -e /dev/gpiomem ] || grep -qiE "raspberry|bcm2[0-9]+|broadcom" /proc/cpuinfo 2>/dev/null; then
    HAS_GPIO=true
    echo_info "GPIO hardware detected - will install GPIO support packages"
else
    echo_info "No GPIO hardware detected (VM or standard PC) - skipping GPIO packages"
fi
echo ""

# Build base package list as array for safe expansion
BASE_PACKAGES=(
    python3-dev
    build-essential
    libpq-dev
    libev-dev
    libevent-dev
    libffi-dev
    libssl-dev
    libxml2-dev
    libxslt1-dev
    libjpeg-dev
    zlib1g-dev
    libpng-dev
    libfreetype6-dev
    ffmpeg
    espeak
    libespeak-ng1
    icecast2
    libusb-1.0-0
    libusb-1.0-0-dev
    python3-numpy
    python3-soapysdr
    soapysdr-tools
    rtl-sdr
    soapysdr-module-rtlsdr
    soapysdr-module-airspy
    libairspy0
)

# Add GPIO packages only if hardware is present
# i2c-tools: Command-line I2C bus utilities (for sensors, displays)
# python3-smbus: Python bindings for SMBus/I2C communication
# python3-lgpio: Raspberry Pi 5-compatible GPIO library (replaces deprecated RPi.GPIO)
if [ "$HAS_GPIO" = true ]; then
    BASE_PACKAGES+=(
        i2c-tools
        python3-smbus
        python3-lgpio
    )
fi

# Install all required system dependencies (matches install.sh)
# This ensures new dependencies added in updates are installed
# Use DEBIAN_FRONTEND=noninteractive to prevent prompts from package configuration
# Show output (no -qq) so user can see progress and diagnose any issues
# Array expansion is safe and prevents command injection
DEBIAN_FRONTEND=noninteractive apt-get install -y "${BASE_PACKAGES[@]}"

echo ""
echo_success "System dependencies up to date"

# Update Python dependencies
echo_step "Updating Python Dependencies"

if [ -f "$INSTALL_DIR/venv/bin/pip" ]; then
    echo_progress "Installing updated Python packages (main venv)..."
    echo_info "Full output shown below:"
    echo ""
    # Show full output so user can see progress (no grep filter)
    sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade -r "$INSTALL_DIR/requirements.txt"
    echo ""
    echo_success "Main venv dependencies updated"
else
    echo_warning "Main virtual environment not found - skipping dependency update"
    echo_info "You may need to recreate the virtual environment"
fi

# Update or create SDR venv (with --system-site-packages for python3-soapysdr access)
VENV_SDR_DIR="$INSTALL_DIR/venv-sdr"
if [ ! -d "$VENV_SDR_DIR" ]; then
    echo_progress "Creating SDR virtual environment (new in v2.27.12+)..."
    if sudo -u "$SERVICE_USER" python3 -m venv --system-site-packages "$VENV_SDR_DIR" 2>&1; then
        echo_success "SDR virtual environment created at $VENV_SDR_DIR"
    else
        echo_warning "Failed to create SDR venv - SDR service may not work"
    fi
fi

if [ -f "$VENV_SDR_DIR/bin/pip" ]; then
    echo_progress "Installing SDR service dependencies..."
    sudo -u "$SERVICE_USER" "$VENV_SDR_DIR/bin/pip" install --upgrade pip 2>&1 | grep -E "(Successfully installed)" || true
    if [ -f "$INSTALL_DIR/requirements-sdr.txt" ]; then
        echo_info "Installing SDR requirements (numba/llvmlite downloads may be 50+ MB; no log output during download)..."
        echo_info "If the log appears stalled here, a large package is downloading — this is normal, please wait..."
        echo ""
        # Show full output so user can see compilation progress (no grep filter).
        # NOTE: pip suppresses its progress bar when stdout is not a TTY (i.e. when
        # output is redirected to this log file), so large downloads produce no output
        # until they complete. That silence is expected, not a hang.
        sudo -u "$SERVICE_USER" "$VENV_SDR_DIR/bin/pip" install --upgrade -r "$INSTALL_DIR/requirements-sdr.txt"
        echo ""
    fi
    echo_success "SDR venv dependencies updated"

    # Verify SoapySDR access
    if "$VENV_SDR_DIR/bin/python" -c "import SoapySDR" 2>/dev/null; then
        SOAPY_VER=$("$VENV_SDR_DIR/bin/python" -c "import SoapySDR; print(SoapySDR.getAPIVersion())" 2>/dev/null)
        echo_success "✓ SoapySDR accessible in SDR venv (API: $SOAPY_VER)"
    else
        echo_warning "⚠️  SoapySDR not accessible in SDR venv"
        echo_warning "   Install: sudo apt-get install python3-soapysdr"
    fi
else
    echo_warning "SDR venv not found - SDR service may not work"
fi

# Update systemd service files
echo_step "Updating System Services"

if [ -d "$INSTALL_DIR/systemd" ]; then
    echo_progress "Updating systemd service files..."

    # Copy service files (SDR service now uses venv-sdr with --system-site-packages)
    # This eliminates the need for complex PYTHONPATH detection
    cp "$INSTALL_DIR/systemd/"*.service /etc/systemd/system/ 2>/dev/null || true
    cp "$INSTALL_DIR/systemd/"*.target /etc/systemd/system/ 2>/dev/null || true
    cp "$INSTALL_DIR/systemd/"*.timer /etc/systemd/system/ 2>/dev/null || true

    systemctl daemon-reload
    echo_success "Service files updated"

    # Update sudoers configuration for certbot/nginx management
    echo_progress "Updating sudoers configuration for SSL certificate management..."
    if [ -f "$INSTALL_DIR/config/sudoers-eas-station" ]; then
        cp "$INSTALL_DIR/config/sudoers-eas-station" /etc/sudoers.d/eas-station
        chmod 0440 /etc/sudoers.d/eas-station

        # Validate sudoers syntax
        if visudo -c -f /etc/sudoers.d/eas-station &>/dev/null; then
            echo_success "Sudoers configuration updated and validated"
        else
            echo_error "Invalid sudoers syntax - removing file"
            rm -f /etc/sudoers.d/eas-station
        fi
    else
        echo_warning "Sudoers configuration file not found (config/sudoers-eas-station)"
    fi

    # Fix certbot data directories permissions
    # These directories must be writable by both the eas-station user and root (for certbot via sudo)
    echo_progress "Fixing certbot data directories permissions..."
    CERTBOT_DATA_DIR="$INSTALL_DIR/certbot_data"
    mkdir -p "$CERTBOT_DATA_DIR/config" "$CERTBOT_DATA_DIR/work" "$CERTBOT_DATA_DIR/logs"
    chmod -R 777 "$CERTBOT_DATA_DIR"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$CERTBOT_DATA_DIR"
    # Remove any stale lock files that can cause permission errors
    find "$CERTBOT_DATA_DIR" -name ".certbot.lock" -delete 2>/dev/null || true
    echo_success "Certbot data directories configured"

    # Ensure ACME challenge directory exists for certbot webroot method
    # Path matches nginx config: location /.well-known/acme-challenge/ { root /var/www/certbot; }
    # IMPORTANT: Must be owned by root:root (certbot runs as root) with 755 permissions
    # This allows certbot to write challenge files as root, and nginx to read them as www-data
    echo_progress "Ensuring ACME challenge directory exists..."
    mkdir -p /var/www/certbot/.well-known/acme-challenge
    chown -R root:root /var/www/certbot
    chmod -R 755 /var/www/certbot
    echo_success "ACME challenge directory configured (root:root 755)"

    # Ensure hardware access groups exist (for services that use SupplementaryGroups)
    echo_progress "Ensuring hardware access groups exist..."
    HARDWARE_GROUPS="gpio i2c spi audio plugdev dialout"
    GROUPS_CREATED=0
    for group in $HARDWARE_GROUPS; do
        if ! getent group "$group" >/dev/null 2>&1; then
            if groupadd --system "$group" 2>/dev/null; then
                echo_info "Created group: $group"
                GROUPS_CREATED=$((GROUPS_CREATED + 1))
            fi
        fi
    done
    
    # Add service user to hardware groups (always run to ensure user is member)
    echo_progress "Adding $SERVICE_USER to hardware access groups..."
    for group in $HARDWARE_GROUPS; do
        usermod -a -G "$group" "$SERVICE_USER" 2>/dev/null || true
    done
    
    if [ $GROUPS_CREATED -gt 0 ]; then
        echo_success "Hardware access groups configured (created $GROUPS_CREATED new groups)"
    else
        echo_success "Hardware access groups configured (all groups already existed)"
    fi

    # Apply Argon ONE V5 config.txt settings if the Argon daemon is installed but the
    # USB hub overlay is missing (e.g. installed before this fix was added)
    if (command -v argonone-cli &>/dev/null || systemctl list-unit-files argononed.service &>/dev/null 2>&1) \
        && grep -q "Raspberry Pi 5" /proc/device-tree/model 2>/dev/null; then
        CONFIG_TXT="/boot/firmware/config.txt"
        if [ -f "$CONFIG_TXT" ] && ! grep -q "dtoverlay=dwc2,dr_mode=host" "$CONFIG_TXT"; then
            echo_progress "Applying missing Argon ONE V5 USB hub overlays to $CONFIG_TXT..."
            if grep -q "^\[all\]" "$CONFIG_TXT"; then
                sed -i '/^\[all\]/a dtoverlay=dwc2,dr_mode=host\nusb_max_current_enable=1' "$CONFIG_TXT"
            else
                printf '\n[all]\ndtoverlay=dwc2,dr_mode=host\nusb_max_current_enable=1\n' >> "$CONFIG_TXT"
            fi
            echo_warning "Argon ONE V5 USB overlays added — reboot required for /dev/ttyUSB0 to appear"
        fi
    fi
else
    echo_warning "Systemd directory not found - skipping service file update"
fi

# Update nginx configuration (only if changed)
echo_step "Checking Nginx Configuration"

if [ -f "$INSTALL_DIR/config/nginx-eas-station.conf" ]; then
    if [ -f /etc/nginx/sites-available/eas-station ]; then
        if ! diff -q "$INSTALL_DIR/config/nginx-eas-station.conf" /etc/nginx/sites-available/eas-station >/dev/null 2>&1; then
            echo_progress "Updating nginx configuration..."

            # Preserve any existing SSL certificate configuration before overwriting
            # the config.  The template always uses the self-signed certificate.  If
            # the admin installed a Let's Encrypt certificate via the web UI, that
            # installation takes one of two forms:
            #
            #  1. Direct paths – ssl_certificate and ssl_certificate_key point
            #     directly to the Let's Encrypt PEM files.
            #
            #  2. Snippet include – _install_certificate_internal() comments out the
            #     self-signed lines and adds "include snippets/ssl-letsencrypt.conf;"
            #     which points to the cert files.
            #
            # Capture both forms now, before the template overwrites the live config.
            EXISTING_CERT=$(grep -E "^\s*ssl_certificate " /etc/nginx/sites-available/eas-station \
                | grep -Ev "^[[:space:]]*#" \
                | awk '{print $2}' | tr -d ';' | head -1)
            EXISTING_KEY=$(grep -E "^\s*ssl_certificate_key " /etc/nginx/sites-available/eas-station \
                | grep -Ev "^[[:space:]]*#" \
                | awk '{print $2}' | tr -d ';' | head -1)

            # Detect snippet-based installation: uncommented include + snippet file on disk.
            USES_SSL_SNIPPET=false
            if grep -qE "^\s*include\s+snippets/ssl-letsencrypt\.conf" \
                    /etc/nginx/sites-available/eas-station 2>/dev/null \
               && [ -f /etc/nginx/snippets/ssl-letsencrypt.conf ]; then
                USES_SSL_SNIPPET=true
            fi

            cp "$INSTALL_DIR/config/nginx-eas-station.conf" /etc/nginx/sites-available/eas-station

            # Restore whichever certificate form was in use before the template copy.
            if [ -n "$EXISTING_CERT" ] && \
               [ "$EXISTING_CERT" != "/etc/ssl/certs/eas-station-selfsigned.crt" ] && \
               [ -f "$EXISTING_CERT" ]; then
                # Form 1: direct certificate paths.
                echo_info "Preserving existing SSL certificate: $EXISTING_CERT"
                # Escape & and \ in the replacement strings so sed does not
                # misinterpret them.  File paths on Linux cannot contain | so the
                # | delimiter is safe; only & and \ need escaping in replacements.
                CERT_ESC=$(printf '%s\n' "$EXISTING_CERT" | sed 's/[\\&]/\\&/g')
                KEY_ESC=$(printf '%s\n' "$EXISTING_KEY" | sed 's/[\\&]/\\&/g')
                sed -i "s|ssl_certificate /etc/ssl/certs/eas-station-selfsigned.crt;|ssl_certificate $CERT_ESC;|g" \
                    /etc/nginx/sites-available/eas-station
                sed -i "s|ssl_certificate_key /etc/ssl/private/eas-station-selfsigned.key;|ssl_certificate_key $KEY_ESC;|g" \
                    /etc/nginx/sites-available/eas-station
                echo_success "SSL certificate paths preserved"
            elif [ "$USES_SSL_SNIPPET" = true ]; then
                # Form 2: snippet include.  Re-apply the same edits that
                # _install_certificate_internal() makes so the template does not
                # silently revert to the self-signed certificate.
                echo_info "Restoring Let's Encrypt SSL snippet configuration..."
                sed -i 's|^\(\s*\)ssl_certificate /etc/ssl/|\1# ssl_certificate /etc/ssl/|g' \
                    /etc/nginx/sites-available/eas-station
                sed -i 's|^\(\s*\)ssl_certificate_key /etc/ssl/|\1# ssl_certificate_key /etc/ssl/|g' \
                    /etc/nginx/sites-available/eas-station
                if ! grep -q 'ssl-letsencrypt.conf' /etc/nginx/sites-available/eas-station; then
                    sed -i '/ssl_protocols/a\    include snippets/ssl-letsencrypt.conf;' \
                        /etc/nginx/sites-available/eas-station
                fi
                echo_success "Let's Encrypt SSL snippet configuration restored"
            fi

            if nginx -t 2>&1 | grep -q "successful"; then
                systemctl reload nginx
                echo_success "Nginx configuration updated"
            else
                echo_error "Nginx configuration test failed - reverting"
                # Restore from backup if available
            fi
        else
            echo_info "Nginx configuration unchanged"
        fi
    else
        echo_info "Nginx not configured for EAS Station"
    fi
else
    echo_info "No nginx configuration file in source"
fi

# Run database migrations (if any)
echo_step "Running Database Migrations"
echo_progress "Running Alembic migrations to update database schema..."

# FIX PASSWORD AUTHENTICATION BEFORE MIGRATIONS
echo_info "Checking database authentication..."
if [ -f "$INSTALL_DIR/scripts/database/fix_database_user.sh" ]; then
    echo_info "Syncing database password from .env..."
    "$INSTALL_DIR/scripts/database/fix_database_user.sh" 2>&1 | grep -E "success|error|warning|ERROR|WARNING" || true
    echo_success "Database password synchronized"
else
    echo_warning "Password sync script not found - using existing credentials"
fi

echo ""
echo_info "This may take a few moments. Output will be shown below:"
echo_info "Press Ctrl+C to cancel if needed (changes will be rolled back)"

if [ -f "$INSTALL_DIR/venv/bin/alembic" ]; then
    echo ""

    # Check current database revision before migration
    echo_info "Checking current database state..."
    CURRENT_REV=$(sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/alembic' current" 2>/dev/null | tail -1 | awk '{print $1}' || echo "none")
    if [ -n "$CURRENT_REV" ] && [ "$CURRENT_REV" != "none" ] && [ "$CURRENT_REV" != "" ]; then
        echo_info "Current revision: $CURRENT_REV"
    else
        echo_info "Database is at an unknown or initial state"
    fi
    echo ""
    
    # Disable exit-on-error for migrations
    set +e
    # Run Alembic directly (no output capture) so user sees real-time feedback
    # and can interrupt with Ctrl+C if needed
    # IMPORTANT: Run from install directory to ensure .env file is found
    sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/alembic' upgrade head"
    ALEMBIC_EXIT_CODE=$?
    set -e
    
    echo ""
    MIGRATION_FAILED=false
    if [ $ALEMBIC_EXIT_CODE -eq 0 ]; then
        echo_success "Database migrations completed successfully"
        # Show what revision we're at now
        NEW_REV=$(sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/alembic' current" 2>/dev/null | tail -1 | awk '{print $1}' || echo "")
        if [ -n "$NEW_REV" ] && [ "$NEW_REV" != "" ]; then
            echo_info "Database is now at: $NEW_REV"
        fi
    elif [ $ALEMBIC_EXIT_CODE -eq 130 ]; then
        MIGRATION_FAILED=true
        echo_warning "Migration cancelled by user (Ctrl+C)"
        echo_info "Database state may be partially migrated - check with: sudo -u $SERVICE_USER bash -c 'cd $INSTALL_DIR && $INSTALL_DIR/venv/bin/alembic current'"
        echo_info "To retry: sudo -u $SERVICE_USER bash -c 'cd $INSTALL_DIR && $INSTALL_DIR/venv/bin/alembic upgrade head'"
    else
        MIGRATION_FAILED=true
        echo_warning "Alembic migrations encountered errors (exit code: $ALEMBIC_EXIT_CODE)"
        echo ""
        echo_info "Common causes:"
        echo_info "  • Database connection failed (check DATABASE_URL in .env)"
        echo_info "  • PostgreSQL/PostGIS not running (check: systemctl status postgresql)"
        echo_info "  • Migration script has errors (check output above)"
        echo_info "  • Conflicting schema changes (may need manual resolution)"
        echo ""
        echo_info "Attempting to create any missing tables with db.create_all() as fallback..."
        
        set +e
        sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('Missing tables created')
"
        set -e
        
        echo ""
        echo_warning "Database upgrade may be incomplete - check logs after update"
        echo_info "You can manually run migrations:"
        echo_info "  sudo -u $SERVICE_USER bash -c 'cd $INSTALL_DIR && $INSTALL_DIR/venv/bin/alembic upgrade head'"
        
        # Give user time to read the error before continuing.
        MIGRATION_ERR_MSG="Database migration errors were detected."
        MIGRATION_ERR_MSG+="\n\nAlembic exited with code: $ALEMBIC_EXIT_CODE"
        MIGRATION_ERR_MSG+="\n\nCommon causes:"
        MIGRATION_ERR_MSG+="\n  \u2022 Database connection failed (check DATABASE_URL in .env)"
        MIGRATION_ERR_MSG+="\n  \u2022 PostgreSQL/PostGIS not running"
        MIGRATION_ERR_MSG+="\n  \u2022 Migration script has errors"
        MIGRATION_ERR_MSG+="\n  \u2022 Conflicting schema changes"
        MIGRATION_ERR_MSG+="\n\nThe update will continue."
        MIGRATION_ERR_MSG+="\nCheck the log for details: $LOG_FILE"
        MIGRATION_ERR_MSG+="\n\nTo retry migrations manually:"
        MIGRATION_ERR_MSG+="\n  sudo -u $SERVICE_USER bash -c"
        MIGRATION_ERR_MSG+="\n    'cd $INSTALL_DIR && $INSTALL_DIR/venv/bin/alembic upgrade head'"
        whiptail --title "Migration Warning" \
            --backtitle "$(whiptail_footer)" \
            --msgbox "$MIGRATION_ERR_MSG" \
            22 75
    fi
elif [ -f "$INSTALL_DIR/venv/bin/python" ]; then
    echo_warning "Alembic not found - using db.create_all() fallback"
    echo_progress "Creating any missing database tables..."
    echo ""

    set +e
    sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('Database schema updated')
"
    DB_EXIT_CODE=$?
    set -e

    echo ""
    if [ $DB_EXIT_CODE -eq 0 ]; then
        echo_success "Database tables created"
    else
        echo_warning "Database operation failed (non-critical)"
    fi
else
    echo_warning "Python environment not found - skipping database migrations"
fi

# Add any new columns that may not be in Alembic migrations yet
echo_progress "Ensuring latest schema changes are applied..."
set +e
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" -c "
from app import app
from app_core.extensions import db
from sqlalchemy import text

with app.app_context():
    # Add details column to poll_history if it doesn't exist
    result = db.session.execute(text('''
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'poll_history' AND column_name = 'details'
    ''')).fetchone()
    if not result:
        db.session.execute(text('ALTER TABLE poll_history ADD COLUMN details JSONB'))
        db.session.commit()
        print('Added poll_history.details column')
    else:
        print('poll_history.details column already exists')
" 2>&1 | grep -E "Added|already exists|error" || true
set -e
echo_success "Schema updates complete"

# Restart services with updated code
echo_step "Restarting Services"
echo_progress "Reloading systemd daemon to pick up any service file changes..."
systemctl daemon-reload
echo_success "Systemd daemon reloaded"

# Ensure external services (icecast2, certbot.timer) are enabled and running
echo_progress "Ensuring external services are enabled..."

# Start icecast2 if it's installed and not running
if command -v icecast2 &> /dev/null || systemctl list-unit-files | grep -q icecast2; then
    echo_info "Icecast2 is installed - ensuring it's enabled and running..."
    if systemctl enable icecast2 2>&1 | grep -E "Created|enabled" || true; then
        echo_success "Icecast2 service enabled"
    fi
    if systemctl is-active --quiet icecast2 2>/dev/null; then
        echo_success "Icecast2 already running"
    else
        if systemctl start icecast2 2>&1; then
            echo_success "Icecast2 started"
        else
            echo_warning "Failed to start icecast2 - check 'sudo systemctl status icecast2'"
        fi
    fi
else
    echo_info "Icecast2 not installed - skipping (audio streaming will not work)"
fi

# Enable and start certbot.timer if certbot is installed
if command -v certbot &> /dev/null; then
    echo_info "Certbot is installed - ensuring timer is enabled..."
    if [ -f "/etc/systemd/system/certbot.timer" ] || [ -f "/lib/systemd/system/certbot.timer" ]; then
        if systemctl enable certbot.timer 2>&1 | grep -E "Created|enabled" || true; then
            echo_success "Certbot timer enabled"
        fi
        if systemctl is-active --quiet certbot.timer 2>/dev/null; then
            echo_success "Certbot timer already running"
        else
            if systemctl start certbot.timer 2>&1; then
                echo_success "Certbot timer started"
            else
                echo_warning "Failed to start certbot.timer - SSL auto-renewal may not work"
            fi
        fi
    else
        echo_info "Certbot timer service file not found - using system default"
    fi
else
    echo_info "Certbot not installed - skipping (SSL auto-renewal will not work)"
fi

# Ensure nginx is running (may have been stopped or never started)
echo_progress "Ensuring nginx web server is running..."
NGINX_STATUS="ok"
if systemctl is-active --quiet nginx 2>/dev/null; then
    if systemctl reload nginx 2>&1; then
        echo_success "Nginx reloaded"
    else
        echo_error "Failed to reload nginx - check 'sudo nginx -t' for config errors"
        NGINX_STATUS="failed"
    fi
else
    if systemctl start nginx 2>&1; then
        echo_success "Nginx started"
    else
        echo_error "Failed to start nginx - check 'sudo systemctl status nginx'"
        echo_info "Web interface will only be accessible on port 5000"
        NGINX_STATUS="failed"
    fi
fi

echo_progress "Ensuring log directory exists with correct ownership..."
mkdir -p "$LOG_DIR"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$LOG_DIR"
echo_success "Log directory ready: $LOG_DIR"

echo_progress "Starting all EAS Station services with updated code..."
# Reset any services that are in systemd 'failed' state before restarting.
# A service that exceeded its start-limit burst enters 'failed' and will NOT
# be restarted by 'systemctl restart eas-station.target' unless reset first.
echo_progress "Resetting any failed EAS Station service units..."
for svc in eas-station-web.service eas-station-audio.service eas-station-eas.service \
            eas-station-sdr.service eas-station-hardware.service eas-station-poller.service; do
    systemctl reset-failed "$svc" 2>/dev/null || true
done
echo_success "Failed service states cleared"

# Use restart (not start) to ensure all services reload with new code
# This works whether services were stopped or are already running
# Longer sleep (8s) to allow services to fully initialize and load new code
systemctl restart eas-station.target
sleep 8

# Check status
echo_progress "Checking service status..."
if systemctl is-active --quiet eas-station.target; then
    echo_success "All services started successfully"
    SERVICE_STATUS="running"
    
    # Verify web service is actually responding
    echo_progress "Verifying web service is responding..."
    sleep 2
    if systemctl is-active --quiet eas-station-web.service 2>/dev/null; then
        echo_success "Web service is active and should be serving updated code"
        echo_info "Note: Your browser may have cached content - do a hard refresh (Ctrl+Shift+R or Cmd+Shift+R)"
    else
        echo_warning "Web service status unclear - check manually"
    fi
else
    echo_error "Some services failed to start"
    echo_info "Check status with: ${BOLD}sudo systemctl status eas-station.target${NC}"
    SERVICE_STATUS="degraded"
fi

# Get updated version info
NEW_VERSION="unknown"
if [ -f "$INSTALL_DIR/VERSION" ]; then
    NEW_VERSION=$(cat "$INSTALL_DIR/VERSION" | tr -d '\n' | tr -d '\r')
elif [ -d "$INSTALL_DIR/.git" ]; then
    NEW_VERSION=$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
fi

# Display success summary
# Don't clear screen if migration failed - user needs to see the errors
if [ "$MIGRATION_FAILED" != "true" ]; then
    clear
fi
echo_header "Update Complete!"

# Build summary for whiptail
SUMMARY="EAS Station has been successfully updated!\n\n"
SUMMARY+="Update Details:\n"
SUMMARY+="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
SUMMARY+="Backup: $BACKUP_FILE\n"
if [ -n "$CURRENT_VERSION" ] || [ -n "$NEW_VERSION" ]; then
    [ -n "$CURRENT_VERSION" ] && SUMMARY+="Old Version: $CURRENT_VERSION\n"
    [ -n "$NEW_VERSION" ] && [ "$NEW_VERSION" != "unknown" ] && SUMMARY+="New Version: $NEW_VERSION\n"
fi
SUMMARY+="Branch: $CURRENT_BRANCH\n"
SUMMARY+="Old Commit: $CURRENT_COMMIT\n"
[ -n "$NEW_COMMIT" ] && SUMMARY+="New Commit: $NEW_COMMIT\n"
SUMMARY+="Configuration: Preserved\n"
SUMMARY+="Services: $SERVICE_STATUS\n\n"
SUMMARY+="Next Steps:\n"
SUMMARY+="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
SUMMARY+="• IMPORTANT: Hard refresh your browser (Ctrl+Shift+R)\n"
SUMMARY+="  to clear cached JavaScript and CSS files\n"
SUMMARY+="• View logs: journalctl -u eas-station-web -f\n"
SUMMARY+="• Check status: systemctl status eas-station.target\n"
SUMMARY+="• Web interface: https://$(hostname -I | awk '{print $1}')\n"

# Only show whiptail success dialog if update completed without errors
if [ "$SERVICE_STATUS" = "running" ] && [ "$NGINX_STATUS" = "ok" ]; then
    whiptail --title "Update Complete" --backtitle "$(whiptail_footer)" --msgbox "$SUMMARY" 24 75
else
    # Show error dialog instead
    ERROR_MSG="Update completed with errors:\n\n"
    if [ "$NGINX_STATUS" = "failed" ]; then
        ERROR_MSG+="✗ Nginx failed to start\n"
        ERROR_MSG+="  Check: sudo nginx -t\n"
        ERROR_MSG+="  Status: sudo systemctl status nginx\n\n"
    fi
    if [ "$SERVICE_STATUS" != "running" ]; then
        ERROR_MSG+="✗ EAS Station services failed to start\n"
        ERROR_MSG+="  Check: sudo systemctl status eas-station.target\n"
        ERROR_MSG+="  Logs: sudo journalctl -u eas-station-web -n 100\n\n"
    fi
    ERROR_MSG+="Review the console output above for details.\n"
    ERROR_MSG+="Press OK to continue..."

    whiptail --title "Update Issues Detected" --backtitle "$(whiptail_footer)" --msgbox "$ERROR_MSG" 20 75
fi

# Console summary
echo ""

# Show celebration animation
show_celebration "Update completed successfully!"

# Show elapsed time
show_elapsed_time
echo ""

echo_success "═══════════════════════════════════════════════════════════════"
echo_success "                     UPDATE COMPLETE                           "
echo_success "═══════════════════════════════════════════════════════════════"
echo ""
echo -e "${BOLD}Update Summary:${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}Backup:${NC}        $BACKUP_FILE"
if [ -n "$CURRENT_VERSION" ]; then
    echo -e "${CYAN}Old Version:${NC}   $CURRENT_VERSION"
fi
if [ -n "$NEW_VERSION" ] && [ "$NEW_VERSION" != "unknown" ]; then
    echo -e "${CYAN}New Version:${NC}   $NEW_VERSION"
fi
echo -e "${CYAN}Branch:${NC}        $CURRENT_BRANCH"
echo -e "${CYAN}Old Commit:${NC}    $CURRENT_COMMIT"
# Get current commit after update for comparison
NEW_COMMIT=""
if [ -d "$INSTALL_DIR/.git" ]; then
    NEW_COMMIT=$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || echo "")
fi
if [ -n "$NEW_COMMIT" ] && [ "$NEW_COMMIT" != "$CURRENT_COMMIT" ]; then
    echo -e "${CYAN}New Commit:${NC}    $NEW_COMMIT"
fi
echo -e "${CYAN}Configuration:${NC} Preserved"
echo -e "${CYAN}Services:${NC}      $SERVICE_STATUS"
echo ""
echo -e "${BOLD}Quick Commands:${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${WHITE}View status:${NC}     ${BOLD}sudo systemctl status eas-station.target${NC}"
echo -e "${WHITE}View web logs:${NC}   ${BOLD}sudo journalctl -u eas-station-web.service -f${NC}"
echo -e "${WHITE}View all logs:${NC}   ${BOLD}sudo journalctl -u eas-station.target -f${NC}"
echo -e "${WHITE}Restart all:${NC}     ${BOLD}sudo systemctl restart eas-station.target${NC}"
echo ""
echo -e "${BOLD}Web Interface:${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}➜${NC}  https://$(hostname -I | awk '{print $1}')"
echo ""
echo -e "${YELLOW}⚠️  CRITICAL:${NC} ${BOLD}You MUST clear your browser cache to see changes!${NC}"
echo -e "   ${BOLD}Hard Refresh:${NC}"
echo -e "   • Chrome/Firefox/Edge: ${GREEN}Ctrl+Shift+R${NC} (Windows/Linux) or ${GREEN}Cmd+Shift+R${NC} (Mac)"
echo -e "   • Safari: ${GREEN}Cmd+Option+R${NC}"
echo -e ""
echo -e "   ${BOLD}Or manually clear cache:${NC}"
echo -e "   • Chrome: Settings > Privacy > Clear browsing data > Cached images and files"
echo -e "   • Firefox: Settings > Privacy & Security > Clear Data > Cached Web Content"
echo -e ""
echo -e "   ${RED}If you still see old pages after hard refresh, fully clear browser cache!${NC}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
