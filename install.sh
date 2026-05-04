#!/bin/bash
# EAS Station Bare Metal Installation Script
# Copyright (c) 2025-2026 Timothy Kramer (KR8MER)
# Licensed under AGPL v3 or Commercial License

set -e  # Exit on error

# Log file — all command output is redirected here after root check
LOG_FILE="/var/log/eas-install.log"

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
TOTAL_STEPS=17
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
    whiptail --title "*** INSTALLATION COMPLETE ***" \
             --backtitle "$(whiptail_footer)" \
             --msgbox "$1\n\nTotal time: $elapsed\nLog: $LOG_FILE" 10 65
}

cleanup_on_exit() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo "[ERROR] Script exited with code $exit_code"
        whiptail --title "Installation Failed" \
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
    printf '\033[1;34m  EAS Station — Bare Metal Installer\033[0m\n'
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
VENV_DIR="${INSTALL_DIR}/venv"
LOG_DIR="/var/log/eas-station"
CONFIG_FILE="${INSTALL_DIR}/.env"

# Get the directory where this script is located (for accessing bundled helper scripts before install)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo_step "System Detection"

# Detect system architecture
ARCH=$(uname -m)
echo_info "Architecture: ${BOLD}$ARCH${NC}"

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    OS_VERSION=$VERSION_ID
    echo_info "Operating System: ${BOLD}$OS $OS_VERSION${NC}"
else
    echo_error "Cannot detect OS. /etc/os-release not found."
    exit 1
fi

# Check if Debian/Ubuntu based
if [ "$OS" != "debian" ] && [ "$OS" != "ubuntu" ] && [ "$OS" != "raspbian" ]; then
    echo_warning "This script is designed for Debian/Ubuntu. Your OS is: $OS"
    if ! whiptail --title "Unsupported OS" --backtitle "$(whiptail_footer)" \
         --yesno "Unsupported OS detected: $OS\n\nThis script is designed for Debian/Ubuntu.\n\nContinue anyway?" 10 60; then
        echo_info "Installation cancelled by user"
        exit 1
    fi
fi

echo_success "System detection complete"

# Detect GPIO hardware presence (Raspberry Pi or other SBCs with GPIO)
# This must be done early since it's used in both package installation and hardware setup
HAS_GPIO=false
if [ -e /dev/gpiochip0 ] || [ -e /dev/gpiomem ] || grep -qiE "raspberry|bcm2[0-9]+|broadcom" /proc/cpuinfo 2>/dev/null; then
    HAS_GPIO=true
    echo_info "GPIO hardware detected (will be available for configuration)"
else
    echo_info "No GPIO hardware detected (VM or standard PC)"
fi

# Detect Raspberry Pi 5 (needed to offer Argon ONE V5 Zigbee option)
IS_PI5=false
if grep -q "Raspberry Pi 5" /proc/device-tree/model 2>/dev/null; then
    IS_PI5=true
    echo_info "Raspberry Pi 5 detected"
fi

# ====================================================================
# COLLECT MINIMAL CONFIGURATION
# ====================================================================

# Check if whiptail is available
if ! command -v whiptail &> /dev/null; then
    echo_error "whiptail is required for interactive installation"
    echo_info "whiptail provides the blue/gray dialog boxes for interactive configuration"
    echo_info "Installing whiptail package..."
    
    # Disable exit-on-error temporarily
    set +e
    apt-get update
    UPDATE_EXIT=$?
    
    if [ $UPDATE_EXIT -eq 0 ]; then
        apt-get install -y whiptail
        INSTALL_EXIT=$?
    else
        INSTALL_EXIT=1
    fi
    
    # Re-enable exit-on-error
    set -e
    
    if [ $UPDATE_EXIT -ne 0 ] || [ $INSTALL_EXIT -ne 0 ]; then
        echo_error "Failed to install whiptail automatically"
        echo_info "Please install manually and re-run installer:"
        echo_info "  ${BOLD}sudo apt-get update && sudo apt-get install whiptail${NC}"
        exit 1
    fi
    
    if ! command -v whiptail &> /dev/null; then
        echo_error "whiptail installation succeeded but command not found"
        echo_info "This is unusual. Please install manually:"
        echo_info "  ${BOLD}sudo apt-get install whiptail${NC}"
        exit 1
    fi
    echo_success "whiptail installed successfully"
fi

echo_step "Administrator Account Setup"

# Welcome screen
whiptail --title "EAS Station Installation" --backtitle "$(whiptail_footer)" --msgbox "Welcome to the EAS Station Interactive Installer!\n\nThis wizard will guide you through configuring your Emergency Alert System station.\n\nYou'll be asked to configure:\n• Administrator account\n• System identification\n• Station callsign and location\n\nPress OK to begin." 18 70

