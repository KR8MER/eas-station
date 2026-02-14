#!/bin/bash
# EAS Station diagnostic script for database and service issues
# Copyright (c) 2025-2026 Timothy Kramer (KR8MER)
# Licensed under AGPL v3 or Commercial License

# Colors
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

echo_error() {
    echo -e "${RED}✗  [ERROR]${NC} $1"
}

# Add branding footer for whiptail dialogs
whiptail_footer() {
    echo "EAS Station Diagnostics | Copyright (c) 2025-2026 Timothy Kramer (KR8MER)"
}

# Display diagnostic banner
clear
echo -e "${BOLD}${CYAN}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║              🔍  EAS STATION DIAGNOSTICS  🔍                          ║
║                                                                       ║
║              System & Service Health Check Tool                       ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo_error "This script must be run as root (use sudo)"
    echo ""
    echo -e "${YELLOW}Please run:${NC} ${BOLD}sudo ./diagnose.sh${NC}"
    echo ""
    exit 1
fi

# Check if whiptail is available
if command -v whiptail &> /dev/null; then
    USE_WHIPTAIL=true
else
    USE_WHIPTAIL=false
    echo_info "whiptail not available - running all diagnostics automatically"
    echo ""
fi

# Diagnostic functions
# Diagnostic functions

check_services() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "1. Checking services status..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    systemctl status eas-station-web.service --no-pager -l | head -20
    echo ""
}

check_nginx() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "2. Checking nginx status..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    systemctl status nginx --no-pager -l | head -10
    echo ""
}

check_database() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "3. Checking database connection..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if sudo -u postgres psql -d alerts -c "SELECT version();" 2>/dev/null | grep PostgreSQL; then
        echo -e "${GREEN}✓ Database connection OK${NC}"
    else
        echo -e "${RED}✗ Database connection FAILED${NC}"
    fi
    echo ""
}

check_migrations() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "4. Checking if migration tables exist..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    TABLES=$(sudo -u postgres psql -d alerts -tAc "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('hardware_settings', 'icecast_settings');" 2>/dev/null)
    if echo "$TABLES" | grep -q "hardware_settings"; then
        echo -e "${GREEN}✓ hardware_settings table exists${NC}"
    else
        echo -e "${RED}✗ hardware_settings table MISSING${NC}"
    fi
    
    if echo "$TABLES" | grep -q "icecast_settings"; then
        echo -e "${GREEN}✓ icecast_settings table exists${NC}"
    else
        echo -e "${RED}✗ icecast_settings table MISSING${NC}"
    fi
    echo ""
}

check_logs() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "5. Checking recent web service logs..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    journalctl -u eas-station-web.service -n 50 --no-pager
    echo ""
}

check_env() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "6. Checking .env file..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [ -f /opt/eas-station/.env ]; then
        echo -e "${GREEN}✓ .env file exists${NC}"
        echo "Database URL: $(grep DATABASE_URL /opt/eas-station/.env | sed 's/:[^:]*@/:***@/')"
    else
        echo -e "${RED}✗ .env file MISSING${NC}"
    fi
    echo ""
}

check_app_import() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "7. Testing app import..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    cd /opt/eas-station
    sudo -u eas-station /opt/eas-station/venv/bin/python3 -c "
try:
    from app import app
    print('${GREEN}✓ App imports successfully${NC}')
except Exception as e:
    print('${RED}✗ App import failed: ' + str(e) + '${NC}')
    import traceback
    traceback.print_exc()
" 2>&1 | head -30
    echo ""
}

run_all_diagnostics() {
    check_services
    check_nginx
    check_database
    check_migrations
    check_logs
    check_env
    check_app_import
}

# Main logic
if [ "$USE_WHIPTAIL" = true ]; then
    # Interactive menu
    while true; do
        CHOICE=$(whiptail --title "EAS Station Diagnostics" --backtitle "$(whiptail_footer)" --menu "Select diagnostic test to run:\n\nUse arrow keys to navigate, Enter to select" 20 70 10 \
            "1" "Check EAS Station Services Status" \
            "2" "Check Nginx Status" \
            "3" "Check Database Connection" \
            "4" "Check Database Migrations" \
            "5" "Check Recent Service Logs" \
            "6" "Check .env Configuration File" \
            "7" "Test Application Import" \
            "8" "Run ALL Diagnostics" \
            "9" "Save Output to File" \
            "0" "Exit" \
            3>&1 1>&2 2>&3)
        
        EXIT_STATUS=$?
        if [ $EXIT_STATUS != 0 ]; then
            echo_info "Diagnostics cancelled"
            exit 0
        fi
        
        case $CHOICE in
            1)
                check_services
                read -p "Press Enter to continue..."
                ;;
            2)
                check_nginx
                read -p "Press Enter to continue..."
                ;;
            3)
                check_database
                read -p "Press Enter to continue..."
                ;;
            4)
                check_migrations
                read -p "Press Enter to continue..."
                ;;
            5)
                check_logs
                read -p "Press Enter to continue..."
                ;;
            6)
                check_env
                read -p "Press Enter to continue..."
                ;;
            7)
                check_app_import
                read -p "Press Enter to continue..."
                ;;
            8)
                run_all_diagnostics
                read -p "Press Enter to continue..."
                ;;
            9)
                OUTPUT_FILE="/tmp/eas-diagnostics-$(date +%Y%m%d-%H%M%S).txt"
                echo_info "Saving diagnostics to $OUTPUT_FILE..."
                run_all_diagnostics > "$OUTPUT_FILE" 2>&1
                echo_success "Diagnostics saved to: $OUTPUT_FILE"
                whiptail --title "Output Saved" --backtitle "$(whiptail_footer)" --msgbox "Diagnostics have been saved to:\n\n$OUTPUT_FILE\n\nYou can view this file with:\nsudo cat $OUTPUT_FILE" 12 70
                ;;
            0)
                echo_info "Exiting diagnostics"
                exit 0
                ;;
            *)
                whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Invalid option" 8 40
                ;;
        esac
    done
else
    # Non-interactive mode - run all diagnostics
    run_all_diagnostics
    
    echo "=========================================="
    echo "Diagnostic complete"
    echo "=========================================="
fi
