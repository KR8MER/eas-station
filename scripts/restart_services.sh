#!/bin/bash
# Quick fix for database authentication issues
# Reloads systemd configuration and restarts all EAS Station services
# Copyright (c) 2025-2026 Timothy Kramer (KR8MER)
# Licensed under AGPL v3 or Commercial License

set -e

# Color output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo_info() {
    echo -e "${BLUE}ℹ️  ${NC}$1"
}

echo_success() {
    echo -e "${GREEN}✓  ${NC}$1"
}

echo_warning() {
    echo -e "${YELLOW}⚠️  ${NC}$1"
}

# Add branding footer for whiptail dialogs
whiptail_footer() {
    echo "EAS Station Service Manager | Copyright (c) 2025-2026 Timothy Kramer (KR8MER)"
}

# Display banner
clear
echo -e "${BOLD}${CYAN}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║              🔄  EAS STATION SERVICE MANAGER  🔄                      ║
║                                                                       ║
║              Service Control & Status Monitoring                      ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo_warning "This script should be run with sudo for full functionality"
    echo_info "Attempting to use sudo for privileged commands..."
    SUDO="sudo"
else
    SUDO=""
fi

# Check if whiptail is available
if command -v whiptail &> /dev/null; then
    USE_WHIPTAIL=true
else
    USE_WHIPTAIL=false
    echo_info "whiptail not available - using automatic mode"
    echo ""
fi
# Check if whiptail is available
if command -v whiptail &> /dev/null; then
    USE_WHIPTAIL=true
else
    USE_WHIPTAIL=false
    echo_info "whiptail not available - using automatic mode"
    echo ""
fi

# Service management functions

reload_daemon() {
    echo_info "Reloading systemd daemon configuration..."
    $SUDO systemctl daemon-reload
    echo_success "Systemd daemon reloaded"
    echo ""
}

stop_all_services() {
    echo_info "Stopping all EAS Station services..."
    $SUDO systemctl stop eas-station.target 2>/dev/null || echo_warning "Target not found or already stopped"
    echo_success "Services stopped"
    echo ""
}

start_all_services() {
    echo_info "Starting all EAS Station services..."
    $SUDO systemctl start eas-station.target
    echo_success "Services started"
    echo ""
}

restart_all_services() {
    reload_daemon
    stop_all_services
    start_all_services
    sleep 3
    check_service_status
}

check_config() {
    echo_info "Checking configuration..."
    if [ -f "/opt/eas-station/.env" ]; then
        if grep -q "^DATABASE_URL=" "/opt/eas-station/.env"; then
            echo_success "DATABASE_URL found in .env file"
        else
            echo_warning "DATABASE_URL not found in .env file - services may fail to start"
        fi
    else
        echo_warning ".env file not found at /opt/eas-station/.env - services will fail"
    fi
    echo ""
}

check_service_status() {
    echo_info "Checking service status..."
    echo ""
    
    SERVICES=(
        "eas-station-web"
        "eas-station-eas"
        "eas-station-audio"
        "eas-station-sdr"
        "eas-station-hardware"
        "eas-station-ipaws-poller"
        "eas-station-noaa-poller"
    )
    
    ALL_RUNNING=true
    for service in "${SERVICES[@]}"; do
        if $SUDO systemctl is-active --quiet "$service.service" 2>/dev/null; then
            echo_success "$service.service is running"
        else
            # Check if service exists
            if $SUDO systemctl list-unit-files | grep -q "$service.service"; then
                echo_warning "$service.service is NOT running"
                ALL_RUNNING=false
            fi
        fi
    done
    
    echo ""
    
    if [ "$ALL_RUNNING" = true ]; then
        echo_success "All services are running!"
    else
        echo_warning "Some services failed to start. Check logs with:"
        echo "  sudo journalctl -u eas-station.target -n 50 --no-pager"
    fi
    echo ""
}

check_db_errors() {
    echo_info "Checking for database authentication errors..."
    if $SUDO journalctl -u eas-station.target --since "1 minute ago" 2>/dev/null | grep -q "password authentication failed"; then
        echo_warning "Database authentication errors detected in logs"
        echo ""
        echo "  This may indicate an incorrect database user exists."
        echo "  Run the database fix script:"
        echo "    sudo /opt/eas-station/scripts/database/fix_database_user.sh"
        echo ""
    else
        echo_success "No database authentication errors detected"
    fi
    echo ""
}

