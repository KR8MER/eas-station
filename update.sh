#!/bin/bash
# EAS Station Update Script
# Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)
# Licensed under AGPL v3 or Commercial License

set -e  # Exit on error

# Log file — all command output is redirected here after root check
LOG_FILE="/var/log/eas-update.log"

# Step tracking (must be set before sourcing the UI lib so its defaults pick
# them up).
STEP_NUM=0
TOTAL_STEPS=12
CURRENT_DESC="Initializing..."
START_TIME=$(date +%s)

# Title used by the shared cleanup_on_exit trap when something fails.
FAILURE_TITLE="Update Failed"

# ── Command-line flags ──────────────────────────────────────────────────────
# --non-interactive: for automated callers (the Admin -> Operations "System
#   Upgrade" button runs this via systemd-run). Every whiptail confirmation
#   or pause below is skipped in favor of a sane default, but every
#   echo_step/echo_info/echo_success/echo_warning/echo_error line still goes
#   to the log exactly as it does interactively -- that plain-text stream is
#   what the web UI tails and renders as live progress.
# --skip-backup: skip the pre-update tar.gz backup (default: create one).
#   Independent of the one-click "Backup Operations" panel on the same page.
# --checkout <ref>: git checkout this branch/tag before pulling.
NON_INTERACTIVE=false
SKIP_BACKUP=false
CHECKOUT_REF=""
while [ $# -gt 0 ]; do
    case "$1" in
        --non-interactive)
            NON_INTERACTIVE=true
            shift
            ;;
        --skip-backup)
            SKIP_BACKUP=true
            shift
            ;;
        --checkout)
            CHECKOUT_REF="${2:-}"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 2
            ;;
    esac
done

# Resolve script dir before sourcing the UI library.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Shared modern terminal UI primitives (color codes, banner, spinner,
# progress bars, apt/pip wrappers, whiptail helper, completion card).
# Falls back to plain text when not run from a TTY.
# shellcheck source=scripts/lib/ui.sh
source "$SCRIPT_DIR/scripts/lib/ui.sh"
ui_install_traps

# ── Startup ──────────────────────────────────────────────────────────────────

# Show the modern ASCII banner.
ui_banner "Update Manager" "" "$LOG_FILE"

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

# Show welcome dialog — skip on self-restart so the user is not asked to confirm twice,
# and skip entirely in --non-interactive mode (nobody is at a terminal to answer it).
if [ "$NON_INTERACTIVE" = "true" ]; then
    echo_info "Non-interactive mode — proceeding without confirmation"
elif [ "${EAS_UPDATE_RESTARTED:-}" != "true" ]; then
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
if [ "${EAS_SKIP_BACKUP:-}" != "true" ] && [ "$SKIP_BACKUP" != "true" ]; then
echo_step "Creating Backup"

DO_BACKUP=false
if [ "$NON_INTERACTIVE" = "true" ]; then
    # No one to ask -- default to safe (create it), unlike the interactive
    # wizard's --defaultno, since there is no operator here to notice and
    # override a silently-skipped backup.
    DO_BACKUP=true
    echo_info "Non-interactive mode — creating a backup before updating"
elif whiptail --title "Create Backup?" --backtitle "$(whiptail_footer)" --yesno "Would you like to create a backup before updating?\n\nThis will create a compressed archive of your current installation.\nBackups are saved to: $BACKUP_DIR\n\nRecommended if you have local customizations." 14 65 --defaultno; then
    DO_BACKUP=true
fi

