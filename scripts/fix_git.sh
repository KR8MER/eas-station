#!/bin/bash
# EAS Station - Fix Missing .git Directory
# Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)
# Licensed under AGPL v3 or Commercial License

set -e  # Exit on error

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

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

echo_header() {
    echo -e "\n${BOLD}${CYAN}$1${NC}\n"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo_error "This script must be run as root (use sudo)"
    echo ""
    echo -e "${YELLOW}Please run:${NC} ${BOLD}sudo bash scripts/fix_git.sh${NC}"
    echo ""
    exit 1
fi

INSTALL_DIR="/opt/eas-station"
SERVICE_USER="eas-station"

echo_header "🔧 EAS Station - Restore Git Repository"

# Check if installation exists
if [ ! -d "$INSTALL_DIR" ]; then
    echo_error "EAS Station not found at $INSTALL_DIR"
    echo_info "This script is for existing installations only"
    exit 1
fi

echo_success "Found EAS Station installation at $INSTALL_DIR"

# Fix "dubious ownership" errors when running git as root
# This allows git commands to work on repositories owned by SERVICE_USER
echo_info "Configuring git safe.directory for $INSTALL_DIR..."
if git config --global --add safe.directory "$INSTALL_DIR" >/dev/null 2>&1; then
    echo_success "Git configuration updated"
else
    echo_warning "Could not update git config (non-critical - continuing)"
fi

# Check if .git already exists
if [ -d "$INSTALL_DIR/.git" ]; then
    echo_success "Git repository already exists!"
    echo_info "Checking repository status..."
    
    cd "$INSTALL_DIR"
    if sudo -u "$SERVICE_USER" git status > /dev/null 2>&1; then
        CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
        CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
        echo_success "Git repository is healthy"
        echo_info "Branch: ${BOLD}$CURRENT_BRANCH${NC}"
        echo_info "Commit: ${BOLD}$CURRENT_COMMIT${NC}"
        echo ""
        echo -e "${GREEN}No action needed. You can run update.sh to get latest changes.${NC}"
        exit 0
    else
        echo_warning "Git repository exists but appears corrupted"
        echo_info "Will attempt to fix..."
        sudo rm -rf "$INSTALL_DIR/.git"
    fi
fi

echo_warning "Git repository missing from $INSTALL_DIR"
echo_info "This prevents git-based updates and version info display"
echo ""

# Prompt user for action
echo -e "${BOLD}How would you like to fix this?${NC}"
echo ""
echo "1) Clone fresh from GitHub (recommended - clean state)"
echo "2) Copy .git from ~/eas-station (if you still have the original clone)"
echo "3) Initialize new git repo and fetch from GitHub"
echo "4) Cancel"
echo ""
read -p "Enter choice [1-4]: " -n 1 -r CHOICE
echo ""

case $CHOICE in
    1)
        echo_header "Option 1: Clone Fresh from GitHub"
        
        # Check network connectivity
        echo_info "Testing GitHub connectivity..."
        if ! curl -s --head https://github.com > /dev/null; then
            echo_error "Cannot reach GitHub. Check your internet connection."
            exit 1
        fi
        echo_success "GitHub is reachable"
        
        # Determine branch to use
        if [ -f "$INSTALL_DIR/VERSION" ]; then
            echo_info "Detected existing installation, will use 'main' branch"
            BRANCH="main"
        else
            BRANCH="main"
        fi
        
        echo_info "Will clone branch: ${BOLD}$BRANCH${NC}"
        echo ""
        echo_warning "This will:"
        echo "  1. Create temporary backup of current installation"
        echo "  2. Clone fresh repository from GitHub"
        echo "  3. Restore your .env configuration"
        echo "  4. Preserve your data (database, uploads, etc.)"
        echo ""
        read -p "Continue? (y/N) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo_info "Cancelled"
            exit 0
        fi
        
        # Create backup
        BACKUP_DIR="/tmp/eas-station-backup-$(date +%Y%m%d-%H%M%S)"
        echo_info "Creating backup at $BACKUP_DIR..."
        
        # Backup critical files
        mkdir -p "$BACKUP_DIR"
        [ -f "$INSTALL_DIR/.env" ] && cp "$INSTALL_DIR/.env" "$BACKUP_DIR/"
        [ -d "$INSTALL_DIR/venv" ] && echo "venv" > "$BACKUP_DIR/.venv_existed"
        echo_success "Backup created"
        
        # Clone to temporary location
        TEMP_CLONE="/tmp/eas-station-clone-$$"
        echo_info "Cloning repository from GitHub..."
        if git clone --branch "$BRANCH" https://github.com/KR8MER/eas-station.git "$TEMP_CLONE"; then
            echo_success "Repository cloned successfully"
        else
            echo_error "Git clone failed"
            exit 1
        fi
        
        # Copy .git directory to installation
        echo_info "Copying .git directory to $INSTALL_DIR..."
        cp -r "$TEMP_CLONE/.git" "$INSTALL_DIR/"
        chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.git"
        
        # Reset to match remote (update files)
        echo_info "Updating files to match repository..."
        cd "$INSTALL_DIR"
        if sudo -u "$SERVICE_USER" git reset --hard HEAD; then
            echo_success "Files updated to match repository"
        else
            echo_warning "git reset had issues, but .git directory is in place"
        fi
        
        # Restore .env
        if [ -f "$BACKUP_DIR/.env" ]; then
            echo_info "Restoring your .env configuration..."
            cp "$BACKUP_DIR/.env" "$INSTALL_DIR/.env"
            chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"
            echo_success "Configuration restored"
        fi
        
        # Cleanup
        rm -rf "$TEMP_CLONE"
        
        echo_success "Git repository restored!"
        echo ""
        echo -e "${GREEN}Next steps:${NC}"
        echo "  1. Run merge to add any new .env variables:"
        echo "     ${CYAN}sudo python3 $INSTALL_DIR/scripts/merge_env.py --backup${NC}"
        echo ""
        echo "  2. Restart services:"
        echo "     ${CYAN}sudo systemctl restart eas-station.target${NC}"
        echo ""
        echo "  3. Future updates will now use git:"
        echo "     ${CYAN}sudo $INSTALL_DIR/update.sh${NC}"
        ;;
        
    2)
        echo_header "Option 2: Copy .git from ~/eas-station"
        
        # Look for original clone in common locations
        ORIGINAL_CLONE=""
        for dir in ~/eas-station /home/*/eas-station /root/eas-station; do
            if [ -d "$dir/.git" ]; then
                ORIGINAL_CLONE="$dir"
                echo_success "Found original clone at: $ORIGINAL_CLONE"
                break
            fi
        done
        
        if [ -z "$ORIGINAL_CLONE" ]; then
            echo_warning "Could not find original clone automatically"
            echo ""
            read -p "Enter path to original eas-station clone (or press Enter to cancel): " MANUAL_PATH
            if [ -n "$MANUAL_PATH" ] && [ -d "$MANUAL_PATH/.git" ]; then
                ORIGINAL_CLONE="$MANUAL_PATH"
            else
                echo_error "No valid clone found. Try option 1 instead."
                exit 1
            fi
        fi
        
        # Update original clone first
        echo_info "Updating original clone to latest version..."
        cd "$ORIGINAL_CLONE"
        if sudo -u "$SERVICE_USER" git pull 2>/dev/null || git pull; then
            echo_success "Original clone updated"
        else
            echo_warning "Could not update original clone (continuing anyway)"
        fi
        
        # Copy .git directory
        echo_info "Copying .git directory to $INSTALL_DIR..."
        cp -r "$ORIGINAL_CLONE/.git" "$INSTALL_DIR/"
        chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.git"
        
        # Reset to match the .git we just copied
        echo_info "Updating files to match repository..."
        cd "$INSTALL_DIR"
        if sudo -u "$SERVICE_USER" git reset --hard HEAD; then
            echo_success "Files updated"
        else
            echo_warning "git reset had issues, but .git directory is in place"
        fi
        
        echo_success "Git repository restored from original clone!"
        ;;
        
    3)
        echo_header "Option 3: Initialize New Git Repo"
        
        echo_warning "This option is for advanced users"
        echo_info "Will initialize git repo and add GitHub as remote"
        echo ""
        read -p "Continue? (y/N) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo_info "Cancelled"
            exit 0
        fi
        
        cd "$INSTALL_DIR"
        
        # Initialize repo
        echo_info "Initializing git repository..."
        sudo -u "$SERVICE_USER" git init
        
        # Add remote
        echo_info "Adding GitHub remote..."
        sudo -u "$SERVICE_USER" git remote add origin https://github.com/KR8MER/eas-station.git
        
        # Fetch
        echo_info "Fetching from GitHub..."
        if sudo -u "$SERVICE_USER" git fetch origin; then
            echo_success "Fetched successfully"
        else
            echo_error "Git fetch failed"
            exit 1
        fi
        
        # Set up branch tracking
        BRANCH="main"
        echo_info "Setting up branch tracking for $BRANCH..."
        sudo -u "$SERVICE_USER" git checkout -b "$BRANCH" "origin/$BRANCH" || \
        sudo -u "$SERVICE_USER" git checkout "$BRANCH"
        
        # Reset to match remote
        echo_info "Updating files to match repository..."
        sudo -u "$SERVICE_USER" git reset --hard "origin/$BRANCH"
        
        echo_success "Git repository initialized!"
        ;;
        
    4)
        echo_info "Cancelled"
        exit 0
        ;;
        
    *)
        echo_error "Invalid choice"
        exit 1
        ;;
esac

# Final verification
echo ""
echo_header "Verification"

cd "$INSTALL_DIR"
if [ -d ".git" ] && sudo -u "$SERVICE_USER" git status > /dev/null 2>&1; then
    BRANCH=$(git branch --show-current)
    COMMIT=$(git rev-parse --short HEAD)
    
    echo_success "Git repository is working!"
    echo_info "Current branch: ${BOLD}$BRANCH${NC}"
    echo_info "Current commit: ${BOLD}$COMMIT${NC}"
    echo ""
    
    # Show recent commits
    echo -e "${BOLD}Recent commits:${NC}"
    git log --oneline -5
    echo ""
    
    echo_success "✅ Fix complete!"
    echo ""
    echo -e "${GREEN}Your installation now has a working git repository.${NC}"
    echo ""
    echo -e "${BOLD}Recommended next steps:${NC}"
    echo "1. Merge any new .env variables:"
    echo "   ${CYAN}sudo python3 $INSTALL_DIR/scripts/merge_env.py --backup${NC}"
    echo ""
    echo "2. Restart services:"
    echo "   ${CYAN}sudo systemctl restart eas-station.target${NC}"
    echo ""
    echo "3. Verify version info displays correctly:"
    echo "   ${CYAN}Visit web interface → Help → Version${NC}"
    echo ""
    echo "4. Future updates:"
    echo "   ${CYAN}cd $INSTALL_DIR && sudo ./update.sh${NC}"
    
else
    echo_error "Git repository setup failed"
    echo_info "Please try option 1 (Clone fresh from GitHub)"
    exit 1
fi
