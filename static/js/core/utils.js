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
     * Generate PDF and open print dialog
     * @param {string} filename - Base filename for the PDF (without extension)
     * @param {HTMLElement|string} element - Element to print (defaults to document.body)
     */
    function printPageAsPDF(filename = 'document', element = null) {
        // Show loading toast
        if (window.showToast) {
            window.showToast('Generating PDF...', 'info');
        }

        // Determine element to print
        const printElement = element
            ? (typeof element === 'string' ? document.querySelector(element) : element)
            : document.body;

        if (!printElement) {
            window.showToast && window.showToast('Error: Could not find content to print', 'error');
            return;
        }

        // Create a clone to avoid modifying the original
        const clone = printElement.cloneNode(true);

        // Remove elements that shouldn't be printed
        const elementsToRemove = clone.querySelectorAll('.d-print-none, .no-print, .btn, .navbar, .footer, .toast-container, .modal, .pagination');
        elementsToRemove.forEach(el => el.remove());

        // Configure PDF options
        const opt = {
            margin: [10, 10, 10, 10],
            filename: `${filename}_${new Date().toISOString().split('T')[0]}.pdf`,
            image: { type: 'jpeg', quality: 0.98 },
            html2canvas: {
                scale: 2,
                useCORS: true,
                logging: false
            },
            jsPDF: {
                unit: 'mm',
                format: 'letter',
                orientation: 'portrait'
            }
        };

        // Generate PDF and open print dialog
        html2pdf()
            .set(opt)
            .from(clone)
            .toPdf()
            .get('pdf')
            .then(function(pdf) {
                // Open print dialog
                const pdfBlob = pdf.output('blob');
                const pdfUrl = URL.createObjectURL(pdfBlob);

                // Create a hidden iframe to load and print the PDF
                const iframe = document.createElement('iframe');
                iframe.style.position = 'fixed';
                iframe.style.right = '0';
                iframe.style.bottom = '0';
                iframe.style.width = '0';
                iframe.style.height = '0';
                iframe.style.border = 'none';

                iframe.onload = function() {
                    try {
                        iframe.contentWindow.print();
                        // Clean up after a delay
                        setTimeout(() => {
                            document.body.removeChild(iframe);
                            URL.revokeObjectURL(pdfUrl);
                        }, 1000);
                    } catch (e) {
                        console.error('Print error:', e);
                        // Fallback: download the PDF instead
                        const link = document.createElement('a');
                        link.href = pdfUrl;
                        link.download = opt.filename;
                        link.click();
                        URL.revokeObjectURL(pdfUrl);
                        document.body.removeChild(iframe);
                        if (window.showToast) {
                            window.showToast('PDF downloaded. Please open and print manually.', 'info');
                        }
                    }
                };

                document.body.appendChild(iframe);
                iframe.src = pdfUrl;
            })
            .catch(function(error) {
                console.error('PDF generation error:', error);
                if (window.showToast) {
                    window.showToast('Failed to generate PDF. Please try again.', 'error');
                }
            });
    }

    /**
     * Legacy wrapper for backwards compatibility
     * Use printPageAsPDF instead
     */
    function printPage() {
        printPageAsPDF('page');
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
     * Escape HTML special characters to prevent XSS
     * @param {string} text - Text to escape
     * @returns {string} Escaped text
     */
    function escapeHtml(text) {
        if (text === null || text === undefined) {
            return '';
        }
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    /**
     * Safely set HTML content by escaping user-provided text
     * @param {HTMLElement|string} element - Element or selector
     * @param {string} content - Content to set (will be escaped)
     */
    function setSafeText(element, content) {
        const el = typeof element === 'string' ? document.querySelector(element) : element;
        if (el) {
            el.textContent = content;
        }
    }

    /**
     * Safely append HTML by creating elements programmatically
     * @param {HTMLElement} parent - Parent element
     * @param {string} tag - HTML tag name
     * @param {Object} attributes - Attributes to set
     * @param {string} text - Text content (will be escaped)
     * @returns {HTMLElement} Created element
     */
    function createSafeElement(parent, tag, attributes = {}, text = '') {
        const el = document.createElement(tag);

        // Set attributes safely
        Object.keys(attributes).forEach(key => {
            if (key === 'className') {
                el.className = attributes[key];
            } else if (key.startsWith('data-')) {
                el.setAttribute(key, attributes[key]);
            } else {
                el[key] = attributes[key];
            }
        });

        // Set text content (automatically escaped)
        if (text) {
            el.textContent = text;
        }

        if (parent) {
            parent.appendChild(el);
        }

        return el;
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
    window.printPage = printPage;
    window.printPageAsPDF = printPageAsPDF;
    window.EASUtils = {
        updateCurrentTime: updateCurrentTime,
        exportToExcel: exportToExcel,
        printPage: printPage,
        printPageAsPDF: printPageAsPDF,
        formatDate: formatDate,
        debounce: debounce,
        escapeHtml: escapeHtml,
        setSafeText: setSafeText,
        createSafeElement: createSafeElement
    };
})();
