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
        },
        'aurora': {
            name: 'Aurora',
            mode: 'dark',
            description: 'Polar lights theme with teal and violet glows',
            builtin: true
        },
        'nebula': {
            name: 'Nebula',
            mode: 'dark',
            description: 'Deep space magenta and cyan dark theme',
            builtin: true
        },
        'sunset': {
            name: 'Sunset',
            mode: 'light',
            description: 'Golden hour gradient with warm oranges',
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
                
                // Apply CSS for custom themes with color definitions
                Object.entries(themes).forEach(([themeName, theme]) => {
                    if (theme.colors) {
                        applyThemeCSS({ colors: theme.colors }, themeName);
                    }
                });
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
                            <div class="row g-3">
                                <div class="col-md-4">
                                    <h6><i class="fas fa-plus-circle me-2"></i>Create New Theme</h6>
                                    <button class="btn btn-success btn-sm w-100" onclick="window.showThemeCreator()">
                                        <i class="fas fa-magic me-1"></i>Theme Creator
                                    </button>
                                </div>
                                <div class="col-md-4">
                                    <h6><i class="fas fa-download me-2"></i>Export Current Theme</h6>
                                    <button class="btn btn-primary btn-sm w-100" onclick="window.downloadTheme(window.getCurrentTheme())">
                                        <i class="fas fa-file-download me-1"></i>Download Theme
                                    </button>
                                </div>
                                <div class="col-md-4">
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

    /**
     * Show theme creator modal
     */
    function showThemeCreator() {
        // Create modal if it doesn't exist
        let modal = document.getElementById('theme-creator-modal');
        if (!modal) {
            modal = createThemeCreator();
        }

        // Initialize with current theme or defaults
        initializeThemeCreator();

        // Show modal (Bootstrap 5)
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    /**
     * Create theme creator modal
     */
    function createThemeCreator() {
        const modalHTML = `
            <div class="modal fade" id="theme-creator-modal" tabindex="-1" aria-labelledby="themeCreatorLabel" aria-hidden="true">
                <div class="modal-dialog modal-xl">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="themeCreatorLabel">
                                <i class="fas fa-magic me-2"></i>Theme Creator
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body" style="max-height: 70vh; overflow-y: auto;">
                            <div class="row mb-3">
                                <div class="col-md-6">
                                    <label for="theme-name-input" class="form-label">Theme Name</label>
                                    <input type="text" class="form-control" id="theme-name-input" placeholder="My Custom Theme">
                                </div>
                                <div class="col-md-6">
                                    <label for="theme-mode-input" class="form-label">Theme Mode</label>
                                    <select class="form-select" id="theme-mode-input">
                                        <option value="light">Light</option>
                                        <option value="dark">Dark</option>
                                    </select>
                                </div>
                            </div>
                            <div class="mb-3">
                                <label for="theme-description-input" class="form-label">Description</label>
                                <input type="text" class="form-control" id="theme-description-input" placeholder="A custom theme">
                            </div>
                            <hr>
                            <h6><i class="fas fa-palette me-2"></i>Primary Colors</h6>
                            <div class="row g-3 mb-3">
                                <div class="col-md-3">
                                    <label class="form-label small">Primary Color</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-primary" value="#204885">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label small">Secondary Color</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-secondary" value="#872a96">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label small">Accent Color</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-accent" value="#4f6fb3">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label small">Background Color</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-bg" value="#e8ecf7">
                                </div>
                            </div>
                            <h6><i class="fas fa-check-circle me-2"></i>Status Colors</h6>
                            <div class="row g-3 mb-3">
                                <div class="col-md-3">
                                    <label class="form-label small">Success Color</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-success" value="#2eb08d">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label small">Warning Color</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-warning" value="#f6b968">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label small">Danger Color</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-danger" value="#e05263">
                                </div>
                                <div class="col-md-3">
                                    <label class="form-label small">Info Color</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-info" value="#2f5aa1">
                                </div>
                            </div>
                            <h6><i class="fas fa-font me-2"></i>Text Colors</h6>
                            <div class="row g-3 mb-3">
                                <div class="col-md-4">
                                    <label class="form-label small">Text Color</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-text" value="#1c2233">
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label small">Text Secondary</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-text-secondary" value="#5a6c8f">
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label small">Text Muted</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-text-muted" value="#8892a6">
                                </div>
                            </div>
                            <h6><i class="fas fa-layer-group me-2"></i>UI Elements</h6>
                            <div class="row g-3 mb-3">
                                <div class="col-md-4">
                                    <label class="form-label small">Surface Color</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-surface" value="#ffffff">
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label small">Border Color</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-border" value="#ced7ea">
                                </div>
                                <div class="col-md-4">
                                    <label class="form-label small">Card Background</label>
                                    <input type="color" class="form-control form-control-color w-100" id="color-card" value="#ffffff">
                                </div>
                            </div>
                            <div class="alert alert-info">
                                <i class="fas fa-lightbulb me-2"></i>
                                <strong>Preview:</strong> The theme will be temporarily applied when you click "Preview Theme" below.
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" onclick="window.previewCreatedTheme()">
                                <i class="fas fa-eye me-1"></i>Preview Theme
                            </button>
                            <button type="button" class="btn btn-primary" onclick="window.saveCreatedTheme()">
                                <i class="fas fa-save me-1"></i>Save Theme
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const div = document.createElement('div');
        div.innerHTML = modalHTML;
        document.body.appendChild(div.firstElementChild);

        return document.getElementById('theme-creator-modal');
    }

    /**
     * Initialize theme creator with current theme or defaults
     */
    function initializeThemeCreator() {
        const currentTheme = getCurrentTheme();
        document.getElementById('theme-name-input').value = `Custom ${currentTheme}`;
        document.getElementById('theme-mode-input').value = THEMES[currentTheme]?.mode || 'light';
        document.getElementById('theme-description-input').value = 'A custom theme';
        
        // Set default colors based on current theme
        const root = document.documentElement;
        const style = getComputedStyle(root);
        
        // Helper to get CSS variable value
        const getCSSVar = (name) => style.getPropertyValue(name).trim();
        
        document.getElementById('color-primary').value = getCSSVar('--primary-color') || '#204885';
        document.getElementById('color-secondary').value = getCSSVar('--secondary-color') || '#872a96';
        document.getElementById('color-accent').value = getCSSVar('--accent-color') || '#4f6fb3';
        document.getElementById('color-bg').value = getCSSVar('--bg-color') || '#e8ecf7';
        document.getElementById('color-success').value = getCSSVar('--success-color') || '#2eb08d';
        document.getElementById('color-warning').value = getCSSVar('--warning-color') || '#f6b968';
        document.getElementById('color-danger').value = getCSSVar('--danger-color') || '#e05263';
        document.getElementById('color-info').value = getCSSVar('--info-color') || '#2f5aa1';
        document.getElementById('color-text').value = getCSSVar('--text-color') || '#1c2233';
        document.getElementById('color-text-secondary').value = getCSSVar('--text-secondary') || '#5a6c8f';
        document.getElementById('color-text-muted').value = getCSSVar('--text-muted') || '#8892a6';
        document.getElementById('color-surface').value = getCSSVar('--surface-color') || '#ffffff';
        document.getElementById('color-border').value = getCSSVar('--border-color') || '#ced7ea';
        document.getElementById('color-card').value = getCSSVar('--bg-card') || '#ffffff';
    }

    /**
     * Preview the created theme temporarily
     */
    function previewCreatedTheme() {
        const themeData = collectThemeData();
        applyThemeCSS(themeData);
    }

    /**
     * Save the created theme
     */
    function saveCreatedTheme() {
        const themeData = collectThemeData();
        const themeName = themeData.name.toLowerCase().replace(/\s+/g, '-');
        
        if (!themeName) {
            alert('Please enter a theme name');
            return;
        }

        if (THEMES[themeName]?.builtin) {
            alert('This theme name is reserved. Please choose a different name.');
            return;
        }

        // Add theme to registry
        THEMES[themeName] = {
            name: themeData.displayName,
            mode: themeData.mode,
            description: themeData.description,
            builtin: false,
            colors: themeData.colors
        };

        // Apply the theme CSS
        applyThemeCSS(themeData, themeName);

        // Save custom themes
        saveCustomThemes();

        // Set as active theme
        setTheme(themeName);

        // Close creator modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('theme-creator-modal'));
        if (modal) modal.hide();

        // Show selector with new theme
        setTimeout(() => {
            showThemeSelector();
        }, 500);
    }

    /**
     * Collect theme data from form
     */
    function collectThemeData() {
        return {
            name: document.getElementById('theme-name-input').value.toLowerCase().replace(/\s+/g, '-'),
            displayName: document.getElementById('theme-name-input').value,
            mode: document.getElementById('theme-mode-input').value,
            description: document.getElementById('theme-description-input').value,
            colors: {
                primary: document.getElementById('color-primary').value,
                secondary: document.getElementById('color-secondary').value,
                accent: document.getElementById('color-accent').value,
                bg: document.getElementById('color-bg').value,
                success: document.getElementById('color-success').value,
                warning: document.getElementById('color-warning').value,
                danger: document.getElementById('color-danger').value,
                info: document.getElementById('color-info').value,
                text: document.getElementById('color-text').value,
                textSecondary: document.getElementById('color-text-secondary').value,
                textMuted: document.getElementById('color-text-muted').value,
                surface: document.getElementById('color-surface').value,
                border: document.getElementById('color-border').value,
                card: document.getElementById('color-card').value
            }
        };
    }

    /**
     * Apply theme CSS variables dynamically
     */
    function applyThemeCSS(themeData, themeName = 'preview') {
        // Create or update style element for custom theme
        let styleEl = document.getElementById('custom-theme-style');
        if (!styleEl) {
            styleEl = document.createElement('style');
            styleEl.id = 'custom-theme-style';
            document.head.appendChild(styleEl);
        }

        const colors = themeData.colors;
        const css = `
            [data-theme="${themeName}"] {
                --primary-color: ${colors.primary};
                --primary-soft: ${colors.primary};
                --secondary-color: ${colors.secondary};
                --secondary-soft: ${colors.secondary};
                --accent-color: ${colors.accent};
                --success-color: ${colors.success};
                --danger-color: ${colors.danger};
                --warning-color: ${colors.warning};
                --info-color: ${colors.info};
                --critical-color: ${colors.danger};
                --light-color: ${colors.surface};
                --dark-color: ${colors.text};
                --bg-color: ${colors.bg};
                --surface-color: ${colors.surface};
                --bg-card: ${colors.card};
                --bg-primary: ${colors.text};
                --text-color: ${colors.text};
                --text-secondary: ${colors.textSecondary};
                --text-muted: ${colors.textMuted};
                --border-color: ${colors.border};
                --shadow-color: rgba(0, 0, 0, 0.12);
                --shadow: rgba(0, 0, 0, 0.12);
                --accent-primary: ${colors.accent};
                --accent-secondary: ${colors.secondary};
                --info: ${colors.info};
                --success: ${colors.success};
                --warning: ${colors.warning};
                --danger: ${colors.danger};
            }
        `;

        styleEl.textContent = css;
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
    window.showThemeCreator = showThemeCreator;
    window.previewCreatedTheme = previewCreatedTheme;
    window.saveCreatedTheme = saveCreatedTheme;
})();