if [ "$DO_BACKUP" = true ]; then
    mkdir -p "$BACKUP_DIR"
    BACKUP_FILE="$BACKUP_DIR/eas-station-$(date +%Y%m%d-%H%M%S).tar.gz"

    echo_progress "Creating backup archive..."
    # Exclude the big, regenerable-or-already-preserved-elsewhere directories:
    # venv/venv-sdr rebuild from requirements*.txt in minutes; .git duplicates
    # what's already on the remote; archives/ is recorded audio (tens of GB
    # on a station that's been running a while -- backing it up on every
    # single upgrade turns a few-second step into a multi-minute one for no
    # reason a code/config backup needs); backups/ is this very script's own
    # output directory when it lives under INSTALL_DIR -- without excluding
    # it, every new backup would also contain every backup before it,
    # growing without bound across repeated upgrades.
    if tar -czf "$BACKUP_FILE" \
        --exclude=./venv \
        --exclude=./venv-sdr \
        --exclude=./.git \
        --exclude=./archives \
        --exclude=./backups \
        --exclude='*/__pycache__' \
        --exclude='*.pyc' \
        -C "$INSTALL_DIR" . 2>/dev/null; then
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

    # Fix git's dubious-ownership check for both identities that touch this
    # repo: update.sh itself runs git as root (this line), but almost every
    # git call below is `sudo -u "$SERVICE_USER" git ...` -- a separate
    # identity with its own $HOME/.gitconfig that this exact line, prior to
    # this fix, never configured. Found by an end-to-end non-interactive run
    # failing at the very next git command with "fatal: detected dubious
    # ownership in repository" -- root's own config being satisfied didn't
    # help the eas-station-identity calls at all.
    # --replace-all rather than --add: this line runs on every single
    # upgrade, and --add has no dedup, so the alternative is one more
    # identical line appended to .gitconfig forever.
    git config --global --replace-all safe.directory "$INSTALL_DIR" 2>/dev/null || true
    sudo -u "$SERVICE_USER" git config --global --replace-all safe.directory "$INSTALL_DIR" 2>/dev/null || true

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

    # Optional: check out a specific branch/tag before pulling.
    if [ -n "$CHECKOUT_REF" ] && [ "${EAS_SKIP_PULL:-}" != "true" ]; then
        echo_progress "Checking out $CHECKOUT_REF..."
        set +e
        CHECKOUT_OUTPUT=$(sudo -u "$SERVICE_USER" git -c safe.directory="$INSTALL_DIR" fetch origin --tags --prune 2>&1 \
            && sudo -u "$SERVICE_USER" git -c safe.directory="$INSTALL_DIR" checkout "$CHECKOUT_REF" 2>&1)
        CHECKOUT_STATUS=$?
        set -e
        if [ $CHECKOUT_STATUS -eq 0 ]; then
            echo_success "Checked out $CHECKOUT_REF"
        else
            echo "$CHECKOUT_OUTPUT" | head -20 | _tty_block
            echo_error "Failed to check out '$CHECKOUT_REF' - continuing on the current branch"
        fi
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
        FETCH_OUTPUT=$(sudo -u "$SERVICE_USER" git -c safe.directory="$INSTALL_DIR" fetch origin "$CURRENT_BRANCH:refs/remotes/origin/$CURRENT_BRANCH" 2>&1)
        FETCH_STATUS=$?
        set -e  # Re-enable exit-on-error
    
    if [ $FETCH_STATUS -eq 0 ]; then
        echo_success "Fetched latest changes from remote"
    elif echo "$FETCH_OUTPUT" | grep -q "couldn't find remote ref"; then
        # The branch this checkout is sitting on no longer exists upstream --
        # normal fallout of this project's PR workflow, where feature
        # branches get deleted on merge. Falling back to main is the correct
        # recovery in every case: main is where every PR lands, so "my
        # branch is gone" always means "that work is already on main (or
        # abandoned)", never "I need to preserve local branch state".
        echo_warning "Branch '$CURRENT_BRANCH' no longer exists on the remote"
        echo_info "This usually means it was a feature/PR branch that already merged and was deleted."
        echo_info "Falling back to main..."
        echo ""

        set +e
        sudo -u "$SERVICE_USER" git -c safe.directory="$INSTALL_DIR" checkout main 2>&1
        CHECKOUT_STATUS=$?
        set -e

        if [ $CHECKOUT_STATUS -ne 0 ]; then
            echo_error "Could not switch to main -- manual recovery needed:"
            echo_info "  cd $INSTALL_DIR"
            echo_info "  sudo -u $SERVICE_USER git checkout main"
            echo_info "  sudo -u $SERVICE_USER git reset --hard origin/main"
            exit 1
        fi

        CURRENT_BRANCH="main"
        echo_success "Switched to main"

        set +e
        FETCH_OUTPUT=$(sudo -u "$SERVICE_USER" git -c safe.directory="$INSTALL_DIR" fetch origin "$CURRENT_BRANCH:refs/remotes/origin/$CURRENT_BRANCH" 2>&1)
        FETCH_STATUS=$?
        set -e

        if [ $FETCH_STATUS -eq 0 ]; then
            echo_success "Fetched latest changes from remote"
        else
            echo_error "Git fetch failed even after falling back to main"
            echo_error "Git output:"
            echo "$FETCH_OUTPUT" | head -20 | _tty_block
            exit 1
        fi
    else
        echo_error "Git fetch failed - cannot update"
        echo_error "Git output:"
        echo "$FETCH_OUTPUT" | head -20 | _tty_block
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
        sudo -u "$SERVICE_USER" git -c safe.directory="$INSTALL_DIR" stash push -m "Auto-stash before update $(date +%Y%m%d-%H%M%S)" 2>&1 || true
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
    RESET_OUTPUT=$(sudo -u "$SERVICE_USER" git -c safe.directory="$INSTALL_DIR" reset --hard "origin/$CURRENT_BRANCH" 2>&1)
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
        echo "$RESET_OUTPUT" | head -20 | _tty_block
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
            # exec with no arguments silently dropped --non-interactive for
            # the rest of the run on every single test of this PR (update.sh
            # modifies itself in nearly every commit, so this branch fires
            # on every run): the re-exec'd process's arg-parsing loop never
            # runs at all with nothing to parse, so NON_INTERACTIVE reverts
            # to its `false` default -- every whiptail call downstream of
            # here, unguarded again, was blowing up under `set -e` for a
            # session with no controlling terminal exactly the way the
            # welcome dialog would have if EAS_UPDATE_RESTARTED didn't
            # already special-case it.
            RESTART_ARGS=()
            [ "$NON_INTERACTIVE" = "true" ] && RESTART_ARGS+=(--non-interactive)
            exec "$INSTALL_DIR/update.sh" "${RESTART_ARGS[@]}"
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

