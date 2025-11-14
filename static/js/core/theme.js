/**
 * EAS Station - Theme Management Module
 * Handles theme switching and persistence with support for multiple themes
 * Includes import/export capabilities for custom themes
 */

(function() {
    'use strict';

    // Available themes
    const THEMES = {
        'cosmo': {
            name: 'Cosmo',
            mode: 'light',
            description: 'Default light theme with vibrant colors',
            builtin: true
        },
        'dark': {
            name: 'Dark',
            mode: 'dark',
            description: 'Enhanced dark theme with improved readability',
            builtin: true
        },
        'coffee': {
            name: 'Coffee',
            mode: 'dark',
            description: 'Warm coffee-inspired dark theme',
            builtin: true
        },
        'spring': {
            name: 'Spring',
            mode: 'light',
            description: 'Fresh spring-inspired light theme',
            builtin: true
        },
        'red': {
            name: 'Red',
            mode: 'light',
            description: 'Bold red accent theme',
            builtin: true
        },
        'green': {
            name: 'Green',
            mode: 'light',
            description: 'Nature-inspired green theme',
            builtin: true
        },
        'blue': {
            name: 'Blue',
            mode: 'light',
            description: 'Ocean blue theme',
            builtin: true
        },
        'purple': {
            name: 'Purple',
            mode: 'light',
            description: 'Royal purple theme',
            builtin: true
        },
        'pink': {
            name: 'Pink',
            mode: 'light',
            description: 'Soft pink theme',
            builtin: true
        },
        'orange': {
            name: 'Orange',
            mode: 'light',
            description: 'Energetic orange theme',
            builtin: true
        },
        'yellow': {
            name: 'Yellow',
            mode: 'light',
            description: 'Bright yellow theme',
            builtin: true
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

    /**
     * Export a theme as JSON
     */
    function exportTheme(themeName) {
        const theme = THEMES[themeName];
        if (!theme) {
            console.error(`Theme "${themeName}" not found`);
            return null;
        }

        const themeData = {
            name: themeName,
            displayName: theme.name,
            mode: theme.mode,
            description: theme.description,
            version: '1.0',
            exported: new Date().toISOString()
        };

        return JSON.stringify(themeData, null, 2);
    }

    /**
     * Export theme and download as file
     */
    function downloadTheme(themeName) {
        const themeJSON = exportTheme(themeName);
        if (!themeJSON) return;

        const blob = new Blob([themeJSON], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `theme-${themeName}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    /**
     * Import a theme from JSON
     */
    function importTheme(themeJSON) {
        try {
            const themeData = JSON.parse(themeJSON);
            
            // Validate theme structure
            if (!themeData.name || !themeData.mode) {
                throw new Error('Invalid theme structure');
            }

            // Add to themes registry (non-builtin)
            THEMES[themeData.name] = {
                name: themeData.displayName || themeData.name,
                mode: themeData.mode,
                description: themeData.description || 'Custom imported theme',
                builtin: false
            };

            // Save custom themes to localStorage
            saveCustomThemes();

            return themeData.name;
        } catch (error) {
            console.error('Failed to import theme:', error);
            return null;
        }
    }

    /**
     * Save custom themes to localStorage
     */
    function saveCustomThemes() {
        const customThemes = Object.entries(THEMES)
            .filter(([_, theme]) => !theme.builtin)
            .reduce((acc, [key, theme]) => {
                acc[key] = theme;
                return acc;
            }, {});
        
        localStorage.setItem('customThemes', JSON.stringify(customThemes));
    }

    /**
     * Load custom themes from localStorage
     */
    function loadCustomThemes() {
        try {
            const customThemes = localStorage.getItem('customThemes');
            if (customThemes) {
                const themes = JSON.parse(customThemes);
                Object.assign(THEMES, themes);
            }
        } catch (error) {
            console.error('Failed to load custom themes:', error);
        }
    }

    /**
     * Delete a custom theme
     */
    function deleteTheme(themeName) {
        if (THEMES[themeName]?.builtin) {
            console.error('Cannot delete built-in theme');
            return false;
        }

        delete THEMES[themeName];
        saveCustomThemes();
        
        // If deleted theme is active, switch to default
        if (getCurrentTheme() === themeName) {
            setTheme(DEFAULT_THEME);
        }
        
        return true;
    }

    /**
     * Show theme selector modal
     */
    function showThemeSelector() {
        // Create modal if it doesn't exist
        let modal = document.getElementById('theme-selector-modal');
        if (!modal) {
            modal = createThemeSelector();
        }

        // Update theme list
        updateThemeList();

        // Show modal (Bootstrap 5)
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    /**
     * Create theme selector modal
     */
    function createThemeSelector() {
        const modalHTML = `
            <div class="modal fade" id="theme-selector-modal" tabindex="-1" aria-labelledby="themeSelectorLabel" aria-hidden="true">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="themeSelectorLabel">
                                <i class="fas fa-palette me-2"></i>Theme Selector
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <div class="mb-3">
                                <label class="form-label">Current Theme: <strong id="current-theme-display"></strong></label>
                            </div>
                            <div class="row g-3" id="theme-list">
                                <!-- Theme cards will be inserted here -->
                            </div>
                            <hr class="my-4">
                            <div class="row">
                                <div class="col-md-6">
                                    <h6><i class="fas fa-download me-2"></i>Export Current Theme</h6>
                                    <button class="btn btn-primary btn-sm" onclick="window.downloadTheme(window.getCurrentTheme())">
                                        <i class="fas fa-file-download me-1"></i>Download Theme
                                    </button>
                                </div>
                                <div class="col-md-6">
                                    <h6><i class="fas fa-upload me-2"></i>Import Theme</h6>
                                    <input type="file" class="form-control form-control-sm" id="theme-import-input" accept=".json">
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const div = document.createElement('div');
        div.innerHTML = modalHTML;
        document.body.appendChild(div.firstElementChild);

        // Add import handler
        document.getElementById('theme-import-input').addEventListener('change', handleThemeImport);

        return document.getElementById('theme-selector-modal');
    }

    /**
     * Update theme list in selector
     */
    function updateThemeList() {
        const themeList = document.getElementById('theme-list');
        const currentTheme = getCurrentTheme();
        
        document.getElementById('current-theme-display').textContent = THEMES[currentTheme]?.name || currentTheme;

        themeList.innerHTML = Object.entries(THEMES).map(([key, theme]) => `
            <div class="col-md-4">
                <div class="card theme-card ${key === currentTheme ? 'border-primary' : ''}" style="cursor: pointer;" onclick="window.setTheme('${key}'); window.updateThemeList();">
                    <div class="card-body">
                        <h6 class="card-title">
                            ${theme.name}
                            ${key === currentTheme ? '<i class="fas fa-check text-primary float-end"></i>' : ''}
                            ${!theme.builtin ? '<i class="fas fa-user text-muted float-end me-2"></i>' : ''}
                        </h6>
                        <p class="card-text small text-muted">${theme.description}</p>
                        <span class="badge bg-${theme.mode === 'dark' ? 'dark' : 'light'} text-${theme.mode === 'dark' ? 'light' : 'dark'}">${theme.mode}</span>
                        ${!theme.builtin ? `<button class="btn btn-sm btn-danger float-end" onclick="event.stopPropagation(); window.deleteTheme('${key}'); window.updateThemeList();"><i class="fas fa-trash"></i></button>` : ''}
                    </div>
                </div>
            </div>
        `).join('');
    }

    /**
     * Handle theme import from file
     */
    function handleThemeImport(event) {
        const file = event.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = function(e) {
            const themeName = importTheme(e.target.result);
            if (themeName) {
                updateThemeList();
                alert(`Theme "${themeName}" imported successfully!`);
                event.target.value = ''; // Reset file input
            } else {
                alert('Failed to import theme. Please check the file format.');
            }
        };
        reader.readAsText(file);
    }

    // Load custom themes on startup
    loadCustomThemes();

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
    window.exportTheme = exportTheme;
    window.downloadTheme = downloadTheme;
    window.importTheme = importTheme;
    window.deleteTheme = deleteTheme;
    window.showThemeSelector = showThemeSelector;
    window.updateThemeList = updateThemeList;
})();
