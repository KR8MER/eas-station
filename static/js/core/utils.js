/**
 * EAS Station - Utility Functions Module
 * Common utility functions used throughout the application
 */

(function() {
    'use strict';

    /**
     * Update current time display in footer
     */
    function updateCurrentTime() {
        const now = new Date();
        const timeString = now.toLocaleString('en-US', {
            timeZone: 'America/New_York',
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            timeZoneName: 'short'
        });
        const timeElement = document.getElementById('current-time');
        if (timeElement) {
            timeElement.textContent = timeString;
        }
    }

    /**
     * Simple CSV export utility
     * @param {Array} data - Array of objects to export
     * @param {string} baseFilename - Base filename for the export
     */
    function exportToExcel(data, baseFilename = 'export') {
        if (!Array.isArray(data) || data.length === 0) {
            window.showToast && window.showToast('No data available to export.', 'warning');
            return;
        }

        const headers = Object.keys(data[0]);
        if (headers.length === 0) {
            window.showToast && window.showToast('Export failed: no columns detected.', 'error');
            return;
        }

        const escapeCell = (value) => {
            if (value === null || value === undefined) {
                return '""';
            }
            const stringValue = String(value).replace(/"/g, '""');
            return `"${stringValue}"`;
        };

        const csvRows = [headers.map(escapeCell).join(',')];

        data.forEach((row) => {
            const rowValues = headers.map((header) => escapeCell(row[header] ?? ''));
            csvRows.push(rowValues.join(','));
        });

        const csvContent = '\ufeff' + csvRows.join('\n');
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);

        const timestamp = new Date().toISOString().split('T')[0];
        const filename = `${baseFilename}_${timestamp}.csv`;

        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        URL.revokeObjectURL(url);
    }

    /**
     * Format date for display
     * @param {string|Date} date - Date to format
     * @param {boolean} includeTime - Whether to include time
     * @returns {string} Formatted date string
     */
    function formatDate(date, includeTime = true) {
        const d = date instanceof Date ? date : new Date(date);
        if (isNaN(d.getTime())) {
            return 'Invalid Date';
        }

        const options = {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
        };

        if (includeTime) {
            options.hour = '2-digit';
            options.minute = '2-digit';
            options.second = '2-digit';
        }

        return d.toLocaleString('en-US', options);
    }

    /**
     * Debounce function to limit how often a function is called
     * @param {Function} func - Function to debounce
     * @param {number} wait - Wait time in milliseconds
     * @returns {Function} Debounced function
     */
    function debounce(func, wait = 300) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    /**
     * Initialize utility functions
     */
    function init() {
        // Update time immediately and then every second
        updateCurrentTime();
        setInterval(updateCurrentTime, 1000);
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Export functions to window
    window.exportToExcel = exportToExcel;
    window.EASUtils = {
        updateCurrentTime: updateCurrentTime,
        exportToExcel: exportToExcel,
        formatDate: formatDate,
        debounce: debounce
    };
})();