restart_single_service() {
    local service=$1
    echo_info "Restarting $service.service..."
    $SUDO systemctl restart "$service.service"
    sleep 2
    if $SUDO systemctl is-active --quiet "$service.service"; then
        echo_success "$service.service restarted successfully"
    else
        echo_warning "$service.service failed to start"
        echo "Check logs: sudo journalctl -u $service.service -n 50"
    fi
    echo ""
}

show_logs() {
    local service=$1
    echo_info "Showing recent logs for $service.service..."
    echo ""
    $SUDO journalctl -u "$service.service" -n 50 --no-pager
    echo ""
}

# Main logic
if [ "$USE_WHIPTAIL" = true ]; then
    # Interactive menu
    while true; do
        CHOICE=$(whiptail --title "EAS Station Service Manager" --backtitle "$(whiptail_footer)" --menu "Select an action:\n\nUse arrow keys to navigate, Enter to select" 22 70 12 \
            "1" "Restart All Services (Full Restart)" \
            "2" "Start All Services" \
            "3" "Stop All Services" \
            "4" "Check Service Status" \
            "5" "Restart Web Service" \
            "6" "Restart EAS Service" \
            "7" "Restart Audio Service" \
            "8" "Restart SDR Service" \
            "9" "Restart Hardware Service" \
            "10" "View Service Logs" \
            "11" "Check Configuration" \
            "0" "Exit" \
            3>&1 1>&2 2>&3)
        
        EXIT_STATUS=$?
        if [ $EXIT_STATUS != 0 ]; then
            echo_info "Service manager cancelled"
            exit 0
        fi
        
        case $CHOICE in
            1)
                restart_all_services
                read -p "Press Enter to continue..."
                ;;
            2)
                start_all_services
                check_service_status
                read -p "Press Enter to continue..."
                ;;
            3)
                stop_all_services
                read -p "Press Enter to continue..."
                ;;
            4)
                check_service_status
                read -p "Press Enter to continue..."
                ;;
            5)
                restart_single_service "eas-station-web"
                read -p "Press Enter to continue..."
                ;;
            6)
                restart_single_service "eas-station-eas"
                read -p "Press Enter to continue..."
                ;;
            7)
                restart_single_service "eas-station-audio"
                read -p "Press Enter to continue..."
                ;;
            8)
                restart_single_service "eas-station-sdr"
                read -p "Press Enter to continue..."
                ;;
            9)
                restart_single_service "eas-station-hardware"
                read -p "Press Enter to continue..."
                ;;
            10)
                # Select which service logs to view
                SERVICE=$(whiptail --title "View Service Logs" --backtitle "$(whiptail_footer)" --menu "Select service:" 18 60 9 \
                    "1" "eas-station-web" \
                    "2" "eas-station-eas" \
                    "3" "eas-station-audio" \
                    "4" "eas-station-sdr" \
                    "5" "eas-station-hardware" \
                    "6" "eas-station-ipaws-poller" \
                    "7" "eas-station-noaa-poller" \
                    "8" "All (eas-station.target)" \
                    3>&1 1>&2 2>&3)
                
                case $SERVICE in
                    1) show_logs "eas-station-web" ;;
                    2) show_logs "eas-station-eas" ;;
                    3) show_logs "eas-station-audio" ;;
                    4) show_logs "eas-station-sdr" ;;
                    5) show_logs "eas-station-hardware" ;;
                    6) show_logs "eas-station-ipaws-poller" ;;
                    7) show_logs "eas-station-noaa-poller" ;;
                    8) show_logs "eas-station.target" ;;
                esac
                read -p "Press Enter to continue..."
                ;;
            11)
                check_config
                check_db_errors
                read -p "Press Enter to continue..."
                ;;
            0)
                echo_info "Exiting service manager"
                exit 0
                ;;
            *)
                whiptail --title "Error" --backtitle "$(whiptail_footer)" --msgbox "Invalid option" 8 40
                ;;
        esac
    done
else
    # Non-interactive mode - restart all services
    restart_all_services
    check_db_errors
    
    echo_info "Next steps:"
    echo "  • View logs: sudo journalctl -u eas-station.target -f"
    echo "  • Check status: sudo systemctl status eas-station.target"
    echo "  • Web interface: http://$(hostname -I | awk '{print $1}'):5000"
    echo ""
fi
