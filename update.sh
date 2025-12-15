#!/bin/bash
# EAS Station Update Script
# Copyright (c) 2025 Timothy Kramer (KR8MER)
# Licensed under AGPL v3 or Commercial License

set -e  # Exit on error

# Color output (enhanced palette - matching install.sh)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

# Step counter for progress tracking
STEP_NUM=0
TOTAL_STEPS=12

echo_step() {
    STEP_NUM=$((STEP_NUM + 1))
    show_step_progress "$STEP_NUM" "$TOTAL_STEPS" "$1"
}

echo_info() {
    echo -e "${BLUE}ℹ️  [INFO]${NC} $1"
}

echo_success() {
    echo -e "${GREEN}✓  [SUCCESS]${NC} $1"
}

echo_warning() {
    echo -e "${YELLOW}⚠️  [WARNING]${NC} $1"
}

echo_error() {
    echo -e "${RED}✗  [ERROR]${NC} $1"
}

echo_progress() {
    echo -e "${MAGENTA}▶  ${NC}$1"
}

echo_header() {
    local text="$1"
    local box_width=64
    local content_width=$((box_width - 4))  # Account for "║  " and "  ║"
    
    # Calculate visual length (accounting for emojis and multi-byte chars)
    local text_len=$(echo -n "$text" | wc -m)
    local padding=$((content_width - text_len))
    if [ $padding -lt 0 ]; then
        padding=0
    fi
    
    echo ""
    echo -e "${BOLD}${CYAN}╔$(printf '═%.0s' $(seq 1 $box_width))╗${NC}"
    echo -e "${BOLD}${CYAN}║${NC}${BOLD}${WHITE}  $text$(printf ' %.0s' $(seq 1 $padding))  ${BOLD}${CYAN}║${NC}"
    echo -e "${BOLD}${CYAN}╚$(printf '═%.0s' $(seq 1 $box_width))╝${NC}"
    echo ""
}

# Progress bar function
show_progress_bar() {
    local current=$1
    local total=$2
    local width=50
    local percentage=$((current * 100 / total))
    local filled=$((current * width / total))
    local empty=$((width - filled))
    
    printf "\r${CYAN}["
    printf "%${filled}s" | tr ' ' '█'
    printf "%${empty}s" | tr ' ' '░'
    printf "]${NC} ${BOLD}${percentage}%%${NC} ${WHITE}($current/$total)${NC}"
    
    if [ "$current" -eq "$total" ]; then
        echo ""
    fi
}