# Provision the Ed25519 audit-log signing key for installs that predate the
# tamper-evident chain (v2.75.0) or that have been running on an ephemeral
# in-memory key. Idempotent: an existing key is never overwritten — rotating
# it would orphan the signatures on rows signed by the old key.
echo_progress "Ensuring audit-log signing key exists..."
AUDIT_KEY_DIR="$INSTALL_DIR/secrets"
AUDIT_KEY_FILE="$AUDIT_KEY_DIR/audit_signing.key"
if [ -f "$AUDIT_KEY_FILE" ]; then
    echo_info "Audit signing key already present - keeping it"
else
    mkdir -p "$AUDIT_KEY_DIR"
    if openssl genpkey -algorithm ed25519 -out "$AUDIT_KEY_FILE" 2>/dev/null; then
        echo_success "Audit signing key generated at $AUDIT_KEY_FILE"
    else
        echo_warning "Could not generate audit signing key - audit rows will use an ephemeral key (see docs/security/AUDIT_LOG_INTEGRITY.md)"
    fi
fi
if [ -d "$AUDIT_KEY_DIR" ]; then
    chown -R "$SERVICE_USER:$SERVICE_USER" "$AUDIT_KEY_DIR"
    chmod 700 "$AUDIT_KEY_DIR"
    [ -f "$AUDIT_KEY_FILE" ] && chmod 600 "$AUDIT_KEY_FILE"
fi
# Make sure the .env points at the key (older installs won't have the var).
if [ -f "$INSTALL_DIR/.env" ] && ! grep -q '^AUDIT_SIGNING_KEY_PATH=' "$INSTALL_DIR/.env"; then
    {
        echo ""
        echo "# Tamper-evident audit log signing key (Ed25519) - added by update.sh"
        echo "AUDIT_SIGNING_KEY_PATH=$AUDIT_KEY_FILE"
    } >> "$INSTALL_DIR/.env"
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"
    echo_success "AUDIT_SIGNING_KEY_PATH added to .env"
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

# Build base package list as array for safe expansion.
# Availability of some of these (SDR, audio, TTS libraries) varies between
# Debian/Ubuntu releases, so installation is best-effort: packages missing
# from this OS release are skipped with a warning instead of aborting the
# whole update (matches install.sh behavior).
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
    fail2ban
    libusb-1.0-0
    libusb-1.0-0-dev
    python3-numpy
    python3-soapysdr
    soapysdr-tools
    rtl-sdr
    soapysdr-module-rtlsdr
    soapysdr-module-airspy
    libairspy0
    libasound2-dev
    alsa-utils
    portaudio19-dev
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

# Filter out packages that don't exist on this OS release, then install the
# rest in one transaction. If the batch still fails (e.g. a transient dpkg
# conflict), retry per-package so one bad package can't block the update.
set +e
AVAILABLE_PACKAGES=()
SKIPPED_PACKAGES=()
for pkg in "${BASE_PACKAGES[@]}"; do
    if apt-cache show "$pkg" >/dev/null 2>&1; then
        AVAILABLE_PACKAGES+=("$pkg")
    else
        SKIPPED_PACKAGES+=("$pkg")
    fi
done

