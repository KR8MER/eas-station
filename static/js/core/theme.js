/**
 * EAS Station - Theme Management Module
 * Handles theme switching and persistence with support for multiple themes
 */

(function() {
    'use strict';

    // Available themes
    const THEMES = {
        'cosmo': {
            name: 'Cosmo',
            mode: 'light',
            description: 'Default light theme with vibrant colors'
        },
        'dark': {
            name: 'Dark',
            mode: 'dark',
            description: 'Enhanced dark theme with improved readability'
        }
    };

    const DEFAULT_THEME = 'cosmo';

    /**
     * Toggle between light and dark theme modes
     */
    function toggleTheme() {
        const currentTheme = getCurrentTheme();
        const currentMode = THEMES[currentTheme]?.mode || 'light';
        
        // Find the next theme with opposite mode
        let newTheme = currentMode === 'dark' ? DEFAULT_THEME : 'dark';

        setTheme(newTheme);
    }

    /**
     * Set a specific theme
     */
    function setTheme(themeName) {
        if (!THEMES[themeName]) {
            console.warn(`Theme "${themeName}" not found, using default`);
            themeName = DEFAULT_THEME;
        }

        const theme = THEMES[themeName];
        document.documentElement.setAttribute('data-theme', themeName);
        document.documentElement.setAttribute('data-theme-mode', theme.mode);
        localStorage.setItem('theme', themeName);

        // Update icon
        const icon = document.getElementById('theme-icon');
        if (icon) {
            icon.className = theme.mode === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
        }

        // Dispatch custom event for other modules to listen to
        window.dispatchEvent(new CustomEvent('theme-changed', {
            detail: { 
                theme: themeName,
                mode: theme.mode,
                themeName: theme.name
            }
        }));
    }

    /**
     * Load saved theme from localStorage
     */
    function loadTheme() {
        const savedTheme = localStorage.getItem('theme') || DEFAULT_THEME;
        setTheme(savedTheme);
        return savedTheme;
    }

    /**
     * Get current theme
     */
    function getCurrentTheme() {
        return document.documentElement.getAttribute('data-theme') || DEFAULT_THEME;
    }

    /**
     * Get current theme mode (light or dark)
     */
    function getCurrentThemeMode() {
        const theme = getCurrentTheme();
        return THEMES[theme]?.mode || 'light';
    }

    /**
     * Get all available themes
     */
    function getAvailableThemes() {
        return THEMES;
    }

    // Initialize theme on module load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadTheme);
    } else {
        loadTheme();
    }

    // Export functions to window
    window.toggleTheme = toggleTheme;
    window.setTheme = setTheme;
    window.loadTheme = loadTheme;
    window.getCurrentTheme = getCurrentTheme;
    window.getCurrentThemeMode = getCurrentThemeMode;
    window.getAvailableThemes = getAvailableThemes;
})();