# Animated spinner for long operations
show_spinner() {
    local pid=$1
    local delay=0.1
    local spinstr='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    while ps -p $pid > /dev/null 2>&1; do
        local temp=${spinstr#?}
        printf " ${CYAN}[%c]${NC}  " "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b\b"
    done
    printf "    \b\b\b\b"
}

# Box drawing for important information
draw_box() {
    local text="$1"
    local box_width=68
    local text_len=$(echo -n "$text" | wc -m)
    local padding=$((box_width - text_len - 2))
    if [ $padding -lt 0 ]; then padding=0; fi
    
    echo ""
    echo -e "${BOLD}${GREEN}┌$(printf '─%.0s' $(seq 1 $box_width))┐${NC}"
    echo -e "${BOLD}${GREEN}│${NC} ${BOLD}${WHITE}${text}$(printf ' %.0s' $(seq 1 $padding))${NC} ${BOLD}${GREEN}│${NC}"
    echo -e "${BOLD}${GREEN}└$(printf '─%.0s' $(seq 1 $box_width))┘${NC}"
    echo ""
}

# Display a visual step indicator with progress
show_step_progress() {
    local step=$1
    local total=$2
    local desc="$3"
    local box_width=63
    
    # Step line
    local step_text="Step $step of $total"
    local step_len=$(echo -n "$step_text" | wc -m)
    local step_padding=$((box_width - step_len - 2))
    if [ $step_padding -lt 0 ]; then step_padding=0; fi
    
    # Description line
    local desc_len=$(echo -n "$desc" | wc -m)
    local desc_padding=$((box_width - desc_len - 2))
    if [ $desc_padding -lt 0 ]; then desc_padding=0; fi
    
    echo ""
    echo -e "${BOLD}${CYAN}╔$(printf '═%.0s' $(seq 1 $box_width))╗${NC}"
    echo -e "${BOLD}${CYAN}║${NC} ${BOLD}${WHITE}$step_text${NC}$(printf ' %.0s' $(seq 1 $step_padding)) ${BOLD}${CYAN}║${NC}"
    echo -e "${BOLD}${CYAN}║${NC} ${CYAN}$desc${NC}$(printf ' %.0s' $(seq 1 $desc_padding)) ${BOLD}${CYAN}║${NC}"
    echo -e "${BOLD}${CYAN}╚$(printf '═%.0s' $(seq 1 $box_width))╝${NC}"
    
    # Show mini progress bar
    local filled=$((step * 50 / total))
    local empty=$((50 - filled))
    printf "  ${CYAN}["
    printf "%${filled}s" | tr ' ' '█'
    printf "%${empty}s" | tr ' ' '░'
    printf "]${NC}\n\n"
}

# Add branding footer for whiptail dialogs
whiptail_footer() {
    echo "Copyright (c) 2025 Timothy Kramer (KR8MER) | AGPL v3 / Commercial License"
}

# Display update banner
clear
echo -e "${BOLD}${CYAN}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║                 ███████╗ █████╗ ███████╗                              ║
║                 ██╔════╝██╔══██╗██╔════╝                              ║
║                 █████╗  ███████║███████╗                              ║
║                 ██╔══╝  ██╔══██║╚════██║                              ║
║                 ███████╗██║  ██║███████║                              ║
║                 ╚══════╝╚═╝  ╚═╝╚══════╝                              ║
║                                                                       ║
║            ███████╗████████╗ █████╗ ████████╗██╗ ██████╗ ███╗   ██╗  ║
║            ██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝██║██╔═══██╗████╗  ██║  ║
║            ███████╗   ██║   ███████║   ██║   ██║██║   ██║██╔██╗ ██║  ║
║            ╚════██║   ██║   ██╔══██║   ██║   ██║██║   ██║██║╚██╗██║  ║
║            ███████║   ██║   ██║  ██║   ██║   ██║╚██████╔╝██║ ╚████║  ║
║            ╚══════╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝  ╚═══╝  ║
║                                                                       ║
║                    Emergency Alert System Update                      ║
║                   Updating to Latest Version                          ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"
echo ""
echo -e "${DIM}Copyright (c) 2025 Timothy Kramer (KR8MER)${NC}"
echo -e "${DIM}Licensed under AGPL v3 or Commercial License${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo_error "This script must be run as root (use sudo)"
    echo ""
    echo -e "${YELLOW}Please run:${NC} ${BOLD}sudo ./update.sh${NC}"
    echo ""
    exit 1
fi

draw_box "✓  Root privileges confirmed - Update ready to begin"

# Configuration variables
INSTALL_DIR="/opt/eas-station"
SERVICE_USER="eas-station"
BACKUP_DIR="/var/backups/eas-station"

echo_step "Pre-flight Checks"

# Check if EAS Station is installed
if [ ! -d "$INSTALL_DIR" ]; then
    echo_error "EAS Station is not installed at $INSTALL_DIR"
    echo_info "Please run install.sh first"
    exit 1
fi
echo_success "Installation directory found: $INSTALL_DIR"

# Check if whiptail is available (for TUI dialogs)
if ! command -v whiptail &> /dev/null; then
    echo_warning "whiptail not found - installing for interactive dialogs..."
    
    # Set DEBIAN_FRONTEND to avoid interactive prompts
    export DEBIAN_FRONTEND=noninteractive
    
    if ! apt-get update; then
        echo_warning "Failed to update package lists for whiptail installation"
        echo_info "Continuing without TUI..."
        USE_WHIPTAIL=false
    elif ! apt-get install -y whiptail; then
        echo_warning "Failed to install whiptail"
        echo_info "Continuing without TUI..."
        USE_WHIPTAIL=false
    elif ! command -v whiptail &> /dev/null; then
        echo_warning "whiptail installation succeeded but command not found"
        echo_info "Continuing without TUI..."
        USE_WHIPTAIL=false
    else
        echo_success "whiptail installed successfully"
        USE_WHIPTAIL=true
    fi
else
    echo_success "whiptail available for interactive dialogs"
    USE_WHIPTAIL=true
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

# Show welcome dialog with whiptail if available
if [ "$USE_WHIPTAIL" = true ]; then
    VERSION_LINE=""
    if [ -n "$CURRENT_VERSION" ]; then
        VERSION_LINE="  Version: $CURRENT_VERSION\n"
    fi
    if ! whiptail --title "EAS Station Update" --backtitle "$(whiptail_footer)" --yesno "Welcome to the EAS Station Update Wizard!\n\nThis will update your EAS Station installation to the latest version.\n\nThe update process will:\n• Create a backup of your current installation\n• Stop all EAS Station services temporarily\n• Update application files from Git or GitHub\n• Preserve your configuration (.env file)\n• Update Python dependencies\n• Run database migrations if needed\n• Update systemd service files\n• Restart all services\n\nCurrent Installation:\n  Location: $INSTALL_DIR\n${VERSION_LINE}  Branch: $CURRENT_BRANCH\n  Commit: $CURRENT_COMMIT\n\nDo you want to continue with the update?" 28 75; then
        echo_info "Update cancelled by user"
        exit 0
    fi
else
    # Fallback to simple confirmation
    echo_header "Update Confirmation"
    echo_warning "This will update EAS Station to the latest version."
    echo_warning "Services will be stopped during the update."
    echo ""
    echo_info "Current Installation:"
    echo "  Location: $INSTALL_DIR"
    if [ -n "$CURRENT_VERSION" ]; then
        echo "  Version: $CURRENT_VERSION"
    fi
    echo "  Branch: $CURRENT_BRANCH"
    echo "  Commit: $CURRENT_COMMIT"
    echo ""
    read -p "Continue? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo_info "Update cancelled"
        exit 0
    fi
fi

# Create backup (skip if restarting after self-update)
if [ "${EAS_SKIP_BACKUP:-}" != "true" ]; then
echo_step "Creating Backup"
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
    if sudo -u "$SERVICE_USER" git fetch origin 2>&1; then
        echo_success "Fetched latest changes from remote"
    else
        echo_error "Git fetch failed - cannot update"
        echo_info "Check your internet connection and git configuration"
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
        echo_success "Already up to date with remote"
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
    
    if sudo -u "$SERVICE_USER" git reset --hard "origin/$CURRENT_BRANCH" 2>&1; then
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
        echo_info "Your installation may be out of date"
        echo_info "Try running: git reset --hard origin/$CURRENT_BRANCH"
        exit 1
    fi
    
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
echo_progress "Installing any new system packages..."
echo_info "Output will be shown below so you can track progress and see any errors:"
echo ""

# Set DEBIAN_FRONTEND to avoid interactive prompts
export DEBIAN_FRONTEND=noninteractive

if ! apt-get update; then
    echo_warning "Failed to update package lists"
    echo_info "This may be due to network issues or repository problems"
    echo_info "Continuing with update, but some packages may not be updated"
fi

# Install all required system dependencies (matches install.sh)
# This ensures new dependencies added in updates are installed
if ! apt-get install -y \
    python3-dev \
    build-essential \
    libpq-dev \
    libev-dev \
    libevent-dev \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    libfreetype6-dev \
    ffmpeg \
    espeak \
    libespeak-ng1 \
    libusb-1.0-0 \
    libusb-1.0-0-dev \
    python3-numpy \
    python3-soapysdr \
    soapysdr-tools \
    rtl-sdr \
    soapysdr-module-rtlsdr \
    soapysdr-module-airspy \
    libairspy0 \
    i2c-tools \
    python3-smbus \
    python3-lgpio; then
    echo ""
    echo_warning "Some system dependencies failed to install"
    echo_info "This may not affect the update, but check the errors above"
    echo_info "You can manually install missing packages later if needed"
    echo ""
fi

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
        echo_info "Installing SDR requirements (scipy, numba may take 5-15 min to compile)..."
        echo_info "Full output shown below to track progress:"
        echo ""
        # Show full output so user can see compilation progress (no grep filter)
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
else
    echo_warning "Systemd directory not found - skipping service file update"
fi

# Update nginx configuration (only if changed)
echo_step "Checking Nginx Configuration"

if [ -f "$INSTALL_DIR/config/nginx-eas-station.conf" ]; then
    if [ -f /etc/nginx/sites-available/eas-station ]; then
        if ! diff -q "$INSTALL_DIR/config/nginx-eas-station.conf" /etc/nginx/sites-available/eas-station >/dev/null 2>&1; then
            echo_progress "Updating nginx configuration..."
            cp "$INSTALL_DIR/config/nginx-eas-station.conf" /etc/nginx/sites-available/eas-station
            
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
        
        # Give user time to read the error before continuing
        echo ""
        echo_warning "Migration errors detected above - review carefully before continuing"
        echo_info "Press Enter to continue with update (auto-continue in 60s), or Ctrl+C to abort..."
        read -r -t 60 || echo_info "Auto-continuing after timeout..."
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

# Restart services with updated code
echo_step "Restarting Services"
echo_progress "Reloading systemd daemon to pick up any service file changes..."
systemctl daemon-reload
echo_success "Systemd daemon reloaded"

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

echo_progress "Starting all EAS Station services with updated code..."
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

if [ "$USE_WHIPTAIL" = true ]; then
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
fi

# Console summary
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