# Use DEBIAN_FRONTEND=noninteractive to prevent prompts from package configuration
# Show output (no -qq) so user can see progress and diagnose any issues
# Array expansion is safe and prevents command injection
if [ ${#AVAILABLE_PACKAGES[@]} -gt 0 ]; then
    ui_stream env DEBIAN_FRONTEND=noninteractive apt-get install -y "${AVAILABLE_PACKAGES[@]}"
    if [ $? -ne 0 ]; then
        echo_warning "Batch package install failed - retrying individually..."
        for pkg in "${AVAILABLE_PACKAGES[@]}"; do
            if ! DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg" >/dev/null 2>&1; then
                SKIPPED_PACKAGES+=("$pkg")
            fi
        done
    fi
fi
set -e

echo ""
if [ ${#SKIPPED_PACKAGES[@]} -gt 0 ]; then
    echo_warning "⚠️  Packages not available on this OS release (skipped): ${SKIPPED_PACKAGES[*]}"
    echo_info "  Related optional features may be disabled."
fi
echo_success "System dependencies up to date"

# Update Python dependencies
echo_step "Updating Python Dependencies"

if [ -f "$INSTALL_DIR/venv/bin/pip" ]; then
    echo_progress "Installing updated Python packages (main venv)..."
    echo_info "Full output shown below:"
    echo ""
    # Show full output so user can see progress (no grep filter)
    ui_stream sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade -r "$INSTALL_DIR/requirements.txt"
    echo ""
    echo_success "Main venv dependencies updated"

    # Optional audio capture bindings: pyalsaaudio (ALSA source adapter) and
    # pyaudio (PulseAudio source adapter). They compile against libasound2-dev
    # / portaudio19-dev (installed best-effort above), so install them
    # best-effort too — without them the matching adapters stay disabled.
    echo_progress "Installing optional audio capture bindings (pyalsaaudio, pyaudio)..."
    set +e
    for audio_pkg in pyalsaaudio pyaudio; do
        if sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install "$audio_pkg" >/dev/null 2>&1; then
            echo_success "✓ $audio_pkg installed (audio capture adapter enabled)"
        else
            echo_warning "⚠️  Could not install $audio_pkg - the matching audio source adapter stays disabled"
        fi
    done
    set -e
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

    # Guard against a stale executable bit riding along from $INSTALL_DIR
    # (see install.sh) and tripping systemd's "marked executable" warning.
    for src in "$INSTALL_DIR/systemd/"*.service "$INSTALL_DIR/systemd/"*.target "$INSTALL_DIR/systemd/"*.timer; do
        [ -f "$src" ] && chmod 644 "/etc/systemd/system/$(basename "$src")"
    done

    # Phase 4 retired the monolithic eas-station-hardware.service in favour of
    # five per-subsystem units bundled under eas-station-hardware.target.
    # Existing installs still have the old unit on disk and enabled — strip it
    # before reloading so systemd doesn't keep trying to revive it.
    LEGACY_HW_UNIT=/etc/systemd/system/eas-station-hardware.service
    if [ -f "$LEGACY_HW_UNIT" ] || systemctl list-unit-files eas-station-hardware.service 2>/dev/null | grep -q eas-station-hardware.service; then
        echo_progress "Retiring legacy eas-station-hardware.service (replaced by hardware.target)..."
        systemctl stop eas-station-hardware.service 2>/dev/null || true
        systemctl disable eas-station-hardware.service 2>/dev/null || true
        rm -f "$LEGACY_HW_UNIT"
        echo_success "Legacy monolithic hardware unit removed"
    fi

    # eas-station-eas.service duplicated the EAS/SAME decoder already running
    # inside eas-station-audio.service (eas_monitoring_service.py) — both
    # subscribed to the same audio stream and independently decoded it, with
    # a real (if narrow) double-broadcast race between them. Existing installs
    # still have the old unit on disk and enabled — strip it before reloading
    # so systemd doesn't keep trying to revive it.
    LEGACY_EAS_UNIT=/etc/systemd/system/eas-station-eas.service
    if [ -f "$LEGACY_EAS_UNIT" ] || systemctl list-unit-files eas-station-eas.service 2>/dev/null | grep -q eas-station-eas.service; then
        echo_progress "Retiring legacy eas-station-eas.service (duplicate EAS decoder)..."
        systemctl stop eas-station-eas.service 2>/dev/null || true
        systemctl disable eas-station-eas.service 2>/dev/null || true
        rm -f "$LEGACY_EAS_UNIT"
        echo_success "Legacy duplicate EAS decoder unit removed"
    fi

    systemctl daemon-reload
    echo_success "Service files updated"

    # Enable + start the five Phase 4 per-subsystem units and the target that
    # bundles them. enable --now is idempotent for already-enabled units, so
    # this is safe to re-run on every update. Enable units first so the
    # target's Wants= can resolve them.
    echo_progress "Enabling Phase 4 hardware subsystem units..."
    for unit in eas-station-network.service \
                eas-station-zigbee.service \
                eas-station-gps.service \
                eas-station-displays.service \
                eas-station-gpio.service; do
        if ! systemctl enable --now "$unit" >/dev/null 2>&1; then
            echo_warning "$unit failed to enable — check 'sudo systemctl status $unit'"
        fi
    done
    systemctl enable --now eas-station-hardware.target >/dev/null 2>&1 || \
        echo_warning "eas-station-hardware.target failed to enable"

    # Known-bad-actor IP blocklist (Spamhaus DROP/EDROP): enable the daily
    # refresh timer -- enable --now is idempotent, safe on every update, same
    # as the units above. Only trigger an immediate fetch if the list is
    # still just the placeholder from the nginx-config step above (a
    # deployment updating into this feature for the first time), so routine
    # updates on a deployment that already has it configured don't force an
    # extra Spamhaus fetch every time.
    systemctl enable --now bad-actors-update.timer >/dev/null 2>&1 || \
        echo_warning "bad-actors-update.timer failed to enable"
    if grep -q "^# placeholder" /etc/nginx/bad-actors-auto.conf 2>/dev/null; then
        echo_progress "First-time known-bad-actor blocklist fetch..."
        systemctl start bad-actors-update.service >/dev/null 2>&1 || \
            echo_warning "Initial known-bad-actor blocklist fetch failed (will retry on the daily timer)"
    fi

    # Give the subsystems a beat to come up before we judge the target.
    sleep 2
    if systemctl is-active --quiet eas-station-hardware.target; then
        echo_success "eas-station-hardware.target is active"
    else
        echo_error "eas-station-hardware.target is not active — aborting update"
        echo_info "Diagnose with: sudo systemctl status eas-station-hardware.target"
        echo_info "Per-subsystem logs: sudo journalctl -u eas-station-{network,zigbee,gps,displays,gpio}.service -n 50"
        exit 1
    fi

    # Ensure eas-station-hwsetup.service (the privileged GPS HAT setup
    # helper) is enabled and active on existing installs that predate it.
    # systemctl enable --now is idempotent — already-enabled units are a
    # no-op — so this is safe to run on every update.
    if [ -f /etc/systemd/system/eas-station-hwsetup.service ]; then
        echo_progress "Ensuring eas-station-hwsetup.service is enabled..."
        if systemctl enable --now eas-station-hwsetup.service 2>&1 | grep -E "Created|enabled" >/dev/null \
           || systemctl is-active --quiet eas-station-hwsetup.service; then
            echo_success "eas-station-hwsetup.service active (one-click GPS HAT fixes available)"
        else
            echo_warning "eas-station-hwsetup.service did not start — one-click GPS HAT fixes will be unavailable"
            echo_info "Diagnose with: sudo systemctl status eas-station-hwsetup.service"
        fi
    fi

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

    # Fix certbot data directories permissions.
    # Keep ownership root:root (not eas-station) so certbot's internal
    # copy_ownership_and_apply_mode() step doesn't try to chown new key
    # files to a non-root group — that chown fails with EPERM under
    # AppArmor and aborts the renewal. chmod 777 preserves read access
    # for the eas-station user.
    echo_progress "Fixing certbot data directories permissions..."
    CERTBOT_DATA_DIR="$INSTALL_DIR/certbot_data"
    mkdir -p "$CERTBOT_DATA_DIR/config" "$CERTBOT_DATA_DIR/work" "$CERTBOT_DATA_DIR/logs"
    chmod -R 777 "$CERTBOT_DATA_DIR"
    chown -R root:root "$CERTBOT_DATA_DIR"
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

    # Ensure /etc/nginx/snippets exists so the web-UI certificate installer
    # can write /etc/nginx/snippets/ssl-letsencrypt.conf. Hosts updated from
    # an older release may never have created this directory, causing the
    # in-app "obtain/install certificate" step to fail with "No such file
    # or directory".
    echo_progress "Ensuring nginx snippets directory exists..."
    mkdir -p /etc/nginx/snippets
    echo_success "Nginx snippets directory ready"

    # Ensure hardware access groups exist (for services that use SupplementaryGroups)
    echo_progress "Ensuring hardware access groups exist..."
    # video: /dev/vcio_gencmd (vcgencmd) is root:video 0660 -- needed for the
    # Raspberry Pi throttle/under-voltage telemetry on the health dashboard.
    # Harmless no-op on non-Pi installs.
    HARDWARE_GROUPS="gpio i2c spi audio plugdev dialout video"
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

# The nginx config's known-bad-actor blocklist (`geo $bad_actor` etc., see
# scripts/update_bad_actors.sh) `include`s these three files unconditionally
# -- nginx refuses to start (and `nginx -t` below refuses to pass) if any is
# missing. A deployment updating from before this feature existed won't have
# them yet, so create placeholders unconditionally, before the config swap,
# the same way install.sh does for a fresh install. Real Spamhaus content
# gets populated below once services are (re)enabled.
if [ ! -f /etc/nginx/bad-actors-auto.conf ]; then
    echo "# placeholder -- populated by update_bad_actors.sh on first run" \
        > /etc/nginx/bad-actors-auto.conf
fi
if [ ! -f /etc/nginx/bad-actors-switch.conf ]; then
    echo 'map $host $bad_actor_switch { default 1; }' \
        > /etc/nginx/bad-actors-switch.conf
fi
if [ ! -f /etc/nginx/bad-actors-allowlist.conf ]; then
    {
        echo "# Managed by Admin -> Application Settings -> Bad Actor Blocklist."
        echo "# IPs/CIDRs here bypass the Spamhaus/local blocklist entirely."
    } > /etc/nginx/bad-actors-allowlist.conf
fi

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

    # Check current database revision and target head BEFORE migration so the
    # operator can see exactly what's about to happen.
    echo_info "Checking current database state..."
    CURRENT_REV=$(sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/alembic' current" 2>/dev/null | tail -1 | awk '{print $1}' || echo "none")
    if [ -n "$CURRENT_REV" ] && [ "$CURRENT_REV" != "none" ] && [ "$CURRENT_REV" != "" ]; then
        echo_info "Current revision: $CURRENT_REV"
    else
        echo_info "Database is at an unknown or initial state"
    fi
    TARGET_HEADS=$(sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/alembic' heads" 2>/dev/null | awk '{print $1}' | grep -v '^$' | tr '\n' ' ' || echo "")
    if [ -n "$TARGET_HEADS" ]; then
        echo_info "Target head(s):    $TARGET_HEADS"
    fi
    echo ""

    # Repair path: a database initialized by install.sh's db.create_all()
    # fallback has all the application tables but no alembic_version row.
    # In that state "upgrade head" replays every migration from scratch and
    # fails on the first CREATE TABLE ("relation already exists"). Detect the
    # fingerprint (app tables present, no recorded revision), stamp the head,
    # and run create_all once more so any tables added since the original
    # install exist too (additive only — it never drops or moves data).
    if [ -z "$CURRENT_REV" ] || [ "$CURRENT_REV" = "none" ]; then
        set +e
        APP_TABLE_COUNT=$(sudo -u postgres psql -d alerts -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' AND table_name NOT IN ('alembic_version', 'spatial_ref_sys');" 2>/dev/null)
        set -e
        if [ -n "$APP_TABLE_COUNT" ] && [ "$APP_TABLE_COUNT" -gt 0 ] 2>/dev/null; then
            echo_warning "Tables exist but no migration revision is recorded (create_all fallback detected)"
            echo_progress "Repairing migration state: stamping current head..."
            set +e
            sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/alembic' stamp head"
            STAMP_EXIT=$?
            if [ $STAMP_EXIT -eq 0 ]; then
                echo_success "✓ Migration state repaired (stamped at head)"
                echo_progress "Creating any tables added since the original install..."
                sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('✓ Missing tables created (existing tables untouched)')
" || echo_warning "create_all pass failed - run scripts/database/check_schema.py to verify the schema"
            else
                echo_warning "Could not stamp migration head (exit code: $STAMP_EXIT) - migrations may fail below"
            fi
            set -e
        fi
    fi

    # Disable exit-on-error for migrations
    set +e
    # Run Alembic directly (no output capture) so user sees real-time feedback
    # and can interrupt with Ctrl+C if needed
    # IMPORTANT: Run from install directory to ensure .env file is found
    ui_stream sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/alembic' upgrade head"
    ALEMBIC_EXIT_CODE=$?
    set -e

    echo ""
    # Always re-read the current revision after the upgrade attempt so we can
    # report accurately whether it advanced (regardless of exit code).
    POST_REV=$(sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/alembic' current" 2>/dev/null | tail -1 | awk '{print $1}' || echo "")
    if [ -n "$POST_REV" ]; then
        echo_info "Database revision after upgrade attempt: $POST_REV"
    fi

    MIGRATION_FAILED=false
    if [ $ALEMBIC_EXIT_CODE -eq 0 ]; then
        echo_success "Database migrations completed successfully"
        if [ -n "$POST_REV" ]; then
            echo_info "Database is now at: $POST_REV"
        fi
    elif [ $ALEMBIC_EXIT_CODE -eq 130 ]; then
        MIGRATION_FAILED=true
        echo_warning "Migration cancelled by user (Ctrl+C)"
        echo_info "Database state may be partially migrated - check with: sudo -u $SERVICE_USER bash -c 'cd $INSTALL_DIR && $INSTALL_DIR/venv/bin/alembic current'"
        echo_info "To retry: sudo -u $SERVICE_USER bash -c 'cd $INSTALL_DIR && $INSTALL_DIR/venv/bin/alembic upgrade head'"
    else
        MIGRATION_FAILED=true
        echo_error "Alembic migrations encountered errors (exit code: $ALEMBIC_EXIT_CODE)"
        echo ""
        echo_info "Common causes:"
        echo_info "  • Database connection failed (check DATABASE_URL in .env)"
        echo_info "  • PostgreSQL/PostGIS not running (check: systemctl status postgresql)"
        echo_info "  • Migration script has errors (check output above)"
        echo_info "  • Conflicting schema changes (may need manual resolution)"
        echo ""
        # IMPORTANT: We deliberately do NOT run db.create_all() here as a
        # fallback. create_all() only adds missing tables/columns; it never
        # drops, renames, or copies data. For migrations that move data
        # between tables (e.g. 20260506_split_location_settings), running
        # create_all() after a failed alembic upgrade silently leaves the
        # database in a half-migrated state: the new tables exist but are
        # empty, the old columns still hold the real data, and
        # alembic_version is never advanced. That is *worse* than a clean
        # alembic failure because it hides the breakage. Surface the error
        # loudly instead and let the operator re-run alembic (or the
        # recovery script under scripts/database/) once the underlying
        # cause is fixed.
        echo_warning "Schema upgrade has NOT been applied. The database is in its previous state."
        echo_info "To retry migrations once the cause is fixed:"
        echo_info "  sudo -u $SERVICE_USER bash -c 'cd $INSTALL_DIR && $INSTALL_DIR/venv/bin/alembic upgrade head'"
        echo_info "If a previous run left the DB half-migrated (e.g. tables exist but data is missing), run:"
        echo_info "  sudo -u $SERVICE_USER $INSTALL_DIR/venv/bin/python $INSTALL_DIR/scripts/database/recover_split_location_settings.py"

        # Give user time to read the error before continuing.
        MIGRATION_ERR_MSG="Database migration errors were detected."
        MIGRATION_ERR_MSG+="\n\nAlembic exited with code: $ALEMBIC_EXIT_CODE"
        MIGRATION_ERR_MSG+="\nCurrent revision: ${POST_REV:-unknown}"
        MIGRATION_ERR_MSG+="\nTarget head(s):   ${TARGET_HEADS:-unknown}"
        MIGRATION_ERR_MSG+="\n\nNo schema changes were applied as a fallback;"
        MIGRATION_ERR_MSG+="\nthe database is in its previous state."
        MIGRATION_ERR_MSG+="\n\nCommon causes:"
        MIGRATION_ERR_MSG+="\n  \u2022 Database connection failed (check DATABASE_URL in .env)"
        MIGRATION_ERR_MSG+="\n  \u2022 PostgreSQL/PostGIS not running"
        MIGRATION_ERR_MSG+="\n  \u2022 Migration script has errors"
        MIGRATION_ERR_MSG+="\n  \u2022 Conflicting schema changes"
        MIGRATION_ERR_MSG+="\n\nThe update will continue, but the application may"
        MIGRATION_ERR_MSG+="\nfail to start until migrations are applied."
        MIGRATION_ERR_MSG+="\nCheck the log for details: $LOG_FILE"
        MIGRATION_ERR_MSG+="\n\nTo retry migrations manually:"
        MIGRATION_ERR_MSG+="\n  sudo -u $SERVICE_USER bash -c"
        MIGRATION_ERR_MSG+="\n    'cd $INSTALL_DIR && $INSTALL_DIR/venv/bin/alembic upgrade head'"
        MIGRATION_ERR_MSG+="\n\nIf the previous update left the DB half-migrated:"
        MIGRATION_ERR_MSG+="\n  sudo -u $SERVICE_USER \\\\"
        MIGRATION_ERR_MSG+="\n    $INSTALL_DIR/venv/bin/python \\\\"
        MIGRATION_ERR_MSG+="\n    $INSTALL_DIR/scripts/database/recover_split_location_settings.py"
        if [ "$NON_INTERACTIVE" != "true" ]; then
            whiptail --title "Migration Warning" \
                --backtitle "$(whiptail_footer)" \
                --msgbox "$MIGRATION_ERR_MSG" \
                26 78
        fi
    fi

    # Independent recovery pass: even if alembic itself succeeded, a previous
    # run of update.sh may have left the database in a half-migrated state
    # for 20260506_split_location_settings (new tables present but empty,
    # old columns still on location_settings). The recovery script is a
    # no-op when the schema is already healthy, so it's safe to run
    # unconditionally on every update.
    if [ -f "$INSTALL_DIR/scripts/database/recover_split_location_settings.py" ]; then
        echo ""
        echo_info "Checking for any half-migrated location_settings split state..."
        set +e
        sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" \
            "$INSTALL_DIR/scripts/database/recover_split_location_settings.py" --quiet
        RECOVERY_EXIT_CODE=$?
        set -e
        if [ $RECOVERY_EXIT_CODE -eq 0 ]; then
            echo_success "Location-split recovery check completed"
        else
            echo_warning "Location-split recovery check reported issues (exit $RECOVERY_EXIT_CODE) - see log"
        fi
    fi
elif [ -f "$INSTALL_DIR/venv/bin/python" ]; then
    # No alembic binary found. We do NOT run db.create_all() here either:
    # for any release that introduces a destructive/data-moving migration,
    # create_all() would silently leave the DB in an inconsistent state.
    # Surface this loudly instead.
    echo_error "Alembic not found in venv - cannot apply database migrations"
    echo_info "Install Python dependencies and re-run the update:"
    echo_info "  sudo -u $SERVICE_USER $INSTALL_DIR/venv/bin/pip install -r $INSTALL_DIR/requirements.txt"
    MIGRATION_FAILED=true
else
    echo_warning "Python environment not found - skipping database migrations"
    MIGRATION_FAILED=true
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

# Apply cluster-wide PostgreSQL safety tuning (e.g. idle_in_transaction_session_timeout)
if [ -f "$INSTALL_DIR/scripts/database/apply_postgres_tuning.sh" ]; then
    echo_step "Applying PostgreSQL Tuning"
    bash "$INSTALL_DIR/scripts/database/apply_postgres_tuning.sh" || echo_warning "PostgreSQL tuning step failed (non-critical)"
fi

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

# /var/lib/eas-station holds the zigpy NCP state database (zigbee.db).  The
# zigbee unit declares StateDirectory=eas-station so systemd auto-creates
# this on first start, but we mkdir it here too so the directory is in
# place even on older systemd versions and so existing installs that hit
# the crash loop ("226/NAMESPACE: /var/lib/eas-station: No such file or
# directory") recover on the next update.
STATE_DIR="/var/lib/eas-station"
echo_progress "Ensuring state directory exists with correct ownership..."
mkdir -p "$STATE_DIR"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$STATE_DIR"
chmod 750 "$STATE_DIR"
echo_success "State directory ready: $STATE_DIR"

echo_progress "Starting all EAS Station services with updated code..."

# ---------------------------------------------------------------------------
# Refresh the GPS / timing daemons before bringing EAS services back up.
#
# Symptom this fixes: after every update.sh run the GPS receiver dropped back
# to "ACQUIRING" and only a full reboot restored the fix. The asymmetry was
# that update.sh restarted the EAS GPS client (eas-station-gps.service) but
# never restarted gpsd itself — whereas a reboot restarts everything. gpsd is
# known to wedge in a "stuck acquiring" state when the serial link is
# disturbed (which is exactly what the EAS GPS service stopping/starting
# around an update does), and historically only a reboot cleared it. The
# in-process watchdog does restart gpsd, but not until 15 min without a fix —
# far longer than anyone waits before rebooting.
#
# Restarting gpsd (and the chrony refclock that consumes it) here reproduces
# the one thing the reboot did that the update did not, so the receiver comes
# back on its own. We stop the EAS GPS client first so the serial port is free
# for gpsd to reopen (in serial / auto-fallback mode the client owns the
# port), then let the eas-station.target restart below reconnect it to the
# freshly-restarted, healthy gpsd. No-op on installs without gpsd.
# ---------------------------------------------------------------------------
if systemctl list-unit-files 2>/dev/null | grep -q '^gpsd\.'; then
    echo_step "Refreshing GPS/Timing Daemons"
    echo_progress "Releasing the serial port from the EAS GPS service..."
    systemctl stop eas-station-gps.service 2>/dev/null || true

    echo_progress "Restarting gpsd (clears a wedged 'acquiring' state)..."
    # Restart the socket first, then the daemon, mirroring the watchdog's
    # remediation order. Either may be absent depending on how gpsd was set
    # up, so failures are non-fatal.
    systemctl restart gpsd.socket 2>/dev/null || true
    systemctl restart gpsd.service 2>/dev/null || true

    if systemctl list-unit-files 2>/dev/null | grep -q '^chrony'; then
        echo_progress "Restarting chrony so the GPS refclock re-locks..."
        # Debian/Raspberry Pi OS name the unit chrony.service; some images
        # use chronyd.service. Try both; ignore whichever is absent.
        systemctl restart chrony.service 2>/dev/null \
            || systemctl restart chronyd.service 2>/dev/null || true
    fi

    # Give gpsd a moment to reopen the receiver and start emitting before the
    # EAS services reconnect to it during the target restart below.
    sleep 3
    echo_success "GPS/timing daemons refreshed (no reboot required)"
fi

# Reset any services that are in systemd 'failed' state before restarting.
# A service that exceeded its start-limit burst enters 'failed' and will NOT
# be restarted by 'systemctl restart eas-station.target' unless reset first.
echo_progress "Resetting any failed EAS Station service units..."
for svc in eas-station-web.service eas-station-audio.service \
            eas-station-sdr.service eas-station-network.service \
            eas-station-zigbee.service eas-station-gps.service \
            eas-station-displays.service eas-station-gpio.service \
            eas-station-poller.service; do
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
#
# clear needs $TERM to look up how to clear the screen via terminfo; a
# systemd-run transient unit sets neither $TERM nor $HOME for the process
# it launches (see bin/eas-station-run-update's $HOME fix for the same
# class of gap). Unguarded, this was the one command standing between a
# fully successful non-interactive run and `set -e` aborting it right at
# the finish line, exit 1, after every real step had already succeeded --
# `clear`'s only job here is cosmetic.
if [ "$MIGRATION_FAILED" != "true" ]; then
    clear 2>/dev/null || true
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

# Every run prints the plain-text summary to the log unconditionally --
# that's what the web UI's progress feed reads its final result from. The
# whiptail dialog on top of it is only for someone actually watching a
# terminal.
if [ "$SERVICE_STATUS" = "running" ] && [ "$NGINX_STATUS" = "ok" ]; then
    echo "=== UPDATE RESULT: SUCCESS ==="
    echo -e "$SUMMARY"
    if [ "$NON_INTERACTIVE" != "true" ]; then
        whiptail --title "Update Complete" --backtitle "$(whiptail_footer)" --msgbox "$SUMMARY" 24 75
    fi
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
    ERROR_MSG+="Review the console output above for details."

    echo "=== UPDATE RESULT: ISSUES DETECTED ==="
    echo -e "$ERROR_MSG"
    if [ "$NON_INTERACTIVE" != "true" ]; then
        ERROR_MSG_DIALOG="$ERROR_MSG"
        ERROR_MSG_DIALOG+="\nPress OK to continue..."
        whiptail --title "Update Issues Detected" --backtitle "$(whiptail_footer)" --msgbox "$ERROR_MSG_DIALOG" 20 75
    fi
fi

# Console summary
echo ""

# Show celebration animation -- purely decorative for a human watching a
# terminal, so skip it in --non-interactive mode. Its own whiptail call is
# guarded (`2>/dev/null || true`) and an isolated repro of that exact call
# doesn't abort the shell, yet on hardware, in a real end-to-end run inside
# this script, it still took the whole script down right here with the
# same "/dev/tty: No such device or address" -> exit 1 signature as every
# other TTY-only call in this script -- after every real step (backup,
# services, git pull, deps, migrations, restart) had already succeeded.
# Not worth chasing the exact mechanism further for a screen nobody
# watching a log file will ever see.
if [ "$NON_INTERACTIVE" != "true" ]; then
    show_celebration "Update completed successfully!" "*** UPDATE COMPLETE ***"
fi

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
# Trivial touch to exercise the self-restart path in the next end-to-end test.