# Prompt for admin username
while true; do
    ADMIN_USERNAME=$(whiptail --title "Administrator Account" --backtitle "$(whiptail_footer)" --inputbox "Enter administrator username (min 3 characters):\n\nThis account will be used to access the web interface." 12 70 3>&1 1>&2 2>&3)
    
    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        if whiptail --title "Cancel Installation?" --backtitle "$(whiptail_footer)" --yesno "Are you sure you want to cancel the installation?" 8 60; then
            echo_error "Installation cancelled by user"
            exit 1
        else
            continue
        fi
    fi
    
    ADMIN_USERNAME=$(echo "$ADMIN_USERNAME" | xargs)  # Trim whitespace
    
    if [ -z "$ADMIN_USERNAME" ]; then
        whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Username cannot be empty. Please try again." 8 60
        continue
    fi
    
    if [ ${#ADMIN_USERNAME} -lt 3 ]; then
        whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Username must be at least 3 characters long." 8 60
        continue
    fi
    
    if ! [[ "$ADMIN_USERNAME" =~ ^[A-Za-z0-9_.-]+$ ]]; then
        whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Username may only contain letters, numbers, dots, hyphens, or underscores." 9 60
        continue
    fi
    
    echo_success "Username accepted: ${BOLD}$ADMIN_USERNAME${NC}"
    break
done

# Prompt for admin password
while true; do
    ADMIN_PASSWORD=$(whiptail --title "Administrator Password" --backtitle "$(whiptail_footer)" --passwordbox "Enter administrator password (min 12 characters):" 10 70 3>&1 1>&2 2>&3)
    
    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        if whiptail --title "Cancel Installation?" --backtitle "$(whiptail_footer)" --yesno "Are you sure you want to cancel the installation?" 8 60; then
            echo_error "Installation cancelled by user"
            exit 1
        else
            continue
        fi
    fi
    
    if [ ${#ADMIN_PASSWORD} -lt 12 ]; then
        whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Password must be at least 12 characters long." 8 60
        continue
    fi
    
    ADMIN_PASSWORD_CONFIRM=$(whiptail --title "Confirm Password" --backtitle "$(whiptail_footer)" --passwordbox "Confirm administrator password:" 10 70 3>&1 1>&2 2>&3)
    
    if [ "$ADMIN_PASSWORD" != "$ADMIN_PASSWORD_CONFIRM" ]; then
        whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Passwords do not match. Please try again." 8 60
        continue
    fi
    
    echo_success "Password accepted (${#ADMIN_PASSWORD} characters)"
    break
done

# Prompt for admin email address (for notifications)
while true; do
    ADMIN_EMAIL=$(whiptail --title "Administrator Email" --backtitle "$(whiptail_footer)" --inputbox "Enter administrator email address:\n\nThis will be used for system notifications and alerts." 12 70 3>&1 1>&2 2>&3)
    
    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        if whiptail --title "Cancel Installation?" --backtitle "$(whiptail_footer)" --yesno "Are you sure you want to cancel the installation?" 8 60; then
            echo_error "Installation cancelled by user"
            exit 1
        else
            continue
        fi
    fi
    
    ADMIN_EMAIL=$(echo "$ADMIN_EMAIL" | xargs)  # Trim whitespace
    
    if [ -z "$ADMIN_EMAIL" ]; then
        whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Email address cannot be empty." 8 60
        continue
    fi
    
    # Basic email validation (must have @ and . after @)
    if ! [[ "$ADMIN_EMAIL" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Invalid email format.\n\nEmail must be in format: user@domain.com" 9 60
        continue
    fi
    
    echo_success "Email accepted: ${BOLD}$ADMIN_EMAIL${NC}"
    break
done

echo_success "Administrator account configured"

# ====================================================================
# SYSTEM AND EAS STATION CONFIGURATION
# ====================================================================

echo_step "System and EAS Station Configuration"

# Prompt for system hostname
CURRENT_HOSTNAME=$(hostname 2>/dev/null || echo "eas-station")
while true; do
    SYSTEM_HOSTNAME=$(whiptail --title "System Hostname" --backtitle "$(whiptail_footer)" --inputbox "Enter system hostname:\n\nThis will be the network name of your EAS station." 12 70 "$CURRENT_HOSTNAME" 3>&1 1>&2 2>&3)
    
    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        SYSTEM_HOSTNAME="$CURRENT_HOSTNAME"
        echo_info "Using current hostname: $SYSTEM_HOSTNAME"
        break
    fi
    
    # Trim whitespace
    SYSTEM_HOSTNAME=$(echo "$SYSTEM_HOSTNAME" | xargs)
    
    # Use current hostname if empty
    if [ -z "$SYSTEM_HOSTNAME" ]; then
        SYSTEM_HOSTNAME="$CURRENT_HOSTNAME"
    fi
    
    # Validate hostname format (alphanumeric, hyphens, dots)
    if ! [[ "$SYSTEM_HOSTNAME" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ ]]; then
        whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Invalid hostname format.\n\nUse only letters, numbers, hyphens, and dots." 9 60
        continue
    fi
    
    echo_success "Hostname: ${BOLD}$SYSTEM_HOSTNAME${NC}"
    break
done

# Prompt for domain name (for SSL/nginx)
while true; do
    DOMAIN_NAME=$(whiptail --title "Domain Name" --backtitle "$(whiptail_footer)" --inputbox "Enter domain name for SSL/web access:\n\nUse 'localhost' for local-only access, an IP address, or your domain name." 13 70 "localhost" 3>&1 1>&2 2>&3)
    
    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        DOMAIN_NAME="localhost"
        echo_info "Using default: $DOMAIN_NAME"
        break
    fi
    
    # Trim whitespace
    DOMAIN_NAME=$(echo "$DOMAIN_NAME" | xargs)
    
    # Default to localhost if empty
    if [ -z "$DOMAIN_NAME" ]; then
        DOMAIN_NAME="localhost"
    fi
    
    # Validate domain format (allow localhost, IP addresses, and domain names)
    if [[ "$DOMAIN_NAME" == "localhost" ]]; then
        echo_success "Domain: ${BOLD}$DOMAIN_NAME${NC}"
        break
    # Validate IP address with proper octet range (0-255)
    elif [[ "$DOMAIN_NAME" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        IFS='.' read -ra OCTETS <<< "$DOMAIN_NAME"
        VALID_IP=true
        for octet in "${OCTETS[@]}"; do
            # Verify octet is numeric and in valid range
            if ! [[ "$octet" =~ ^[0-9]+$ ]] || [ "$octet" -lt 0 ] || [ "$octet" -gt 255 ]; then
                VALID_IP=false
                break
            fi
        done
        if [ "$VALID_IP" = true ]; then
            echo_success "Domain: ${BOLD}$DOMAIN_NAME${NC}"
            break
        else
            whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Invalid IP address.\n\nEach octet must be 0-255." 9 60
            continue
        fi
    # Validate domain name format
    elif [[ "$DOMAIN_NAME" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ ]]; then
        echo_success "Domain: ${BOLD}$DOMAIN_NAME${NC}"
        break
    else
        whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Invalid domain format.\n\nUse localhost, an IP address, or a valid domain name." 10 60
        continue
    fi
done

# Prompt for EAS originator code using radio button menu
EAS_ORIGINATOR=$(whiptail --title "EAS Originator Code" --backtitle "$(whiptail_footer)" --radiolist \
"Select your EAS Originator Code:\n\nThis identifies the type of EAS station." 16 78 5 \
    "WXR" "NOAA Weather Radio (recommended)" ON \
    "EAS" "EAS Participant Station" OFF \
    "PEP" "Primary Entry Point Station" OFF \
    "CIV" "Civil Authorities" OFF \
    "WXS" "National Weather Service" OFF \
    3>&1 1>&2 2>&3)

exitstatus=$?
if [ $exitstatus != 0 ] || [ -z "$EAS_ORIGINATOR" ]; then
    EAS_ORIGINATOR="WXR"
    echo_info "Using default: $EAS_ORIGINATOR"
else
    echo_success "Originator: ${BOLD}$EAS_ORIGINATOR${NC}"
fi

# Prompt for station callsign/ID
while true; do
    EAS_STATION_ID=$(whiptail --title "Station Callsign/ID" --backtitle "$(whiptail_footer)" --inputbox "Enter your station callsign or ID (max 8 characters):\n\nUse your FCC callsign if you have one, or a unique identifier.\n\nExamples: WKRP, KR8MER, EASNODE1, NOCALL" 14 70 "NOCALL" 3>&1 1>&2 2>&3)
    
    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        EAS_STATION_ID="NOCALL"
        echo_info "Using default: $EAS_STATION_ID"
        break
    fi
    
    # Convert to uppercase and trim whitespace
    EAS_STATION_ID=$(echo "$EAS_STATION_ID" | tr '[:lower:]' '[:upper:]' | xargs)
    
    # Default to NOCALL if empty
    if [ -z "$EAS_STATION_ID" ]; then
        EAS_STATION_ID="NOCALL"
    fi
    
    # Validate format (1-8 alphanumeric characters)
    if ! [[ "$EAS_STATION_ID" =~ ^[A-Z0-9]{1,8}$ ]]; then
        whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Station ID must be 1-8 alphanumeric characters.\n\nExamples: WKRP, KR8MER, NOCALL" 10 60
        continue
    fi
    
    echo_success "Station ID: ${BOLD}$EAS_STATION_ID${NC}"
    break
done

# Configuration summary and confirmation
if whiptail --title "Confirm Configuration" --backtitle "$(whiptail_footer)" --yesno "Please confirm your configuration:\n\nAdministrator: $ADMIN_USERNAME\nEmail: $ADMIN_EMAIL\nHostname: $SYSTEM_HOSTNAME\nDomain: $DOMAIN_NAME\nOriginator: $EAS_ORIGINATOR\nStation ID: $EAS_STATION_ID\n\nProceed with installation?" 18 70; then
    echo_success "Configuration confirmed"
else
    if whiptail --title "Cancel Installation?" --backtitle "$(whiptail_footer)" --yesno "Are you sure you want to cancel the installation?" 8 60; then
        echo_error "Installation cancelled by user"
        exit 1
    else
        whiptail --title "Restart Configuration" --backtitle "$(whiptail_footer)" --msgbox "Please restart the installer to reconfigure." 8 60
        echo_error "Installation cancelled - please restart"
        exit 1
    fi
fi

echo_success "System and EAS station configuration complete"

# ====================================================================
# LOCATION AND TIMEZONE CONFIGURATION
# ====================================================================

echo_step "Location and Timezone Setup"

# Timezone selection
TIMEZONE=$(whiptail --title "Timezone Selection" --backtitle "$(whiptail_footer)" --menu "Select your timezone:" 20 70 10 \
    "America/New_York" "Eastern Time" \
    "America/Chicago" "Central Time" \
    "America/Denver" "Mountain Time" \
    "America/Phoenix" "Arizona (no DST)" \
    "America/Los_Angeles" "Pacific Time" \
    "America/Anchorage" "Alaska Time" \
    "Pacific/Honolulu" "Hawaii Time" \
    "America/Puerto_Rico" "Atlantic Time" \
    3>&1 1>&2 2>&3)

exitstatus=$?
if [ $exitstatus != 0 ]; then
    TIMEZONE="America/New_York"
    echo_info "Using default timezone: $TIMEZONE"
fi

echo_success "Timezone: ${BOLD}$TIMEZONE${NC}"

# State selection (includes DC and territories for EAS coverage)
STATE_CODE=$(whiptail --title "State Selection" --backtitle "$(whiptail_footer)" --menu "Select your state or territory:" 22 70 12 \
    "AL" "Alabama" \
    "AK" "Alaska" \
    "AZ" "Arizona" \
    "AR" "Arkansas" \
    "CA" "California" \
    "CO" "Colorado" \
    "CT" "Connecticut" \
    "DC" "District of Columbia" \
    "DE" "Delaware" \
    "FL" "Florida" \
    "GA" "Georgia" \
    "HI" "Hawaii" \
    "ID" "Idaho" \
    "IL" "Illinois" \
    "IN" "Indiana" \
    "IA" "Iowa" \
    "KS" "Kansas" \
    "KY" "Kentucky" \
    "LA" "Louisiana" \
    "ME" "Maine" \
    "MD" "Maryland" \
    "MA" "Massachusetts" \
    "MI" "Michigan" \
    "MN" "Minnesota" \
    "MS" "Mississippi" \
    "MO" "Missouri" \
    "MT" "Montana" \
    "NE" "Nebraska" \
    "NV" "Nevada" \
    "NH" "New Hampshire" \
    "NJ" "New Jersey" \
    "NM" "New Mexico" \
    "NY" "New York" \
    "NC" "North Carolina" \
    "ND" "North Dakota" \
    "OH" "Ohio" \
    "OK" "Oklahoma" \
    "OR" "Oregon" \
    "PA" "Pennsylvania" \
    "RI" "Rhode Island" \
    "SC" "South Carolina" \
    "SD" "South Dakota" \
    "TN" "Tennessee" \
    "TX" "Texas" \
    "UT" "Utah" \
    "VT" "Vermont" \
    "VA" "Virginia" \
    "WA" "Washington" \
    "WV" "West Virginia" \
    "WI" "Wisconsin" \
    "WY" "Wyoming" \
    3>&1 1>&2 2>&3)

exitstatus=$?
if [ $exitstatus != 0 ]; then
    STATE_CODE="OH"
    echo_info "Using default state: $STATE_CODE"
fi

echo_success "State: ${BOLD}$STATE_CODE${NC}"

# County name
COUNTY_NAME=$(whiptail --title "County/Region" --backtitle "$(whiptail_footer)" --inputbox "Enter your county or region name:\n\n(e.g., Putnam County, Cook County)" 12 70 3>&1 1>&2 2>&3)

exitstatus=$?
if [ $exitstatus != 0 ] || [ -z "$COUNTY_NAME" ]; then
    COUNTY_NAME="Unknown County"
    echo_info "Using default: $COUNTY_NAME"
fi

echo_success "County: ${BOLD}$COUNTY_NAME${NC}"

# Optional: FIPS codes with improved checklist functionality
# NOTE: These FIPS codes are for FILTERING incoming alerts, NOT for RWT broadcasts.
# RWT broadcast targeting must be configured separately in the RWT Schedule page.
if whiptail --title "Alert Filtering FIPS Codes" --backtitle "$(whiptail_footer)" --yesno "Configure FIPS codes for ALERT FILTERING?\n\nThese codes determine which incoming alerts your station will process and forward. Select the areas you want to RECEIVE alerts for.\n\nNOTE: This is NOT for RWT broadcasts. RWT targeting\nis configured separately on the RWT Schedule page.\n\nConfigure alert filtering FIPS codes now?" 16 78; then
    
    # Try to get county list from Python helper
    FIPS_CODES=""
    LOOKUP_RESULT=""
    LOOKUP_ERROR=""
    
    echo_progress "Attempting to load county list for ${BOLD}$STATE_CODE${NC}..."
    
    # Disable exit on error temporarily
    set +e
    
    # Try to use the helper script with system Python (no dependencies needed)
    # Use SCRIPT_DIR (where install.sh is located) since files aren't copied to INSTALL_DIR yet
    if [ -f "$SCRIPT_DIR/scripts/fips_lookup_helper.py" ] && command -v python3 &> /dev/null; then
        LOOKUP_RESULT=$(python3 "$SCRIPT_DIR/scripts/fips_lookup_helper.py" list "$STATE_CODE" 2>&1)
        LOOKUP_EXIT=$?
    else
        LOOKUP_EXIT=1
        if [ ! -f "$SCRIPT_DIR/scripts/fips_lookup_helper.py" ]; then
            LOOKUP_ERROR="FIPS lookup helper script not found at $SCRIPT_DIR/scripts/"
        else
            LOOKUP_ERROR="Python 3 not available"
        fi
    fi
    
    # Re-enable exit on error
    set -e
    
    # Check if lookup was successful
    if [ $LOOKUP_EXIT -eq 0 ] && [ -n "$LOOKUP_RESULT" ] && echo "$LOOKUP_RESULT" | grep -q "counties"; then
        # Parse JSON and create checklist menu
        COUNTY_COUNT=0
        
        # Safely parse county count
        set +e
        COUNTY_COUNT=$(echo "$LOOKUP_RESULT" | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data.get('counties', [])))" 2>/dev/null)
        PARSE_EXIT=$?
        set -e
        
        if [ $PARSE_EXIT -ne 0 ] || [ -z "$COUNTY_COUNT" ]; then
            COUNTY_COUNT=0
        fi
        
        if [ "$COUNTY_COUNT" -gt 0 ]; then
            echo_success "Loaded ${BOLD}$COUNTY_COUNT${NC} counties for selection"
            
            # Build whiptail checklist from counties
            CHECKLIST_ITEMS=()

            # Parse statewide code and add it as first option
            set +e
            STATEWIDE_CODE=$(echo "$LOOKUP_RESULT" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('statewide_code', ''))" 2>/dev/null)
            STATE_NAME=$(echo "$LOOKUP_RESULT" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('state', ''))" 2>/dev/null)
            set -e

            # Add statewide option first if available
            if [ -n "$STATEWIDE_CODE" ] && [ "$STATEWIDE_CODE" != "000000" ]; then
                CHECKLIST_ITEMS+=("$STATEWIDE_CODE" "★ Entire ${STATE_NAME:-$STATE_CODE} (statewide)" "OFF")
            fi

            # Parse counties and build checklist array
            set +e
            while IFS='|' read -r fips_code county_name; do
                if [ -n "$fips_code" ] && [ -n "$county_name" ]; then
                    # Check if this county matches the user's entered county name (for pre-selection)
                    # Use case-insensitive substring match with fgrep to avoid regex issues
                    COUNTY_NAME_LOWER=$(echo "$COUNTY_NAME" | tr '[:upper:]' '[:lower:]')
                    COUNTY_CHECK_LOWER=$(echo "$county_name" | tr '[:upper:]' '[:lower:]')
                    if echo "$COUNTY_CHECK_LOWER" | fgrep -q "$COUNTY_NAME_LOWER"; then
                        CHECKLIST_ITEMS+=("$fips_code" "$county_name" "ON")
                    else
                        CHECKLIST_ITEMS+=("$fips_code" "$county_name" "OFF")
                    fi
                fi
            done < <(echo "$LOOKUP_RESULT" | python3 -c "import sys, json; data=json.load(sys.stdin); [print(f\"{c['fips']}|{c['name']}\") for c in data.get('counties', [])]" 2>/dev/null)
            set -e
            
            if [ ${#CHECKLIST_ITEMS[@]} -gt 0 ]; then
                # Show checklist dialog (allow multiple selection)
                SELECTED_FIPS=$(whiptail --title "Select Alert Filtering Areas" --backtitle "$(whiptail_footer)" \
                    --checklist "Select areas to RECEIVE alerts for:\n\n★ = Entire state (receives statewide alerts)\nNOTE: This is for filtering INCOMING alerts only.\n\nUse SPACE to select, ENTER to confirm:" \
                    25 78 15 "${CHECKLIST_ITEMS[@]}" 3>&1 1>&2 2>&3)
                
                if [ $? = 0 ] && [ -n "$SELECTED_FIPS" ]; then
                    # Parse selected FIPS codes more robustly
                    # Whiptail returns quoted space-separated values like: "039001" "039003" "039005"
                    # Remove all quotes and convert spaces to commas
                    FIPS_CODES=$(echo "$SELECTED_FIPS" | sed 's/"//g' | tr ' ' ',')
                    # Remove any leading/trailing commas that might have been introduced
                    FIPS_CODES=$(echo "$FIPS_CODES" | sed 's/^,//;s/,$//')
                    FIPS_COUNT=$(echo "$FIPS_CODES" | tr ',' '\n' | grep -c '^[0-9]' || echo 0)
                    echo_success "Selected ${BOLD}$FIPS_COUNT${NC} FIPS code(s): ${BOLD}$FIPS_CODES${NC}"
                else
                    FIPS_CODES=""
                    echo_info "No counties selected"
                fi
            else
                echo_warning "Failed to parse county list"
                # Fallback to manual entry
                if whiptail --title "Manual Entry" --backtitle "$(whiptail_footer)" --yesno "County list could not be loaded.\n\nWould you like to enter FIPS codes manually instead?" 10 70; then
                    FIPS_CODES=$(whiptail --title "FIPS Codes" --backtitle "$(whiptail_footer)" --inputbox "Enter FIPS codes (comma-separated):\n\nExample: 039001,039003,039005" 12 70 3>&1 1>&2 2>&3)
                    if [ $? = 0 ] && [ -n "$FIPS_CODES" ]; then
                        echo_success "FIPS codes: ${BOLD}$FIPS_CODES${NC}"
                    else
                        FIPS_CODES=""
                        echo_info "No FIPS codes specified"
                    fi
                else
                    FIPS_CODES=""
                    echo_info "No FIPS codes specified"
                fi
            fi
        else
            echo_warning "No counties found for state $STATE_CODE"
            # Offer manual entry
            if whiptail --title "No Counties" --backtitle "$(whiptail_footer)" --yesno "No counties found.\n\nWould you like to enter FIPS codes manually?" 10 70; then
                FIPS_CODES=$(whiptail --title "FIPS Codes" --backtitle "$(whiptail_footer)" --inputbox "Enter FIPS codes (comma-separated):\n\nExample: 039001,039003,039005" 12 70 3>&1 1>&2 2>&3)
                if [ $? = 0 ] && [ -n "$FIPS_CODES" ]; then
                    echo_success "FIPS codes: ${BOLD}$FIPS_CODES${NC}"
                else
                    FIPS_CODES=""
                    echo_info "No FIPS codes specified"
                fi
            else
                FIPS_CODES=""
                echo_info "No FIPS codes specified"
            fi
        fi
    else
        # Lookup failed or not available yet, fall back to manual entry
        if [ -n "$LOOKUP_ERROR" ]; then
            echo_warning "FIPS lookup not available: $LOOKUP_ERROR"
        else
            echo_warning "FIPS lookup encountered an error (exit=$LOOKUP_EXIT)"
            # Show first 200 chars of result for debugging
            if [ -n "$LOOKUP_RESULT" ]; then
                echo_info "Debug: ${LOOKUP_RESULT:0:200}"
            fi
        fi
        
        if whiptail --title "FIPS Lookup Unavailable" --backtitle "$(whiptail_footer)" --yesno "FIPS code lookup is not yet available (Python environment is being set up during installation).\n\nWould you like to:\n• Enter FIPS codes manually now\n• Skip and use the web interface after installation" 14 78 --yes-button "Manual Entry" --no-button "Skip"; then
            FIPS_CODES=$(whiptail --title "FIPS Codes" --backtitle "$(whiptail_footer)" --inputbox "Enter FIPS codes manually (comma-separated):\n\nExample: 039001,039003,039005\n\nNote: Full FIPS lookup will be available in the web interface at /setup after installation." 14 78 3>&1 1>&2 2>&3)
            
            if [ $? = 0 ] && [ -n "$FIPS_CODES" ]; then
                echo_success "FIPS codes: ${BOLD}$FIPS_CODES${NC}"
            else
                FIPS_CODES=""
                echo_info "No FIPS codes specified"
            fi
        else
            FIPS_CODES=""
            echo_info "FIPS codes skipped - configure via web interface after installation"
        fi
    fi
else
    FIPS_CODES=""
    echo_info "Skipping FIPS code configuration"
fi

# Always ensure 000000 (nationwide) is included in alert FILTERING FIPS codes
# This allows the station to RECEIVE nationwide alerts (e.g., national emergencies)
# NOTE: This does NOT affect RWT broadcasts - RWT targeting is configured separately
if [ -n "$FIPS_CODES" ]; then
    # Check if 000000 is already in the list
    if ! echo ",$FIPS_CODES," | grep -q ",000000,"; then
        FIPS_CODES="000000,$FIPS_CODES"
        echo_info "Added nationwide code (000000) to receive nationwide alerts"
    fi
else
    # Even if no counties selected, set nationwide code as minimum
    FIPS_CODES="000000"
    echo_info "Using nationwide code (000000) to receive nationwide alerts"
fi

# Optional: Derive zone codes from FIPS codes
ZONE_CODES=""
if [ -n "$FIPS_CODES" ]; then
    if whiptail --title "NWS Zone Codes" --backtitle "$(whiptail_footer)" --yesno "Would you like to automatically derive NWS zone codes from your FIPS codes?\n\nZone codes are used for weather alert filtering.\n\nFIPS codes: $FIPS_CODES" 13 78; then
        echo_progress "Deriving NWS zone codes from FIPS codes..."

        # Try to derive zone codes using helper script
        ZONE_RESULT=""
        ZONE_ERROR=""

        # Disable exit on error temporarily
        set +e

        # Use system Python with SCRIPT_DIR since files aren't copied to INSTALL_DIR yet
        # The helper script is designed to work without Flask/SQLAlchemy dependencies
        if [ -f "$SCRIPT_DIR/scripts/zone_derive_helper.py" ] && command -v python3 &> /dev/null; then
            # Convert comma-separated FIPS to space-separated for script args
            FIPS_ARGS=$(echo "$FIPS_CODES" | tr ',' ' ')
            ZONE_RESULT=$(python3 "$SCRIPT_DIR/scripts/zone_derive_helper.py" $FIPS_ARGS 2>&1)
            ZONE_EXIT=$?
        else
            ZONE_EXIT=1
            if [ ! -f "$SCRIPT_DIR/scripts/zone_derive_helper.py" ]; then
                ZONE_ERROR="Zone derivation helper script not found at $SCRIPT_DIR/scripts/"
            else
                ZONE_ERROR="Python 3 not available"
            fi
        fi

        # Re-enable exit on error
        set -e
        
        if [ $ZONE_EXIT -eq 0 ] && [ -n "$ZONE_RESULT" ] && echo "$ZONE_RESULT" | grep -q "zone_codes"; then
            # Safely parse zone codes
            set +e
            # Parse both values in one Python call to avoid redundancy
            ZONE_DATA=$(echo "$ZONE_RESULT" | python3 -c "import sys, json; data=json.load(sys.stdin); print(','.join(data.get('zone_codes', [])) + '|' + str(data.get('count', 0)))" 2>/dev/null)
            PARSE_EXIT=$?
            
            if [ $PARSE_EXIT -eq 0 ] && [ -n "$ZONE_DATA" ]; then
                ZONE_CODES=$(echo "$ZONE_DATA" | cut -d'|' -f1)
                ZONE_COUNT=$(echo "$ZONE_DATA" | cut -d'|' -f2)
            else
                ZONE_CODES=""
                ZONE_COUNT=0
            fi
            set -e
            
            if [ -n "$ZONE_CODES" ] && [ "$ZONE_COUNT" -gt 0 ]; then
                echo_success "Derived ${BOLD}$ZONE_COUNT${NC} zone code(s): ${BOLD}$ZONE_CODES${NC}"
                whiptail --title "Zone Codes Derived" --backtitle "$(whiptail_footer)" --msgbox "Successfully derived $ZONE_COUNT NWS zone code(s):\n\n$ZONE_CODES\n\nThese will be saved to your configuration." 14 78
            else
                # Check if user only selected statewide/nationwide codes (ending in 000)
                HAS_COUNTY_CODES=false
                for code in $(echo "$FIPS_CODES" | tr ',' ' '); do
                    if ! echo "$code" | grep -qE '000$'; then
                        HAS_COUNTY_CODES=true
                        break
                    fi
                done

                if [ "$HAS_COUNTY_CODES" = false ]; then
                    echo_info "Statewide/nationwide FIPS codes don't require zone codes"
                    whiptail --title "No Zone Codes Needed" --backtitle "$(whiptail_footer)" --msgbox "Your FIPS codes are statewide or nationwide codes.\n\nThese are used for state/national level alerts (like Required Weekly Tests) and don't require specific zone codes.\n\nZone codes can be added later via /setup if needed." 14 78
                else
                    echo_warning "No zone codes could be derived from the provided FIPS codes"
                    whiptail --title "No Zone Codes" --backtitle "$(whiptail_footer)" --msgbox "No zone codes could be derived from your FIPS codes.\n\nYou can configure zone codes manually after installation via the web interface at /setup." 12 78
                fi
                ZONE_CODES=""
            fi
        else
            # Zone derivation failed
            if [ -n "$ZONE_ERROR" ]; then
                echo_warning "Zone code derivation not available: $ZONE_ERROR"
            else
                echo_warning "Zone code derivation encountered an error"
            fi
            
            whiptail --title "Zone Derivation Unavailable" --backtitle "$(whiptail_footer)" --msgbox "Zone code derivation is not yet available during installation.\n\nDon't worry - you can easily derive zone codes from your FIPS codes after installation using the web interface at /setup.\n\nThe web interface provides an interactive \"Derive Zone Codes\" button." 15 78
            ZONE_CODES=""
        fi
    else
        echo_info "Skipping zone code derivation"
        ZONE_CODES=""
    fi
else
    ZONE_CODES=""
fi

# Check if user is in a coastal/marine state and mention marine zones
COASTAL_STATES="AL AK CA CT DE FL GA HI IL IN LA MA MD ME MI MN MS NC NH NJ NY OH OR PA RI SC TX VA WA WI"
if echo "$COASTAL_STATES" | grep -qw "$STATE_CODE"; then
    # Determine what marine area applies
    MARINE_AREA=""
    case "$STATE_CODE" in
        MI|WI|MN|IL|IN|OH|PA|NY) MARINE_AREA="Great Lakes" ;;
        TX|LA|MS|AL) MARINE_AREA="Gulf of America" ;;
        FL) MARINE_AREA="Gulf of America and Atlantic coast" ;;
        ME|NH|MA|RI|CT|NJ|DE|MD|VA|NC|SC|GA) MARINE_AREA="Atlantic coast" ;;
        WA|OR|CA) MARINE_AREA="Pacific coast" ;;
        HI) MARINE_AREA="Pacific Ocean" ;;
        AK) MARINE_AREA="Pacific and Arctic waters" ;;
    esac

    if [ -n "$MARINE_AREA" ]; then
        whiptail --title "Marine Zones Available" --backtitle "$(whiptail_footer)" --msgbox "Your state (${STATE_CODE}) borders the ${MARINE_AREA}.\n\nMarine weather zones (for coastal/offshore alerts) can be configured after installation via the web interface at /setup.\n\nLook for zone codes starting with:\n• GMZ - Gulf of America\n• AMZ - Atlantic Marine\n• PMZ - Pacific Marine\n• LMZ/LEZ/LHZ/LSZ/LOZ - Great Lakes" 17 78
        echo_info "Marine zones for ${MARINE_AREA} can be added via /setup"
    fi
fi

# ====================================================================
# ALERT SOURCES CONFIGURATION
# ====================================================================

echo_step "Alert Sources Setup"

# NOAA Weather Alerts
if whiptail --title "NOAA Weather Alerts" --backtitle "$(whiptail_footer)" --yesno "Enable NOAA Weather Radio alerts?\n\nRecommended: Yes" 10 60 --defaultno; then
    NOAA_ENABLED="true"
    echo_success "NOAA alerts: ${BOLD}enabled${NC}"
    
    # Poll interval
    POLL_INTERVAL=$(whiptail --title "NOAA Poll Interval" --backtitle "$(whiptail_footer)" --inputbox "Enter poll interval in seconds:\n\n(Recommended: 300 seconds / 5 minutes)" 12 70 "300" 3>&1 1>&2 2>&3)
    
    if [ $? != 0 ] || [ -z "$POLL_INTERVAL" ]; then
        POLL_INTERVAL="300"
    fi
    
    echo_success "Poll interval: ${BOLD}$POLL_INTERVAL${NC} seconds"
else
    NOAA_ENABLED="false"
    POLL_INTERVAL="300"
    echo_info "NOAA alerts: ${BOLD}disabled${NC}"
fi

# IPAWS Integration
if whiptail --title "IPAWS Integration" --backtitle "$(whiptail_footer)" --yesno "Enable IPAWS (Integrated Public Alert & Warning System)?\n\nNote: Requires additional configuration" 10 70 --defaultno; then
    IPAWS_ENABLED="true"
    echo_success "IPAWS: ${BOLD}enabled${NC}"
else
    IPAWS_ENABLED="false"
    echo_info "IPAWS: ${BOLD}disabled${NC}"
fi

# ====================================================================
# AUDIO AND STREAMING CONFIGURATION
# ====================================================================

echo_step "Audio and Streaming Setup"

# Icecast streaming
if whiptail --title "Icecast Streaming" --backtitle "$(whiptail_footer)" --yesno "Enable Icecast audio streaming?\n\nAllows remote listening to monitored audio sources." 10 70; then
    ICECAST_ENABLED="true"
    echo_success "Icecast: ${BOLD}enabled${NC}"
    
    # Icecast passwords
    whiptail --title "Icecast Configuration" --backtitle "$(whiptail_footer)" --msgbox "You'll need to set passwords for Icecast.\n\nThese will be generated automatically if left blank." 10 70
    
    # Generate Icecast passwords
    ICECAST_SOURCE_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
    ICECAST_RELAY_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
    ICECAST_ADMIN_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
    
    echo_success "Icecast passwords generated"
else
    ICECAST_ENABLED="false"
    ICECAST_SOURCE_PASSWORD=""
    ICECAST_RELAY_PASSWORD=""
    ICECAST_ADMIN_PASSWORD=""
    echo_info "Icecast: ${BOLD}disabled${NC}"
fi

# ====================================================================
# HARDWARE INTEGRATION
# ====================================================================

echo_step "Hardware Integration Setup"

# GPIO Integration - automatically detect hardware availability
if [ "$HAS_GPIO" = true ]; then
    # GPIO hardware detected - ask user if they want to enable it
    if whiptail --title "GPIO Integration" --backtitle "$(whiptail_footer)" --yesno "GPIO hardware detected on this system!\n\nEnable GPIO (General Purpose Input/Output) integration?\n\nAllows control of relays, LEDs, and other hardware." 12 70 --defaultno; then
        GPIO_ENABLED="true"
        echo_success "GPIO: ${BOLD}enabled${NC}"
        
        # GPIO Pin for relay
        GPIO_PIN=$(whiptail --title "GPIO Relay Pin" --backtitle "$(whiptail_footer)" --inputbox "Enter GPIO pin number for relay control (2-27):\n\nLeave blank to disable.\nPins 2, 3, 4, 14 are reserved for Argon OLED." 13 70 3>&1 1>&2 2>&3)
        
        if [ $? = 0 ] && [ -n "$GPIO_PIN" ]; then
            echo_success "GPIO relay pin: ${BOLD}$GPIO_PIN${NC}"
        else
            GPIO_PIN=""
            echo_info "GPIO relay pin not configured"
        fi
    else
        GPIO_ENABLED="false"
        GPIO_PIN=""
        echo_info "GPIO: ${BOLD}disabled${NC}"
    fi
else
    # No GPIO hardware - automatically disable
    GPIO_ENABLED="false"
    GPIO_PIN=""
    echo_info "No GPIO hardware detected (VM or standard PC)"
    echo_info "GPIO: ${BOLD}disabled${NC} (no hardware available)"
fi

# LED Sign
if whiptail --title "LED Sign Support" --backtitle "$(whiptail_footer)" --yesno "Do you have an LED sign for displaying alerts?" 8 60 --defaultno; then
    LED_SIGN_ENABLED="true"
    echo_success "LED sign: ${BOLD}enabled${NC}"
else
    LED_SIGN_ENABLED="false"
    echo_info "LED sign: ${BOLD}disabled${NC}"
fi

# VFD Display
if whiptail --title "VFD Display Support" --backtitle "$(whiptail_footer)" --yesno "Do you have a VFD (Vacuum Fluorescent Display)?" 8 60 --defaultno; then
    VFD_DISPLAY_ENABLED="true"
    echo_success "VFD display: ${BOLD}enabled${NC}"
else
    VFD_DISPLAY_ENABLED="false"
    echo_info "VFD display: ${BOLD}disabled${NC}"
fi

# Zigbee Coordinator
ZIGBEE_ENABLED="false"
ZIGBEE_PORT="/dev/ttyUSB0"
ZIGBEE_BAUDRATE="115200"
ARGON_ZIGBEE=false

if [ "$IS_PI5" = true ]; then
    # On Pi 5, offer Argon ONE V5 as a specific option
    if whiptail --title "Argon ONE V5 Zigbee" --backtitle "$(whiptail_footer)" --yesno \
        "Are you using an Argon ONE V5 case with the Industria Zigbee module?\n\n\
The Argon Industria V5 Zigbee module (CC2652P) plugs inside the Argon ONE V5 case.\n\
This installer will:\n\
  • Configure /boot/firmware/config.txt (USB hub overlay)\n\
  • Install the Argon daemon (argononed)\n\
  • Enable Zigbee on /dev/ttyUSB0 at 115200 baud\n\n\
A reboot will be required after installation." 18 72 --defaultno; then
        ZIGBEE_ENABLED="true"
        ZIGBEE_PORT="/dev/ttyUSB0"
        ARGON_ZIGBEE=true
        echo_success "Zigbee: ${BOLD}Argon Industria V5${NC} on /dev/ttyUSB0"
    elif whiptail --title "Other Zigbee Coordinator" --backtitle "$(whiptail_footer)" --yesno \
        "Do you have a different USB Zigbee coordinator (SONOFF, SMLIGHT, ConBee II, etc.)?" 8 70 --defaultno; then
        ZIGBEE_ENABLED="true"
        ZIGBEE_PORT=$(whiptail --title "Zigbee Port" --backtitle "$(whiptail_footer)" \
            --inputbox "Serial port for Zigbee coordinator:\n\n/dev/ttyUSB0  — most USB CC2652P dongles\n/dev/ttyACM0  — ConBee II\n/dev/ttyAMA0  — GPIO UART (rare)" \
            12 70 "/dev/ttyUSB0" 3>&1 1>&2 2>&3) || ZIGBEE_PORT="/dev/ttyUSB0"
        echo_success "Zigbee: ${BOLD}enabled${NC} on $ZIGBEE_PORT"
    else
        echo_info "Zigbee coordinator: ${BOLD}disabled${NC}"
    fi
else
    # Non-Pi5: generic USB Zigbee question
    if whiptail --title "Zigbee Coordinator" --backtitle "$(whiptail_footer)" --yesno \
        "Do you have a USB Zigbee coordinator (SONOFF, SMLIGHT, ConBee II, etc.)?" 8 70 --defaultno; then
        ZIGBEE_ENABLED="true"
        ZIGBEE_PORT=$(whiptail --title "Zigbee Port" --backtitle "$(whiptail_footer)" \
            --inputbox "Serial port for Zigbee coordinator:\n\n/dev/ttyUSB0  — most USB CC2652P dongles\n/dev/ttyACM0  — ConBee II" \
            10 70 "/dev/ttyUSB0" 3>&1 1>&2 2>&3) || ZIGBEE_PORT="/dev/ttyUSB0"
        echo_success "Zigbee: ${BOLD}enabled${NC} on $ZIGBEE_PORT"
    else
        echo_info "Zigbee coordinator: ${BOLD}disabled${NC}"
    fi
fi

# ====================================================================
# FINAL CONFIGURATION SUMMARY
# ====================================================================

# Show complete configuration summary
whiptail --title "Complete Configuration Summary" --backtitle "$(whiptail_footer)" --msgbox "Installation will proceed with these settings:

ADMINISTRATOR:
• Username: $ADMIN_USERNAME
• Email: $ADMIN_EMAIL

SYSTEM:
• Hostname: $SYSTEM_HOSTNAME
• Domain: $DOMAIN_NAME
• Timezone: $TIMEZONE

EAS STATION:
• Originator: $EAS_ORIGINATOR
• Station ID: $EAS_STATION_ID
• State: $STATE_CODE
• County: $COUNTY_NAME

ALERT SOURCES:
• NOAA Alerts: $NOAA_ENABLED
• IPAWS: $IPAWS_ENABLED

FEATURES:
• Icecast Streaming: $ICECAST_ENABLED
• GPIO Integration: $GPIO_ENABLED
• LED Sign: $LED_SIGN_ENABLED
• VFD Display: $VFD_DISPLAY_ENABLED
• Zigbee Coordinator: $ZIGBEE_ENABLED${ARGON_ZIGBEE:+ (Argon ONE V5 — will configure config.txt)}

Press OK to begin installation..." 30 72

echo_success "✓ Complete configuration collected! Starting installation..."

# Set system hostname if it changed
if [ "$SYSTEM_HOSTNAME" != "$CURRENT_HOSTNAME" ]; then
    echo ""
    echo_progress "Setting system hostname to: ${BOLD}$SYSTEM_HOSTNAME${NC}"
    hostnamectl set-hostname "$SYSTEM_HOSTNAME" 2>/dev/null || {
        echo_warning "Could not set hostname using hostnamectl, trying fallback methods..."
        echo "$SYSTEM_HOSTNAME" > /etc/hostname
        hostname "$SYSTEM_HOSTNAME"
    }
    echo_success "Hostname set to: ${BOLD}$SYSTEM_HOSTNAME${NC}"
fi

echo ""
echo_progress "Generating secure database password..."
DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo_success "Database password generated (${#DB_PASSWORD} characters)"

echo ""
# Set default timezone
TIMEZONE="America/New_York"
echo_info "Default timezone: ${BOLD}$TIMEZONE${NC} (can be changed in setup wizard)"

echo ""
echo_success "✓ Configuration complete! Starting installation..."

# ====================================================================
# BEGIN INSTALLATION
# ====================================================================

echo_step "Update Package Lists"

echo_progress "Updating package lists..."
echo ""

# Disable exit-on-error temporarily to provide better error messages
set +e
apt-get update
APT_UPDATE_EXIT=$?
set -e

echo ""

if [ $APT_UPDATE_EXIT -ne 0 ]; then
    echo_error "Failed to update package lists (exit code: $APT_UPDATE_EXIT)"
    echo ""
    echo_info "Common causes:"
    echo_info "  • No internet connection"
    echo_info "  • Package repository mirrors are down"
    echo_info "  • DNS resolution issues"
    echo ""
    echo_info "Troubleshooting steps:"
    echo_info "  1. Check internet connection: ${BOLD}ping -c 3 8.8.8.8${NC}"
    echo_info "  2. Check DNS: ${BOLD}ping -c 3 archive.ubuntu.com${NC}"
    echo_info "  3. Try again later if mirrors are temporarily unavailable"
    echo ""
    echo_error "Cannot continue installation without package list updates"
    exit 1
fi

echo_success "Package lists updated"

echo_step "Install System Dependencies"

echo_info "Installing essential packages - this will take 3-5 minutes..."
echo ""
echo -e "${CYAN}Packages being installed:${NC}"
echo -e "  ${DIM}• Python 3 & development tools${NC}"
echo -e "  ${DIM}• PostgreSQL 17 with PostGIS (geographic data support)${NC}"
echo -e "  ${DIM}• Redis (in-memory caching)${NC}"
echo -e "  ${DIM}• Nginx (web server)${NC}"
echo -e "  ${DIM}• FFmpeg (audio processing)${NC}"
echo -e "  ${DIM}• SDR libraries (RTL-SDR, Airspy, SoapySDR)${NC}"
echo -e "  ${DIM}• SSL certificate tools (Certbot)${NC}"
echo ""
echo_progress "Downloading and installing packages (please wait)..."
echo ""

# Disable exit-on-error temporarily for package installation to provide better error messages
set +e

# Build base package list as array for safe expansion
BASE_PACKAGES=(
    python3
    python3-pip
    python3-venv
    python3-dev
    build-essential
    gcc
    g++
    make
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
    postgresql
    postgresql-contrib
    postgis
    postgresql-17-postgis-3
    redis-server
    nginx
    certbot
    python3-certbot-nginx
    ffmpeg
    espeak
    libespeak-ng1
    icecast2
    ca-certificates
    libusb-1.0-0
    libusb-1.0-0-dev
    usbutils
    python3-numpy
    python3-soapysdr
    soapysdr-tools
    rtl-sdr
    soapysdr-module-rtlsdr
    soapysdr-module-airspy
    airspy
    libairspy0
    git
    curl
    wget
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

# Install all packages (array expansion is safe and prevents injection)
apt-get install -y "${BASE_PACKAGES[@]}"

APT_EXIT_CODE=$?

# Re-enable exit-on-error
set -e

echo ""

if [ $APT_EXIT_CODE -ne 0 ]; then
    echo_error "Failed to install system dependencies (exit code: $APT_EXIT_CODE)"
    echo ""
    echo_info "Common causes:"
    echo_info "  • Network connection issues (cannot reach package mirrors)"
    echo_info "  • Package repository unavailable or outdated"
    echo_info "  • Conflicting packages already installed"
    echo_info "  • Insufficient disk space"
    echo ""
    echo_info "Troubleshooting steps:"
    echo_info "  1. Check internet connection: ${BOLD}ping -c 3 archive.ubuntu.com${NC}"
    echo_info "  2. Update package lists: ${BOLD}sudo apt-get update${NC}"
    echo_info "  3. Check disk space: ${BOLD}df -h${NC}"
    echo_info "  4. Try installing packages individually to identify the problem"
    echo ""
    echo_error "Installation cannot continue without required dependencies"
    exit 1
fi

echo_success "✓ System dependencies installed successfully"

# Verify SDR package installation (especially critical for Airspy and Python 3.13)
echo_progress "Verifying SDR package installation..."
SDR_VERIFICATION_FAILED=0

# Get Python version for diagnostics
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo_info "Detected Python version: $PYTHON_VERSION"

# Check for SoapySDR Python bindings (critical!)
if python3 -c "import SoapySDR" 2>/dev/null; then
    SOAPY_VERSION=$(python3 -c "import SoapySDR; print(SoapySDR.getAPIVersion())" 2>/dev/null)
    echo_success "✓ SoapySDR Python bindings installed (API: $SOAPY_VERSION)"
else
    echo_error "❌ SoapySDR Python bindings NOT found for Python $PYTHON_VERSION"
    SDR_VERIFICATION_FAILED=1
    
    # Check if this is a Python 3.13 compatibility issue
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)" 2>/dev/null; then
        echo_warning "⚠️  Python 3.13 detected - python3-soapysdr may not be available yet"
        echo_warning "   Solutions:"
        echo_warning "   1. Build SoapySDR Python bindings from source (see docs/troubleshooting/PYTHON_313_SOAPYSDR.md)"
        echo_warning "   2. Or downgrade to Python 3.12: sudo apt-get install python3.12"
    else
        echo_warning "   Run: sudo apt-get install python3-soapysdr"
    fi
fi

# Check for airspy_info utility (critical for Airspy support)
if command -v airspy_info >/dev/null 2>&1; then
    echo_success "✓ airspy_info utility installed (Airspy hardware support enabled)"
else
    echo_warning "⚠️ airspy_info utility not found - Airspy devices may not work"
    echo_warning "   Run: sudo apt-get install airspy libairspy0"
    SDR_VERIFICATION_FAILED=1
fi

# Check for SoapySDRUtil
if command -v SoapySDRUtil >/dev/null 2>&1; then
    echo_success "✓ SoapySDRUtil installed (SDR diagnostics available)"
else
    echo_warning "⚠️ SoapySDRUtil not found - SDR diagnostics unavailable"
    SDR_VERIFICATION_FAILED=1
fi

if [ $SDR_VERIFICATION_FAILED -eq 0 ]; then
    echo_success "✓ SDR packages verified successfully"
else
    echo_warning "⚠️  Some SDR packages may be missing - SDR functionality may be limited"
    echo_info "  Check installation logs above for details"
fi

echo_step "Create Service User & Directories"

# Create service user and group
echo_progress "Creating service user: ${BOLD}$SERVICE_USER${NC}"
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --shell /bin/bash --home-dir "$INSTALL_DIR" --create-home "$SERVICE_USER"
    echo_success "User $SERVICE_USER created"
else
    echo_info "User $SERVICE_USER already exists (skipping)"
fi

# Create hardware access groups if they don't exist
echo_progress "Ensuring hardware access groups exist..."
HARDWARE_GROUPS="gpio i2c spi audio plugdev dialout"
GROUPS_CREATED=0
for group in $HARDWARE_GROUPS; do
    if ! getent group "$group" >/dev/null 2>&1; then
        groupadd --system "$group" 2>/dev/null || true
        echo_info "Created group: $group"
        GROUPS_CREATED=$((GROUPS_CREATED + 1))
    fi
done

# Add service user to necessary groups for hardware access
echo_progress "Adding $SERVICE_USER to hardware access groups..."
for group in $HARDWARE_GROUPS; do
    usermod -a -G "$group" "$SERVICE_USER" 2>/dev/null || true
done

if [ $GROUPS_CREATED -gt 0 ]; then
    echo_success "Hardware access groups configured (created $GROUPS_CREATED new groups)"
else
    echo_success "Hardware access groups configured (all groups already existed)"
fi

# Add service user to systemd-journal group for log access
echo_progress "Adding $SERVICE_USER to systemd-journal group for log viewing..."
if getent group systemd-journal >/dev/null 2>&1; then
    usermod -a -G systemd-journal "$SERVICE_USER" 2>/dev/null || true
    echo_success "systemd-journal group access configured"
else
    echo_warning "systemd-journal group not found (systemd logs may not be accessible)"
fi

# Create installation directory
echo_progress "Setting up installation directory: ${BOLD}$INSTALL_DIR${NC}"
if [ ! -d "$INSTALL_DIR" ]; then
    mkdir -p "$INSTALL_DIR"
fi

# Copy application files
echo_progress "Copying application files from repository..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"

# Copy all files including .git directory for update capability
# NOTE: We KEEP .git directory so update.sh can use git to pull updates
# This enables fast git-based updates instead of slow tarball downloads
rsync -a --exclude='Dockerfile*' \
    --exclude='docker-compose*.yml' \
    --exclude='.dockerignore' \
    --exclude='docker-entrypoint*.sh' \
    --exclude='.env' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='bugs/' \
    --exclude='legacy/' \
    --exclude='bare-metal/' \
    --exclude='tests/bug_reproductions/' \
    "$REPO_ROOT/" "$INSTALL_DIR/" > /dev/null 2>&1

echo_success "Application files copied to $INSTALL_DIR"

# Verify .git directory was copied for update capability
if [ -d "$INSTALL_DIR/.git" ]; then
    echo_success "Git repository preserved - updates will use git"
    # Set proper ownership for .git directory
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR/.git"
else
    echo_warning "No .git directory - updates will download from GitHub (slower)"
    echo_info "For git-based updates, clone the repository before installing:"
    echo_info "  git clone https://github.com/KR8MER/eas-station.git ~/eas-station"
fi

# Create log directory
echo_progress "Creating log directory: ${BOLD}$LOG_DIR${NC}"
mkdir -p "$LOG_DIR"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$LOG_DIR"

# Set ownership
echo_progress "Setting file permissions..."
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"

# Install eas-config tool for post-installation configuration
if [ -f "$INSTALL_DIR/eas-config" ]; then
    chmod +x "$INSTALL_DIR/eas-config"
    ln -sf "$INSTALL_DIR/eas-config" /usr/local/bin/eas-config
    echo_success "eas-config tool installed (run: sudo eas-config)"
fi

echo_success "Permissions configured"

echo_step "Python Environment Setup"

# Create Python virtual environment
# NOTE: We explicitly DO NOT use --system-site-packages because:
#   1. System packages can conflict with venv packages (e.g., numpy, scipy, gevent)
#   2. C extension conflicts cause gunicorn workers to fail with import errors
#   3. Creates import order issues where wrong package versions get loaded
# The systemd service sets PYTHONNOUSERSITE=1 which prevents USER site-packages,
# but that doesn't help with the --system-site-packages flag (which is different).
# If you need system packages like python3-soapysdr, install them into the venv after creation.
echo_progress "Creating Python virtual environment..."
if ! sudo -u "$SERVICE_USER" python3 -m venv "$VENV_DIR" 2>&1 | tee /tmp/venv-creation.log; then
    echo_error "Failed to create virtual environment"
    echo_info "See /tmp/venv-creation.log for details"
    exit 1
fi
echo_success "Virtual environment created at $VENV_DIR"

# Install Python dependencies
echo_info "Installing Python packages for EAS Station..."
echo ""
echo -e "${CYAN}Key Python libraries:${NC}"
echo -e "  ${DIM}• Flask (web framework) & extensions${NC}"
echo -e "  ${DIM}• SQLAlchemy & Alembic (database ORM & migrations)${NC}"
echo -e "  ${DIM}• GeoAlchemy2 (PostGIS geographic queries)${NC}"
echo -e "  ${DIM}• PyRTLSDR & SoapySDR (software-defined radio)${NC}"
echo -e "  ${DIM}• NumPy & SciPy (signal processing & audio analysis)${NC}"
echo -e "  ${DIM}• Requests & lxml (CAP alert parsing)${NC}"
echo -e "  ${DIM}• And 50+ other dependencies...${NC}"
echo ""
echo_progress "Installing Python packages (main venv)..."
echo_info "This may take 5-10 minutes depending on your system"
echo_info "Full output shown below to track progress:"
echo ""
if ! sudo -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel; then
    echo_error "Failed to upgrade pip, setuptools, and wheel"
    exit 1
fi
echo ""
if ! sudo -u "$SERVICE_USER" "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"; then
    echo_error "Failed to install Python dependencies"
    exit 1
fi
echo ""
echo_success "✓ Python dependencies installed successfully"

# Create separate venv for SDR service with system site-packages
# This allows the SDR service to access python3-soapysdr from apt without PYTHONPATH hacks
# The web service uses the isolated venv above to avoid gunicorn/gevent conflicts
echo_progress "Creating SDR virtual environment (with system packages)..."
VENV_SDR_DIR="$INSTALL_DIR/venv-sdr"
if ! sudo -u "$SERVICE_USER" python3 -m venv --system-site-packages "$VENV_SDR_DIR"; then
    echo_error "Failed to create SDR virtual environment"
    exit 1
fi
echo_success "SDR virtual environment created at $VENV_SDR_DIR"

# Install minimal SDR-specific dependencies
echo_progress "Installing SDR service dependencies..."
echo_info "Installing SDR requirements (scipy, numba may take 5-15 min to compile)..."
echo_info "Full output shown below to track progress:"
echo ""
if ! sudo -u "$SERVICE_USER" "$VENV_SDR_DIR/bin/pip" install --upgrade pip; then
    echo_warning "Failed to upgrade pip in SDR venv (non-critical)"
fi
if ! sudo -u "$SERVICE_USER" "$VENV_SDR_DIR/bin/pip" install -r "$INSTALL_DIR/requirements-sdr.txt"; then
    echo_error "Failed to install SDR dependencies"
    exit 1
fi
echo ""
echo_success "✓ SDR dependencies installed successfully"

# Verify SoapySDR is accessible in SDR venv
echo_progress "Verifying SoapySDR access in SDR venv..."
if "$VENV_SDR_DIR/bin/python" -c "import SoapySDR; print('SoapySDR API:', SoapySDR.getAPIVersion())" 2>&1; then
    echo_success "✓ SoapySDR accessible in SDR venv (via system packages)"
else
    echo_warning "⚠️  SoapySDR not accessible in SDR venv"
    echo_warning "   Install: sudo apt-get install python3-soapysdr"
fi

echo_step "PostgreSQL Database Configuration"

echo_info "Configuring PostgreSQL database for EAS Station..."
echo ""
echo -e "${CYAN}Database setup tasks:${NC}"
echo -e "  ${DIM}• Create 'alerts' database with PostGIS extensions${NC}"
echo -e "  ${DIM}• Create 'eas-station' database user${NC}"
echo -e "  ${DIM}• Configure authentication (password-based)${NC}"
echo -e "  ${DIM}• Grant necessary permissions${NC}"
echo ""

# Setup PostgreSQL
echo_progress "Starting PostgreSQL service..."
systemctl enable postgresql > /dev/null 2>&1
systemctl start postgresql
echo_success "PostgreSQL service started"

# Configure PostgreSQL authentication to allow password-based connections
echo_progress "Configuring PostgreSQL authentication (pg_hba.conf)..."

# Detect PostgreSQL version to find the correct pg_hba.conf location
PG_VERSION=$(sudo -u postgres psql -tAc "SELECT version();" 2>/dev/null | grep -oP 'PostgreSQL \K[0-9]+' | head -1)
if [ -z "$PG_VERSION" ]; then
    # Fallback: try common versions
    for v in 17 16 15 14 13; do
        if [ -d "/etc/postgresql/$v" ]; then
            PG_VERSION=$v
            break
        fi
    done
fi

if [ -n "$PG_VERSION" ]; then
    PG_HBA_CONF="/etc/postgresql/$PG_VERSION/main/pg_hba.conf"
    
    if [ -f "$PG_HBA_CONF" ]; then
        echo_info "Found pg_hba.conf for PostgreSQL ${BOLD}$PG_VERSION${NC}"
        
        # Backup the original pg_hba.conf
        if [ ! -f "${PG_HBA_CONF}.backup" ]; then
            cp "$PG_HBA_CONF" "${PG_HBA_CONF}.backup"
            echo_info "Created backup: ${PG_HBA_CONF}.backup"
        fi
        
        # Check if eas-station authentication rule already exists
        if ! grep -q "^host.*alerts.*\"eas-station\".*md5" "$PG_HBA_CONF" && \
           ! grep -q "^host.*alerts.*\"eas-station\".*scram-sha-256" "$PG_HBA_CONF" && \
           ! grep -q "^host.*alerts.*eas_station.*md5" "$PG_HBA_CONF" && \
           ! grep -q "^host.*alerts.*eas_station.*scram-sha-256" "$PG_HBA_CONF"; then
            
            # Add authentication rule for eas-station user
            # Insert before the first "local all" line to ensure it takes precedence
            sed -i '/^# TYPE.*DATABASE.*USER.*ADDRESS.*METHOD/a\
# EAS Station authentication (added by install.sh)\
host    alerts          eas_station   127.0.0.1/32            scram-sha-256\
host    alerts          eas_station   ::1/128                 scram-sha-256' "$PG_HBA_CONF"
            
            echo_success "Added authentication rules for eas_station user"
            
            # Reload PostgreSQL to apply changes
            systemctl reload postgresql 2>/dev/null
            echo_success "PostgreSQL authentication configured"
        else
            echo_info "Authentication rule already exists (skipping)"
        fi
    else
        echo_warning "pg_hba.conf not found at expected location: $PG_HBA_CONF"
        echo_warning "You may need to configure PostgreSQL authentication manually"
    fi
else
    echo_warning "Could not detect PostgreSQL version"
    echo_warning "You may need to configure pg_hba.conf manually"
fi

# Create database and user with the password collected earlier
echo_progress "Creating database and user..."
if sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = 'alerts'" 2>/dev/null | grep -q 1; then
    echo_info "Database 'alerts' already exists (skipping creation)"
else
    if sudo -u postgres psql -c "CREATE DATABASE alerts;" 2>/dev/null; then
        echo_success "Database 'alerts' created successfully"
    else
        echo_warning "Database creation failed - it may already exist or there may be permission issues"
    fi
fi

# Create database user (use dollar-quoting to safely handle special characters in password)
if ! sudo -u postgres psql -tc "SELECT 1 FROM pg_user WHERE usename = 'eas_station'" 2>/dev/null | grep -q 1; then
    echo_progress "Creating database user 'eas_station'..."
    if sudo -u postgres psql <<EOF 2>/dev/null
CREATE USER eas_station WITH PASSWORD \$\$${DB_PASSWORD}\$\$;
EOF
    then
        echo_success "Database user 'eas_station' created successfully"
    else
        echo_warning "User creation failed - it may already exist"
    fi
else
    echo_info "Database user 'eas_station' already exists (updating password)"
fi

# Update password if user already exists (in case of re-running script)
sudo -u postgres psql <<EOF 2>/dev/null
ALTER USER eas_station WITH PASSWORD \$\$${DB_PASSWORD}\$\$;
EOF

sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE alerts TO eas_station;" 2>/dev/null

# Grant schema privileges (required for PostgreSQL 15+)
sudo -u postgres psql -d alerts -c "GRANT ALL ON SCHEMA public TO eas_station;" 2>/dev/null
sudo -u postgres psql -d alerts -c "GRANT CREATE ON SCHEMA public TO eas_station;" 2>/dev/null
sudo -u postgres psql -d alerts -c "ALTER SCHEMA public OWNER TO eas_station;" 2>/dev/null

# Grant privileges on all existing tables and sequences (if any)
sudo -u postgres psql -d alerts -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO eas_station;" 2>/dev/null
sudo -u postgres psql -d alerts -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO eas_station;" 2>/dev/null

# Grant default privileges for future tables and sequences
sudo -u postgres psql -d alerts -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO eas_station;" 2>/dev/null
sudo -u postgres psql -d alerts -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO eas_station;" 2>/dev/null

# Create PostGIS extensions
sudo -u postgres psql -d alerts -c "CREATE EXTENSION IF NOT EXISTS postgis;" 2>/dev/null
sudo -u postgres psql -d alerts -c "CREATE EXTENSION IF NOT EXISTS postgis_topology;" 2>/dev/null

echo_success "PostgreSQL configured"

# Command-line database access
echo ""
echo_info "Database access available via: ${BOLD}sudo -u postgres psql -d alerts${NC}"
echo ""


echo_step "Redis Configuration"

# Setup Redis
echo_progress "Enabling and starting Redis service..."
systemctl enable redis-server > /dev/null 2>&1
systemctl start redis-server
echo_success "Redis configured and running"

echo_step "Icecast Streaming Server Configuration"

# Setup Icecast
echo_progress "Enabling and starting Icecast2 service..."
echo_info "Icecast2 is REQUIRED for audio streaming functionality"

# Enable Icecast2
systemctl enable icecast2 > /dev/null 2>&1

# Start Icecast2
systemctl start icecast2 2>/dev/null || {
    echo_warning "Icecast2 failed to start (may need password configuration)"
    echo_info "Passwords will be auto-configured via web interface"
}

# Check if Icecast is running
if systemctl is-active --quiet icecast2; then
    echo_success "Icecast2 configured and running"
    # Get Icecast port
    ICECAST_PORT=$(grep -o '<port>[0-9]*</port>' /etc/icecast2/icecast.xml 2>/dev/null | head -1 | grep -o '[0-9]*' || echo "8000")
    echo_info "Icecast server listening on port: ${BOLD}$ICECAST_PORT${NC}"
else
    echo_warning "Icecast2 installed but not running - will be configured via web UI"
    echo_info "Configure at: /admin/icecast after logging in"
fi

echo_step "Create Configuration File"

# Backup existing .env file if it exists and is not empty
if [ -f "$CONFIG_FILE" ]; then
    # Check if file has meaningful content (more than just comments/whitespace)
    # Pattern matches lines that start with non-comment, non-whitespace characters followed by '='
    if grep -qE '^\s*[^#\s].*=' "$CONFIG_FILE" 2>/dev/null; then
        BACKUP_FILE="${CONFIG_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
        cp "$CONFIG_FILE" "$BACKUP_FILE"
        echo_info "Backed up existing configuration to: $BACKUP_FILE"
    else
        echo_info "Overwriting empty template .env file"
    fi
fi

echo_info "Creating configuration file..."

# Generate a secure SECRET_KEY automatically
echo_info "Generating secure SECRET_KEY..."
GENERATED_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Create the .env file with collected configuration
cat > "$CONFIG_FILE" << EOF
# EAS Station Configuration - Bare Metal Deployment
# This file was auto-generated during installation on $(date)

# Flask Secret Key (auto-generated - keep this secure!)
SECRET_KEY=$GENERATED_SECRET_KEY

# System Configuration
HOSTNAME=$SYSTEM_HOSTNAME
DOMAIN_NAME=$DOMAIN_NAME

# Database Configuration
DATABASE_URL=postgresql+psycopg2://eas_station:$DB_PASSWORD@127.0.0.1:5432/alerts

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Application Settings
FLASK_ENV=production
FLASK_DEBUG=false
DEFAULT_TIMEZONE=$TIMEZONE

# Location Settings
DEFAULT_COUNTY_NAME=$COUNTY_NAME
DEFAULT_STATE_CODE=$STATE_CODE
EAS_MANUAL_FIPS_CODES=$FIPS_CODES
DEFAULT_ZONE_CODES=$ZONE_CODES

# EAS Broadcast Settings
EAS_BROADCAST_ENABLED=true
EAS_ORIGINATOR=$EAS_ORIGINATOR
EAS_STATION_ID=$EAS_STATION_ID

# Alert Source Configuration
NOAA_ALERTS_ENABLED=$NOAA_ENABLED
CAP_POLL_INTERVAL=$POLL_INTERVAL
IPAWS_ENABLED=$IPAWS_ENABLED

# SDR Settings (Configure via web interface)
SDR_ENABLED=false
SDR_ARGS=driver=rtlsdr

# Audio Settings
AUDIO_STREAMING_PORT=5002
AUDIO_INGEST_ENABLED=false

# Icecast Settings
ICECAST_ENABLED=$ICECAST_ENABLED
ICECAST_SERVER=localhost
ICECAST_PORT=8000
ICECAST_EXTERNAL_PORT=8001
ICECAST_PUBLIC_HOSTNAME=$DOMAIN_NAME
ICECAST_LOCATION=$COUNTY_NAME
ICECAST_ADMIN=$ADMIN_EMAIL
ICECAST_MAX_CLIENTS=100
ICECAST_SOURCE_PASSWORD=$ICECAST_SOURCE_PASSWORD
ICECAST_RELAY_PASSWORD=$ICECAST_RELAY_PASSWORD
ICECAST_ADMIN_PASSWORD=$ICECAST_ADMIN_PASSWORD

# Hardware Integration
LED_SIGN_ENABLED=$LED_SIGN_ENABLED
VFD_DISPLAY_ENABLED=$VFD_DISPLAY_ENABLED

# Zigbee Coordinator (read by DB migration to pre-configure hardware_settings table)
ZIGBEE_ENABLED=$ZIGBEE_ENABLED
ZIGBEE_PORT=$ZIGBEE_PORT
ZIGBEE_BAUDRATE=$ZIGBEE_BAUDRATE

# Text-to-Speech Settings (Configure via web interface)
EAS_TTS_PROVIDER=pyttsx3

# Administrator Account (configured during install)
# Login at https://$DOMAIN_NAME/ with username: $ADMIN_USERNAME
EOF
chown "$SERVICE_USER:$SERVICE_GROUP" "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"
echo_success "Configuration created with auto-generated SECRET_KEY"

echo_step "Install Systemd Services"

# Install systemd service files
# SDR service uses venv-sdr (with --system-site-packages) for direct python3-soapysdr access
# This eliminates the need for complex PYTHONPATH configuration
echo_progress "Installing systemd service files..."
cp "$INSTALL_DIR/systemd/"*.service /etc/systemd/system/
cp "$INSTALL_DIR/systemd/"*.target /etc/systemd/system/
cp "$INSTALL_DIR/systemd/"*.timer /etc/systemd/system/ 2>/dev/null || true

systemctl daemon-reload
echo_success "Systemd service files installed"

echo_step "Sudoers Configuration"

# Install sudoers configuration for certbot/nginx management
echo_progress "Installing sudoers configuration for SSL certificate management..."
if [ -f "$INSTALL_DIR/config/sudoers-eas-station" ]; then
    cp "$INSTALL_DIR/config/sudoers-eas-station" /etc/sudoers.d/eas-station
    chmod 0440 /etc/sudoers.d/eas-station

    # Validate sudoers syntax
    if visudo -c -f /etc/sudoers.d/eas-station &>/dev/null; then
        echo_success "Sudoers configuration installed and validated"
    else
        echo_error "Invalid sudoers syntax - removing file"
        rm -f /etc/sudoers.d/eas-station
    fi
else
    echo_warning "Sudoers configuration file not found (config/sudoers-eas-station)"
fi

# Create certbot data directories with proper permissions
# These directories must be writable by both the eas-station user and root (for certbot via sudo)
echo_progress "Creating certbot data directories..."
CERTBOT_DATA_DIR="$INSTALL_DIR/certbot_data"
mkdir -p "$CERTBOT_DATA_DIR/config" "$CERTBOT_DATA_DIR/work" "$CERTBOT_DATA_DIR/logs"
chmod -R 777 "$CERTBOT_DATA_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$CERTBOT_DATA_DIR"
echo_success "Certbot data directories created"

# Create ACME challenge directory for certbot webroot method
# This allows Let's Encrypt to verify domain ownership via HTTP-01 challenge
# Path matches nginx config: location /.well-known/acme-challenge/ { root /var/www/certbot; }
# IMPORTANT: Must be owned by root:root (certbot runs as root) with 755 permissions
# This allows certbot to write challenge files as root, and nginx to read them as www-data
echo_progress "Creating ACME challenge directory..."
mkdir -p /var/www/certbot/.well-known/acme-challenge
chown -R root:root /var/www/certbot
chmod -R 755 /var/www/certbot
echo_success "ACME challenge directory created (root:root 755)"

# ====================================================================
# ARGON ONE V5 HARDWARE CONFIGURATION (only if selected)
# ====================================================================

if [ "$ARGON_ZIGBEE" = true ]; then
    echo ""
    echo_progress "Configuring Argon ONE V5 Zigbee hardware..."

    CONFIG_TXT="/boot/firmware/config.txt"

    if [ -f "$CONFIG_TXT" ]; then
        # Check if config is already set (idempotent)
        if ! grep -q "dtoverlay=dwc2,dr_mode=host" "$CONFIG_TXT"; then
            # Find the [all] section and insert after it, or append if not found
            if grep -q "^\[all\]" "$CONFIG_TXT"; then
                # Insert the two overlay lines immediately after [all]
                sed -i '/^\[all\]/a dtoverlay=dwc2,dr_mode=host\nusb_max_current_enable=1' "$CONFIG_TXT"
                echo_success "Added USB hub overlays under [all] in $CONFIG_TXT"
            else
                # Append an [all] section at the end
                printf '\n[all]\ndtoverlay=dwc2,dr_mode=host\nusb_max_current_enable=1\n' >> "$CONFIG_TXT"
                echo_success "Appended [all] section with USB hub overlays to $CONFIG_TXT"
            fi
        else
            echo_info "Argon USB hub overlays already present in $CONFIG_TXT (skipping)"
        fi
    else
        echo_warning "$CONFIG_TXT not found — skipping Argon config.txt setup"
        echo_warning "Manually add under [all] in your boot config:"
        echo_warning "  dtoverlay=dwc2,dr_mode=host"
        echo_warning "  usb_max_current_enable=1"
    fi

    # Install Argon ONE V5 daemon (fan control + USB hub power)
    if ! command -v argonone-cli &>/dev/null && ! systemctl is-active --quiet argononed 2>/dev/null; then
        echo_progress "Installing Argon ONE V5 daemon..."
        set +e
        curl -sSL https://download.argon40.com/argon1v5.sh -o /tmp/argon1v5.sh
        CURL_EXIT=$?
        set -e

        if [ $CURL_EXIT -eq 0 ] && [ -f /tmp/argon1v5.sh ]; then
            bash /tmp/argon1v5.sh
            rm -f /tmp/argon1v5.sh
            systemctl enable argononed.service 2>/dev/null || true
            echo_success "Argon ONE V5 daemon installed and enabled"
        else
            echo_warning "Could not download Argon daemon — install manually after reboot:"
            echo_warning "  curl https://download.argon40.com/argon1v5.sh | bash"
        fi
    else
        echo_info "Argon daemon already installed (skipping)"
    fi

    echo_warning "*** A reboot is required before the Zigbee module will appear as /dev/ttyUSB0 ***"
fi

echo_step "Nginx Web Server Configuration"

# Configure nginx
echo_progress "Setting up nginx reverse proxy..."
if [ ! -f /etc/nginx/sites-available/eas-station ]; then
    cp "$INSTALL_DIR/config/nginx-eas-station.conf" /etc/nginx/sites-available/eas-station
    
    # Generate self-signed certificate for initial setup
    if [ ! -f /etc/ssl/private/eas-station-selfsigned.key ]; then
        echo_progress "Generating self-signed SSL certificate..."
        mkdir -p /etc/ssl/private
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout /etc/ssl/private/eas-station-selfsigned.key \
            -out /etc/ssl/certs/eas-station-selfsigned.crt \
            -subj "/C=US/ST=State/L=City/O=EAS Station/CN=localhost"
    fi
    
    # Enable site
    ln -sf /etc/nginx/sites-available/eas-station /etc/nginx/sites-enabled/
    
    # Remove default site if it exists
    rm -f /etc/nginx/sites-enabled/default
    
    # Test nginx configuration
    nginx -t && systemctl reload nginx
    echo_success "Nginx configured"
else
    echo_info "Nginx configuration already exists (skipping)"
fi

echo_step "SSL Certificate Configuration"

# Automatic Let's Encrypt SSL certificate setup
if [[ "$DOMAIN_NAME" != "localhost" ]] && ! [[ "$DOMAIN_NAME" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo_info "Domain detected: $DOMAIN_NAME"

    if whiptail --title "SSL Certificate Setup" --backtitle "$(whiptail_footer)" --yesno "Would you like to automatically obtain an SSL certificate from Let's Encrypt for $DOMAIN_NAME?\n\nRequirements:\n• Domain must point to this server's public IP\n• Ports 80 and 443 must be accessible from internet\n• Valid email address for certificate notifications\n\nSelect 'No' to skip (you can run 'sudo certbot --nginx -d $DOMAIN_NAME' later)" 18 75; then

        echo_progress "Checking DNS resolution for $DOMAIN_NAME..."

        # Check if domain resolves
        if host "$DOMAIN_NAME" > /dev/null 2>&1; then
            RESOLVED_IP=$(host "$DOMAIN_NAME" | grep "has address" | head -n1 | awk '{print $NF}')
            echo_success "Domain resolves to: $RESOLVED_IP"

            # Get server's public IP
            SERVER_IP=$(curl -s -4 ifconfig.me 2>/dev/null || curl -s -4 icanhazip.com 2>/dev/null || echo "unknown")

            if [ "$SERVER_IP" != "unknown" ]; then
                if [ "$RESOLVED_IP" = "$SERVER_IP" ]; then
                    echo_success "DNS correctly points to this server"
                else
                    echo_warning "DNS points to $RESOLVED_IP but this server's public IP is $SERVER_IP"
                    if ! whiptail --title "DNS Mismatch" --backtitle "$(whiptail_footer)" --yesno "DNS does not point to this server. Continue anyway?\n\n(Certificate issuance may fail)" 10 70; then
                        echo_info "Skipping Let's Encrypt setup"
                        continue
                    fi
                fi
            fi

            # Prompt for email if not already set
            if [ -z "$ADMIN_EMAIL" ] || [ "$ADMIN_EMAIL" = "admin@localhost" ]; then
                SSL_EMAIL=$(whiptail --title "SSL Email" --backtail "$(whiptail_footer)" --inputbox "Enter email for SSL certificate notifications:" 10 70 "" 3>&1 1>&2 2>&3)
            else
                SSL_EMAIL="$ADMIN_EMAIL"
            fi

            # Ask about staging mode
            STAGING_FLAG=""
            if whiptail --title "Staging Mode" --backtitle "$(whiptail_footer)" --yesno "Use Let's Encrypt staging server?\n\nRecommended for testing. Staging certificates are not trusted by browsers but won't count against rate limits (50 certs/week).\n\nSelect 'No' for production certificate." 14 70; then
                STAGING_FLAG="--staging"
                echo_info "Using Let's Encrypt staging server"
            else
                echo_info "Using Let's Encrypt production server"
            fi

            echo_progress "Requesting SSL certificate from Let's Encrypt..."

            # Stop nginx temporarily for standalone mode (more reliable)
            systemctl stop nginx

            # Run certbot
            if certbot certonly --standalone --non-interactive --agree-tos --email "$SSL_EMAIL" -d "$DOMAIN_NAME" $STAGING_FLAG; then
                echo_success "SSL certificate obtained successfully!"

                # Update nginx config to use Let's Encrypt certificates
                sed -i "s|ssl_certificate /etc/ssl/certs/eas-station-selfsigned.crt;|ssl_certificate /etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem;|g" /etc/nginx/sites-available/eas-station
                sed -i "s|ssl_certificate_key /etc/ssl/private/eas-station-selfsigned.key;|ssl_certificate_key /etc/letsencrypt/live/$DOMAIN_NAME/privkey.pem;|g" /etc/nginx/sites-available/eas-station

                # Test nginx config
                if nginx -t; then
                    systemctl start nginx
                    echo_success "Nginx restarted with Let's Encrypt certificate"
                else
                    echo_error "Nginx configuration test failed, reverting to self-signed"
                    sed -i "s|ssl_certificate /etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem;|ssl_certificate /etc/ssl/certs/eas-station-selfsigned.crt;|g" /etc/nginx/sites-available/eas-station
                    sed -i "s|ssl_certificate_key /etc/letsencrypt/live/$DOMAIN_NAME/privkey.pem;|ssl_certificate_key /etc/ssl/private/eas-station-selfsigned.key;|g" /etc/nginx/sites-available/eas-station
                    systemctl start nginx
                fi

                # Enable certbot renewal timer
                echo_progress "Enabling automatic certificate renewal..."
                systemctl enable certbot.timer
                systemctl start certbot.timer
                echo_success "Certbot renewal timer enabled (checks twice daily)"

                # Add SSL_EMAIL to .env
                echo "SSL_EMAIL=$SSL_EMAIL" >> "$CONFIG_DIR/.env"

                # Set flag for post-install message
                SSL_CONFIGURED=true

            else
                echo_error "Failed to obtain SSL certificate from Let's Encrypt"
                echo_warning "Using self-signed certificate instead"
                echo_info "You can manually request a certificate later with:"
                echo_info "  sudo certbot --nginx -d $DOMAIN_NAME"
                systemctl start nginx
            fi
        else
            echo_warning "Domain $DOMAIN_NAME does not resolve to an IP address"
            echo_info "Skipping Let's Encrypt setup. Configure DNS first, then run:"
            echo_info "  sudo certbot --nginx -d $DOMAIN_NAME"
        fi
    else
        echo_info "Skipping automatic SSL setup"
        echo_info "You can manually request a certificate later with:"
        echo_info "  sudo certbot --nginx -d $DOMAIN_NAME"
    fi
else
    echo_info "Using localhost or IP address - self-signed certificate will be used"
    echo_info "For production SSL, configure a domain name and run:"
    echo_info "  sudo certbot --nginx -d your-domain.com"
fi

echo_step "Firewall Configuration"

# Configure UFW firewall for remote access
echo_progress "Configuring firewall for remote access..."

# Check if UFW is installed (it was installed in step 3)
if command -v ufw &> /dev/null; then
    # Enable UFW if not already enabled
    if ! ufw status verbose | grep -q "Status: active"; then
        echo_progress "Enabling UFW firewall..."
        # Set default policies
        ufw --force default deny incoming > /dev/null 2>&1
        ufw --force default allow outgoing > /dev/null 2>&1
        echo_info "Default policies set (deny incoming, allow outgoing)"
    fi
    
    # Allow SSH (important - don't lock yourself out!)
    echo_progress "Allowing SSH (port 22)..."
    ufw allow 22/tcp > /dev/null 2>&1
    echo_success "SSH access allowed"
    
    # Allow HTTP (port 80) for Let's Encrypt and redirects
    echo_progress "Allowing HTTP (port 80)..."
    ufw allow 80/tcp > /dev/null 2>&1
    echo_success "HTTP access allowed"
    
    # Allow HTTPS (port 443) for web interface
    echo_progress "Allowing HTTPS (port 443)..."
    ufw allow 443/tcp > /dev/null 2>&1
    echo_success "HTTPS access allowed"
    
    # Allow Icecast streaming (port 8000) if enabled
    if [ "${ICECAST_ENABLED:-true}" = "true" ]; then
        echo_progress "Allowing Icecast streaming (port 8000)..."
        ufw allow 8000/tcp > /dev/null 2>&1
        echo_success "Icecast streaming access allowed"
    fi
    
    # Allow PostgreSQL (port 5432) for remote database access (optional, commented by default)
    # Uncomment if you need remote database access for IDE tools like DataGrip, DBeaver, etc.
    # echo_progress "Allowing PostgreSQL (port 5432)..."
    # ufw allow 5432/tcp > /dev/null 2>&1
    # echo_success "PostgreSQL access allowed"
    
    # Enable UFW
    echo_progress "Activating firewall rules..."
    ufw --force enable > /dev/null 2>&1
    echo_success "Firewall configured and active"
    
    # Show status
    echo ""
    echo_info "Firewall status:"
    ufw status numbered | grep -E '\b(22|80|443|8000|5432)/(tcp|udp)\b|Status:' || true
    echo ""
else
    echo_warning "UFW not found - firewall not configured"
    echo_warning "Install UFW manually: apt-get install ufw"
fi

echo_step "Initialize Database Schema"

# Initialize database
echo_progress "Initializing database schema..."
cd "$INSTALL_DIR"

# Check if this is a fresh install or an upgrade
echo_progress "Checking database state..."

# Query to count existing application tables (excluding alembic_version and PostGIS tables)
# This ensures we don't count alembic_version or spatial_ref_sys as "existing data"
TABLE_COUNT_QUERY="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' AND table_name NOT IN ('alembic_version', 'spatial_ref_sys');"

# Disable exit-on-error temporarily for this check
set +e
DB_HAS_TABLES=$(sudo -u postgres psql -d alerts -tAc "$TABLE_COUNT_QUERY" 2>/dev/null)
DB_CHECK_EXIT=$?
set -e

# If the query failed, assume fresh install
if [ $DB_CHECK_EXIT -ne 0 ] || [ -z "$DB_HAS_TABLES" ]; then
    echo_warning "Could not check database state (assuming fresh install)"
    DB_HAS_TABLES="0"
fi

# Trim whitespace
DB_HAS_TABLES=$(echo "$DB_HAS_TABLES" | xargs)

echo_info "Database has $DB_HAS_TABLES application tables"

if [ "$DB_HAS_TABLES" -eq "0" ]; then
    # Fresh install - run migrations to create schema AND populate initial data
    echo_info "Fresh installation detected - initializing database with migrations..."
    echo_info "Using Alembic migrations to create schema and populate initial data"
    echo ""

    if [ -f "$INSTALL_DIR/alembic.ini" ]; then
        echo_progress "Running Alembic migrations for fresh install..."
        echo_info "This will create all tables and populate settings from environment variables"
        echo ""

        # Disable exit-on-error for migrations
        set +e
        # Run Alembic directly (no output capture) so user sees real-time feedback
        # IMPORTANT: Run from install directory to ensure .env file is found
        sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$VENV_DIR/bin/alembic' upgrade head"
        ALEMBIC_EXIT_CODE=$?
        set -e

        echo ""
        if [ $ALEMBIC_EXIT_CODE -eq 0 ]; then
            echo_success "✓ Database schema created and initial data populated"
            echo_info "Hardware and Icecast settings auto-configured from environment variables"
        else
            echo_warning "Alembic migrations encountered errors (exit code: $ALEMBIC_EXIT_CODE)"
            echo ""
            echo_info "Attempting fallback: creating schema with db.create_all()..."

            set +e
            INIT_OUTPUT=$(sudo -u "$SERVICE_USER" "$VENV_DIR/bin/python" -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('✓ Database schema created successfully')
    print('⚠️  WARNING: Initial data not populated - you may need to configure settings manually')
" 2>&1)
            INIT_EXIT=$?
            set -e

            if [ $INIT_EXIT -eq 0 ]; then
                echo "$INIT_OUTPUT"
                echo ""
                echo_warning "Schema created but settings tables may be empty"
                echo_info "Configure via web UI at /admin/hardware and /settings/audio"
            else
                echo_error "Database initialization failed completely (exit code: $INIT_EXIT)"
                echo_info "Output: $INIT_OUTPUT"
            fi
        fi
    else
        echo_warning "alembic.ini not found - using fallback db.create_all()"
        echo_info "WARNING: Settings will not be auto-populated from environment"
        echo ""

        set +e
        INIT_OUTPUT=$(sudo -u "$SERVICE_USER" "$VENV_DIR/bin/python" -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('✓ Database schema created')
    print('⚠️  WARNING: Configure hardware and Icecast settings via web UI')
" 2>&1)
        INIT_EXIT=$?
        set -e

        if [ $INIT_EXIT -eq 0 ]; then
            echo "$INIT_OUTPUT"
        else
            echo_error "Database initialization failed (exit code: $INIT_EXIT)"
            echo_info "Output: $INIT_OUTPUT"
        fi
    fi
else
    # Existing database - run migrations to upgrade schema
    echo_info "Existing database detected ($DB_HAS_TABLES tables found)"
    echo_info "Running Alembic migrations for database upgrade..."
    echo ""
    
    if [ -f "$INSTALL_DIR/alembic.ini" ]; then
        echo_progress "Running Alembic migrations..."
        echo_info "This may take a few moments. Output will be shown below:"
        echo_info "Press Ctrl+C to cancel if needed (changes will be rolled back)"
        echo ""
        
        # Disable exit-on-error for migrations
        set +e
        # Run Alembic directly (no output capture) so user sees real-time feedback
        # and can interrupt with Ctrl+C if needed
        # IMPORTANT: Run from install directory to ensure .env file is found
        sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$VENV_DIR/bin/alembic' upgrade head"
        ALEMBIC_EXIT_CODE=$?
        set -e
        
        echo ""
        if [ $ALEMBIC_EXIT_CODE -eq 0 ]; then
            echo_success "✓ Database migrations completed successfully"
        elif [ $ALEMBIC_EXIT_CODE -eq 130 ]; then
            echo_warning "Migration cancelled by user (Ctrl+C)"
            echo_info "Database state may be partially migrated"
            echo_info "To retry: sudo -u $SERVICE_USER bash -c 'cd $INSTALL_DIR && $VENV_DIR/bin/alembic upgrade head'"
        else
            echo_warning "Alembic migrations encountered errors (exit code: $ALEMBIC_EXIT_CODE)"
            echo ""
            echo_info "Common causes:"
            echo_info "  • Database connection failed (check DATABASE_URL)"
            echo_info "  • PostgreSQL/PostGIS not running"
            echo_info "  • Migration script has errors"
            echo ""
            echo_info "Attempting to create any missing tables with db.create_all()..."
            
            set +e
            sudo -u "$SERVICE_USER" "$VENV_DIR/bin/python" -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('✓ Missing tables created')
"
            set -e
            
            echo ""
            echo_warning "Database upgrade may be incomplete - check logs after installation"
            echo_info "You can manually run migrations:"
            echo_info "  sudo -u $SERVICE_USER bash -c 'cd $INSTALL_DIR && $VENV_DIR/bin/alembic upgrade head'"
        fi
    else
        echo_warning "alembic.ini not found - skipping migrations"
        echo_info "Using db.create_all() to create any missing tables..."
        echo ""
        
        set +e
        sudo -u "$SERVICE_USER" "$VENV_DIR/bin/python" -c "
from app import app, db
with app.app_context():
    db.create_all()
    print('✓ Missing tables created')
"
        DB_EXIT_CODE=$?
        set -e
        
        echo ""
        if [ $DB_EXIT_CODE -eq 0 ]; then
            echo_success "✓ Database tables created"
        else
            echo_warning "Database operation failed (non-critical)"
        fi
    fi
fi

# Download NWS GIS data (zone catalog + partial-county subdivisions)
echo ""
echo_info "Downloading NWS GIS data (zone catalog + partial-county subdivisions)..."
echo_info "Sources:"
echo_info "  Zones:     https://www.weather.gov/gis/PublicZones"
echo_info "  Subdivisions: https://www.weather.gov/gis/NWRPartialCounties"
echo_info "  (Hazard Services partial-county spec: https://vlab.noaa.gov/web/hazard-services/partial-county-alerts)"
set +e
sudo -u "$SERVICE_USER" "$VENV_DIR/bin/python" "$INSTALL_DIR/tools/download_nws_gis_data.py" 2>&1
GIS_EXIT_CODE=$?
set -e
if [ $GIS_EXIT_CODE -eq 0 ]; then
    echo_success "✓ NWS GIS data downloaded"
else
    echo_warning "NWS GIS data download failed (non-critical – connectivity issue?)"
    echo_warning "Re-run later:  sudo -u $SERVICE_USER $VENV_DIR/bin/python $INSTALL_DIR/tools/download_nws_gis_data.py"
fi

# Create administrator account in database
echo ""
echo_info "Creating administrator account in database..."

# Create the administrator account using environment variables to avoid injection
export EAS_ADMIN_USERNAME="$ADMIN_USERNAME"
export EAS_ADMIN_PASSWORD="$ADMIN_PASSWORD"

sudo -u "$SERVICE_USER" -E "$VENV_DIR/bin/python" << 'EOPY'
import sys
import os
from app import app, db
from app_core.models import AdminUser
from app_core.auth.roles import Role, RoleDefinition
from sqlalchemy import func

username = os.environ.get('EAS_ADMIN_USERNAME')
password = os.environ.get('EAS_ADMIN_PASSWORD')

if not username or not password:
    print("ERROR: Username or password not provided", file=sys.stderr)
    sys.exit(1)

with app.app_context():
    # Check if user already exists
    existing = AdminUser.query.filter(func.lower(AdminUser.username) == username.lower()).first()
    if existing:
        print(f"ERROR: User '{username}' already exists", file=sys.stderr)
        sys.exit(1)
    
    # Create new admin user
    admin_user = AdminUser(username=username)
    admin_user.set_password(password)
    
    # Assign admin role - CRITICAL: Must assign role or user will have no permissions
    admin_role = Role.query.filter(func.lower(Role.name) == RoleDefinition.ADMIN.value).first()
    if not admin_role:
        print(f"ERROR: Admin role not found in database. Roles must be created by migrations first.", file=sys.stderr)
        print(f"Available roles: {[r.name for r in Role.query.all()]}", file=sys.stderr)
        sys.exit(1)
    
    admin_user.role = admin_role
    admin_user.role_id = admin_role.id
    
    db.session.add(admin_user)
    db.session.commit()
    
    print(f"Administrator account '{username}' created successfully with role '{admin_role.name}'")
EOPY

# Unset the environment variables
unset EAS_ADMIN_USERNAME
unset EAS_ADMIN_PASSWORD

if [ $? -eq 0 ]; then
    echo_success "Administrator account created"
else
    echo_error "Failed to create administrator account"
    echo_warning "You can create an account later via the web interface at /setup/admin"
fi

# Create udev rules for USB devices
echo_info "Creating udev rules for SDR devices..."
cat > /etc/udev/rules.d/99-eas-station-sdr.rules << 'EOF'
# RTL-SDR
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", GROUP="plugdev", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", GROUP="plugdev", MODE="0666"

# Airspy
SUBSYSTEM=="usb", ATTRS{idVendor}=="1d50", ATTRS{idProduct}=="60a1", GROUP="plugdev", MODE="0666"

# HackRF
SUBSYSTEM=="usb", ATTRS{idVendor}=="1d50", ATTRS{idProduct}=="6089", GROUP="plugdev", MODE="0666"
EOF
udevadm control --reload-rules
udevadm trigger
echo_success "Udev rules created"

# Enable and start services
echo_step "Start EAS Station Services"

# Enable and start services
echo_progress "Enabling services for automatic startup..."
systemctl enable eas-station.target > /dev/null 2>&1
systemctl enable nginx > /dev/null 2>&1
echo_success "Services enabled"

# Start the services automatically
echo_progress "Starting nginx web server..."
systemctl start nginx
echo_success "Nginx started"

echo_progress "Starting all EAS Station services..."
systemctl start eas-station.target

# Give services a moment to start
sleep 3

# Check if services started successfully
if systemctl is-active --quiet eas-station.target; then
    echo_success "✓ All services started successfully!"
else
    echo_warning "Services may need attention"
    echo_info "Check status: ${BOLD}sudo systemctl status eas-station.target${NC}"
fi

# ====================================================================
# INSTALLATION COMPLETE - DISPLAY FINAL MESSAGE
# ====================================================================

clear
echo ""
echo -e "${BOLD}${GREEN}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║   ██████╗ ██████╗ ███╗   ███╗██████╗ ██╗     ███████╗████████╗██████╗ ║
║  ██╔════╝██╔═══██╗████╗ ████║██╔══██╗██║     ██╔════╝╚══██╔══╝██╔═══╝ ║
║  ██║     ██║   ██║██╔████╔██║██████╔╝██║     █████╗     ██║   █████╗  ║
║  ██║     ██║   ██║██║╚██╔╝██║██╔═══╝ ██║     ██╔══╝     ██║   ██╔══╝  ║
║  ╚██████╗╚██████╔╝██║ ╚═╝ ██║██║     ███████╗███████╗   ██║   ███████╗║
║   ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝   ╚═╝   ╚══════╝║
║                                                                       ║
║                 🎉  Installation Successful!  🎉                        ║
║                                                                       ║
║             Your EAS Station is now up and running!                   ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Show celebration animation
show_celebration "Installation completed successfully!"

# Show elapsed time
show_elapsed_time
echo ""

echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${WHITE}  📂 INSTALLATION SUMMARY${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}Installation Directory:${NC} ${BOLD}$INSTALL_DIR${NC}"
echo -e "  ${CYAN}Configuration File:${NC}     ${BOLD}$CONFIG_FILE${NC}"
echo -e "  ${CYAN}Log Directory:${NC}          ${BOLD}$LOG_DIR${NC}"
echo -e "  ${CYAN}Service User:${NC}           ${BOLD}$SERVICE_USER${NC}"
echo ""
echo -e "  ${GREEN}✓${NC} Services started automatically"
echo -e "  ${GREEN}✓${NC} SECRET_KEY auto-generated"
echo -e "  ${GREEN}✓${NC} Database schema initialized"
echo -e "  ${GREEN}✓${NC} Administrator account created: ${BOLD}${ADMIN_USERNAME}${NC}"
echo -e "  ${GREEN}✓${NC} System hostname: ${BOLD}${SYSTEM_HOSTNAME}${NC}"
echo -e "  ${GREEN}✓${NC} Domain name: ${BOLD}${DOMAIN_NAME}${NC}"
echo -e "  ${GREEN}✓${NC} EAS Originator: ${BOLD}${EAS_ORIGINATOR}${NC}"
echo -e "  ${GREEN}✓${NC} Station Callsign: ${BOLD}${EAS_STATION_ID}${NC}"
echo ""

echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${WHITE}  🌐 ACCESS YOUR EAS STATION${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""

# Get the primary IP address
PRIMARY_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$PRIMARY_IP" ]; then
    PRIMARY_IP="<your-server-ip>"
fi

echo -e "  Open your web browser and navigate to:"
echo ""
echo -e "    ${BOLD}${GREEN}https://localhost${NC}      ${DIM}(from this server)${NC}"
echo -e "    ${BOLD}${GREEN}https://${PRIMARY_IP}${NC}  ${DIM}(from any device on your network)${NC}"
echo ""
echo -e "  ${GREEN}✓${NC}  Firewall configured: Ports 80 (HTTP) and 443 (HTTPS) are open"
echo -e "  ${GREEN}✓${NC}  Remote access enabled: Access from any device on your network"
echo ""
echo -e "  ${YELLOW}⚠️${NC}  You'll see a certificate warning - this is ${BOLD}normal${NC}"
echo -e "      Click 'Advanced' → 'Proceed' (certificate was generated during install)"
echo ""

echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${WHITE}  🔐 YOUR LOGIN CREDENTIALS${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}EAS Station Web Interface:${NC}"
echo -e "    Username: ${BOLD}${GREEN}${ADMIN_USERNAME}${NC}"
echo -e "    Password: ${BOLD}(the password you entered)${NC}"
echo ""

echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${WHITE}  🔑 DATABASE CREDENTIALS (For IDE Tools)${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}${MAGENTA}PostgreSQL Connection Details:${NC}"
echo -e "    ${CYAN}Host:${NC}         ${BOLD}localhost${NC}"
echo -e "    ${CYAN}Port:${NC}         ${BOLD}5432${NC}"
echo -e "    ${CYAN}Database:${NC}     ${BOLD}alerts${NC}"
echo -e "    ${CYAN}Username:${NC}     ${BOLD}eas-station${NC}"
echo -e "    ${CYAN}Password:${NC}     ${BOLD}${DB_PASSWORD}${NC}"
echo ""
echo -e "  ${YELLOW}⚠️${NC}  ${BOLD}IMPORTANT - Save these credentials!${NC}"
echo -e "      These credentials are ${BOLD}only shown once during installation${NC}"
echo -e "      The password is ${BOLD}also saved${NC} in: ${BOLD}$CONFIG_FILE${NC}"
echo ""
echo -e "  ${GREEN}💡${NC} ${BOLD}Use these credentials in:${NC}"
echo -e "      • Database IDE tools (DataGrip, DBeaver, Postico, etc.)"
echo -e "      • psql command line: ${BOLD}psql -h localhost -U eas-station -d alerts${NC}"
echo ""
echo -e "  ${DIM}To view your password later, run:${NC}"
echo -e "    ${BOLD}sudo grep POSTGRES_PASSWORD $CONFIG_FILE${NC}"
echo ""

echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${WHITE}  ⚙️  YOUR CONFIGURATION${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}Timezone:${NC}        ${BOLD}$TIMEZONE${NC} (change in setup wizard)"
echo -e "  ${CYAN}Hostname:${NC}        ${BOLD}$SYSTEM_HOSTNAME${NC}"
echo -e "  ${CYAN}Domain:${NC}          ${BOLD}$DOMAIN_NAME${NC}"
echo -e "  ${CYAN}EAS Originator:${NC}  ${BOLD}$EAS_ORIGINATOR${NC}"
echo -e "  ${CYAN}Station ID:${NC}      ${BOLD}$EAS_STATION_ID${NC}"
echo -e "  ${CYAN}Config File:${NC}     ${BOLD}$CONFIG_FILE${NC}"
echo -e "  ${CYAN}Log Directory:${NC}   ${BOLD}$LOG_DIR${NC}"
echo ""
echo -e "  ${GREEN}✓${NC}  SECRET_KEY: ${BOLD}Auto-generated${NC} (64-character secure key)"
echo -e "  ${GREEN}✓${NC}  DB Password: ${BOLD}Auto-generated${NC} (43-character secure password)"
echo ""
echo -e "  ${YELLOW}⚠️${NC}  Technical settings configured automatically"
echo -e "      ${DIM}Database password shown above - save it for IDE access!${NC}"
echo ""

echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${WHITE}  📋 NEXT STEPS - IMPORTANT!${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}${YELLOW}1.${NC} ${BOLD}Log in${NC} to the web interface with your credentials above"
echo ""
echo -e "  ${BOLD}${YELLOW}2.${NC} ${BOLD}Configuration Summary:${NC}"
echo -e "      ${GREEN}✓${NC} Location configured: ${BOLD}$COUNTY_NAME, $STATE_CODE${NC}"
echo -e "      ${GREEN}✓${NC} Station callsign: ${BOLD}$EAS_STATION_ID${NC}"
echo -e "      ${GREEN}✓${NC} Alert sources: NOAA=${BOLD}$NOAA_ENABLED${NC}, IPAWS=${BOLD}$IPAWS_ENABLED${NC}"
echo -e "      ${GREEN}✓${NC} Icecast streaming: ${BOLD}$ICECAST_ENABLED${NC}"
echo -e "      ${GREEN}✓${NC} Hardware: GPIO=${BOLD}$GPIO_ENABLED${NC}, LED=${BOLD}$LED_SIGN_ENABLED${NC}, VFD=${BOLD}$VFD_DISPLAY_ENABLED${NC}, Zigbee=${BOLD}$ZIGBEE_ENABLED${NC}"
echo ""

if [ "$ARGON_ZIGBEE" = true ]; then
echo -e "  ${BOLD}${RED}⚠️  REBOOT REQUIRED FOR ZIGBEE${NC}"
echo -e "      The Argon ONE V5 USB hub was enabled in /boot/firmware/config.txt."
echo -e "      Reboot now for the Zigbee module to appear as /dev/ttyUSB0:"
echo -e "      ${BOLD}sudo reboot${NC}"
echo ""
fi

echo -e "  ${BOLD}${YELLOW}3.${NC} ${BOLD}Fine-tune settings${NC} in the web interface or use ${BOLD}sudo eas-config${NC}"
echo -e "      ${DIM}The eas-config tool provides a raspi-config style interface${NC}"
echo -e "      ${DIM}to reconfigure your EAS station after installation${NC}"
echo ""
echo -e "  ${YELLOW}⚠️${NC}  ${BOLD}Your station is ready to monitor alerts!${NC}"
echo ""

echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${WHITE}  🔌 COMPONENT ACCESS DETAILS${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}${MAGENTA}Main Web Interface (Primary Dashboard):${NC}"
echo -e "    URL:      ${BOLD}${GREEN}https://localhost${NC} or ${BOLD}${GREEN}https://${PRIMARY_IP}${NC}"
echo -e "    Username: ${BOLD}$ADMIN_USERNAME${NC}"
echo -e "    Password: ${BOLD}(your admin password)${NC}"
echo -e "    Purpose:  Configure alerts, view status, manage settings"
echo ""
echo -e "  ${BOLD}${MAGENTA}PostgreSQL Database (Command Line Access):${NC}"
echo -e "    Command:  ${BOLD}sudo -u postgres psql -d alerts${NC}"
echo -e "    Or:       ${BOLD}psql -h localhost -U eas_station -d alerts${NC}"
echo -e "              ${DIM}(Enter password when prompted: see credentials above)${NC}"
echo -e "    Purpose:  Direct SQL queries, database administration"
echo ""
echo -e "  ${BOLD}${MAGENTA}Redis Cache (Command Line):${NC}"
echo -e "    Command:  ${BOLD}redis-cli${NC}"
echo -e "    Purpose:  Monitor cache, debug real-time data"
echo ""
echo -e "  ${BOLD}${MAGENTA}System Logs:${NC}"
echo -e "    Web App:    ${BOLD}sudo journalctl -u eas-station-web.service -f${NC}"
echo -e "    EAS Service: ${BOLD}sudo journalctl -u eas-station-eas.service -f${NC}"
echo -e "    All Services: ${BOLD}sudo journalctl -u eas-station.target -f${NC}"
echo -e "    Purpose:    Troubleshooting, monitoring, debugging"
echo ""

echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${WHITE}  ✅ POST-INSTALLATION CHECKLIST${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}Immediately After Install:${NC}"
echo -e "    ${GREEN}☐${NC} Log in to web interface: ${BOLD}https://localhost${NC}"
echo -e "    ${GREEN}☐${NC} Accept self-signed certificate warning"
echo -e "    ${GREEN}☐${NC} Verify dashboard loads correctly"
echo ""
echo -e "  ${BOLD}Initial Configuration (via Setup Wizard):${NC}"
echo -e "    ${GREEN}☐${NC} Set your timezone and location (county, state)"
echo -e "    ${GREEN}☐${NC} Enter FIPS/zone codes for your area"
echo -e "    ${GREEN}☐${NC} Configure EAS originator code and station ID"
echo -e "    ${GREEN}☐${NC} Enable alert sources (NOAA Weather, IPAWS)"
echo -e "    ${GREEN}☐${NC} Test alert reception with test mode"
echo ""
echo -e "  ${BOLD}Optional Hardware Setup:${NC}"
echo -e "    ${GREEN}☐${NC} Connect SDR device (if using radio monitoring)"
echo -e "    ${GREEN}☐${NC} Configure LED displays or OLED screens"
echo -e "    ${GREEN}☐${NC} Set up GPIO pins (for Raspberry Pi)"
echo -e "    ${GREEN}☐${NC} Enable Icecast streaming (if broadcasting)"
echo ""
echo -e "  ${BOLD}Security & Production Readiness:${NC}"
echo -e "    ${GREEN}☐${NC} Replace self-signed cert with Let's Encrypt (see below)"
echo -e "    ${GREEN}✓${NC} Firewall configured automatically (ports 22, 80, 443 allowed)"
echo -e "    ${GREEN}☐${NC} Set up automatic backups (see backup commands below)"
echo -e "    ${GREEN}☐${NC} Configure email notifications (if desired)"
echo ""
echo -e "  ${BOLD}Testing & Verification:${NC}"
echo -e "    ${GREEN}☐${NC} Test with a sample CAP alert"
echo -e "    ${GREEN}☐${NC} Verify alert audio playback works"
echo -e "    ${GREEN}☐${NC} Check all services are running: ${BOLD}systemctl status eas-station.target${NC}"
echo -e "    ${GREEN}☐${NC} Monitor logs for errors: ${BOLD}journalctl -u eas-station.target -f${NC}"
echo ""

echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${WHITE}  🔧 USEFUL COMMANDS${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}Reconfigure EAS Station (raspi-config style):${NC}"
echo -e "    ${BOLD}${GREEN}sudo eas-config${NC}"
echo -e "    ${DIM}Interactive TUI for changing all settings${NC}"
echo ""
echo -e "  ${CYAN}View service status:${NC}"
echo -e "    ${BOLD}sudo systemctl status eas-station.target${NC}"
echo ""
echo -e "  ${CYAN}View web service logs:${NC}"
echo -e "    ${BOLD}sudo journalctl -u eas-station-web.service -f${NC}"
echo ""
echo -e "  ${CYAN}Restart all services:${NC}"
echo -e "    ${BOLD}sudo systemctl restart eas-station.target${NC}"
echo ""
echo -e "  ${CYAN}Stop all services:${NC}"
echo -e "    ${BOLD}sudo systemctl stop eas-station.target${NC}"
echo ""
echo -e "  ${CYAN}Edit configuration (advanced):${NC}"
echo -e "    ${BOLD}sudo nano $CONFIG_FILE${NC}"
echo -e "    ${DIM}(Restart services after changes)${NC}"
echo ""
echo -e "  ${CYAN}Database backup:${NC}"
echo -e "    ${BOLD}sudo -u postgres pg_dump alerts > /tmp/eas_backup_\$(date +%Y%m%d).sql${NC}"
echo ""
echo -e "  ${CYAN}Database restore:${NC}"
echo -e "    ${BOLD}sudo -u postgres psql alerts < /tmp/eas_backup_YYYYMMDD.sql${NC}"
echo ""
if [ "${SSL_CONFIGURED:-false}" != "true" ]; then
    echo -e "  ${CYAN}Set up production SSL certificate (Let's Encrypt):${NC}"
    echo -e "    ${BOLD}sudo certbot --nginx -d your-domain.com${NC}"
    echo -e "    ${DIM}(Replace 'your-domain.com' with your actual domain)${NC}"
    echo ""
fi
echo -e "  ${CYAN}View firewall status:${NC}"
echo -e "    ${BOLD}sudo ufw status verbose${NC}"
echo ""
echo -e "  ${CYAN}Firewall - Configured Ports:${NC}"
echo -e "    ${GREEN}✓${NC} 22/tcp (SSH), 80/tcp (HTTP), 443/tcp (HTTPS)"
if [ "${ICECAST_ENABLED:-true}" = "true" ]; then
    echo -e "    ${GREEN}✓${NC} 8000/tcp (Icecast streaming)"
fi
echo ""
echo -e "  ${CYAN}Firewall - Optional Ports:${NC}"
echo -e "    ${DIM}5432/tcp (PostgreSQL) - For remote database/IDE access${NC}"
echo -e "    ${DIM}Command: sudo ufw allow 5432/tcp${NC}"
echo -e "    ${DIM}⚠️  Use SSH tunneling for better security:${NC}"
echo -e "    ${DIM}   ssh -L 5432:localhost:5432 user@server${NC}"
echo ""

echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${WHITE}  📚 GETTING HELP${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}Documentation:${NC}"
echo -e "    Web: ${BOLD}https://localhost/help${NC} (after logging in)"
echo -e "    Local: ${BOLD}$INSTALL_DIR/docs/${NC}"
echo ""
echo -e "  ${CYAN}Troubleshooting:${NC}"
echo -e "    Check logs: ${BOLD}sudo journalctl -u eas-station.target -n 100${NC}"
echo -e "    Service status: ${BOLD}sudo systemctl status eas-station.target${NC}"
echo ""
echo -e "  ${CYAN}Community Support:${NC}"
echo -e "    GitHub: ${BOLD}https://github.com/KR8MER/eas-station${NC}"
echo -e "    Issues: ${BOLD}https://github.com/KR8MER/eas-station/issues${NC}"
echo ""
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BOLD}${GREEN}  Thank you for installing EAS Station!${NC}"
echo -e "${BOLD}${GREEN}  Your emergency alert monitoring system is ready to configure.${NC}"
echo ""
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
