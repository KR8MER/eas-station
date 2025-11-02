/**
 * EAS Station - Theme Management Module
 * Handles light/dark theme toggling and persistence
 */

(function() {
    'use strict';

    /**
     * Toggle between light and dark theme
     */
    function toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);

        // Update icon
        const icon = document.getElementById('theme-icon');
        if (icon) {
            icon.className = newTheme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
        }

        // Dispatch custom event for other modules to listen to
        window.dispatchEvent(new CustomEvent('theme-changed', {
            detail: { theme: newTheme }
        }));
    }

    /**
     * Load saved theme from localStorage
     */
    function loadTheme() {
        const savedTheme = localStorage.getItem('theme') || 'light';
        document.documentElement.setAttribute('data-theme', savedTheme);

        const icon = document.getElementById('theme-icon');
        if (icon) {
            icon.className = savedTheme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
        }

        return savedTheme;
    }

    /**
     * Get current theme
     */
    function getCurrentTheme() {
        return document.documentElement.getAttribute('data-theme') || 'light';
    }

    // Initialize theme on module load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadTheme);
    } else {
        loadTheme();
    }

    // Export functions to window
    window.toggleTheme = toggleTheme;
    window.loadTheme = loadTheme;
    window.getCurrentTheme = getCurrentTheme;
})();
