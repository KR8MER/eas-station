/**
 * Theme Management System
 * Handles light/dark theme switching and persistence
 */

class ThemeManager {
    constructor() {
        this.themes = {
            dark: 'dark',
            light: 'light',
            auto: 'auto'
        };

        this.currentTheme = 'dark'; // Default to dark theme
        this.init();
    }

    init() {
        // Load saved theme or detect system preference
        this.loadTheme();

        // Set up theme toggle button
        this.setupThemeToggle();

        // Listen for system theme changes
        this.watchSystemTheme();

        // Apply initial theme
        this.applyTheme(this.currentTheme);
    }

    loadTheme() {
        // Check for saved theme preference
        const savedTheme = localStorage.getItem('theme');

        if (savedTheme && Object.values(this.themes).includes(savedTheme)) {
            this.currentTheme = savedTheme;
        } else {
            // Detect system preference (default to dark)
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            this.currentTheme = prefersDark ? this.themes.dark : this.themes.light;
        }
    }

    saveTheme(theme) {
        localStorage.setItem('theme', theme);
        this.currentTheme = theme;
    }

    applyTheme(theme) {
        const html = document.documentElement;
        const body = document.body;

        // Remove existing theme classes
        html.classList.remove('theme-dark', 'theme-light');
        body.classList.remove('theme-dark', 'theme-light');

        // Apply new theme
        if (theme === this.themes.auto) {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const effectiveTheme = prefersDark ? this.themes.dark : this.themes.light;
            html.classList.add(`theme-${effectiveTheme}`);
            body.classList.add(`theme-${effectiveTheme}`);
        } else {
            html.classList.add(`theme-${theme}`);
            body.classList.add(`theme-${theme}`);
        }

        // Update theme toggle icon
        this.updateThemeIcon(theme);

        // Dispatch theme change event
        this.dispatchThemeChange(theme);
    }

    updateThemeIcon(theme) {
        const themeIcon = document.getElementById('theme-icon');
        if (themeIcon) {
            // Remove existing classes
            themeIcon.classList.remove('fa-sun', 'fa-moon', 'fa-adjust');

            // Add appropriate icon based on theme
            switch (theme) {
                case this.themes.light:
                    themeIcon.classList.add('fa-moon');
                    break;
                case this.themes.dark:
                    themeIcon.classList.add('fa-sun');
                    break;
                case this.themes.auto:
                    themeIcon.classList.add('fa-adjust');
                    break;
                default:
                    themeIcon.classList.add('fa-moon');
            }
        }
    }

    setupThemeToggle() {
        // Create theme toggle if it doesn't exist
        let themeToggle = document.querySelector('.theme-toggle');

        if (!themeToggle) {
            themeToggle = this.createThemeToggle();
            document.body.appendChild(themeToggle);
        }

        // Add click event listener
        themeToggle.addEventListener('click', () => this.toggleTheme());

        // Add keyboard support
        themeToggle.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.toggleTheme();
            }
        });
    }

    createThemeToggle() {
        const toggle = document.createElement('button');
        toggle.className = 'theme-toggle';
        toggle.setAttribute('aria-label', 'Toggle theme');
        toggle.setAttribute('title', 'Toggle Dark/Light Mode');
        toggle.innerHTML = '<i id="theme-icon" class="fas fa-moon"></i>';

        return toggle;
    }

    toggleTheme() {
        let nextTheme;

        switch (this.currentTheme) {
            case this.themes.dark:
                nextTheme = this.themes.light;
                break;
            case this.themes.light:
                nextTheme = this.themes.auto;
                break;
            case this.themes.auto:
                nextTheme = this.themes.dark;
                break;
            default:
                nextTheme = this.themes.dark;
        }

        this.setTheme(nextTheme);
        this.showThemeNotification(nextTheme);
    }

    setTheme(theme) {
        if (Object.values(this.themes).includes(theme)) {
            this.saveTheme(theme);
            this.applyTheme(theme);
        }
    }

    watchSystemTheme() {
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

        mediaQuery.addEventListener('change', (e) => {
            // Only apply system theme change if user has auto theme selected
            if (this.currentTheme === this.themes.auto) {
                this.applyTheme(this.themes.auto);
            }
        });
    }

    dispatchThemeChange(theme) {
        const event = new CustomEvent('themechange', {
            detail: { theme: theme }
        });
        document.dispatchEvent(event);
    }

    showThemeNotification(theme) {
        // Create a subtle notification
        const notification = document.createElement('div');
        notification.className = 'theme-notification';

        const themeNames = {
            [this.themes.dark]: 'Dark Mode',
            [this.themes.light]: 'Light Mode',
            [this.themes.auto]: 'Auto Mode'
        };

        notification.innerHTML = `
            <i class="fas fa-palette"></i>
            <span>${themeNames[theme]} Enabled</span>
        `;

        document.body.appendChild(notification);

        // Show notification
        setTimeout(() => notification.classList.add('show'), 100);

        // Hide and remove notification
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }, 2000);
    }

    // Public API methods
    getCurrentTheme() {
        return this.currentTheme;
    }

    isDarkMode() {
        if (this.currentTheme === this.themes.auto) {
            return window.matchMedia('(prefers-color-scheme: dark)').matches;
        }
        return this.currentTheme === this.themes.dark;
    }

    isLightMode() {
        return !this.isDarkMode();
    }
}

// Theme notification styles
const themeNotificationStyles = `
.theme-notification {
    position: fixed;
    top: 100px;
    right: 20px;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: var(--spacing-md);
    box-shadow: 0 4px 12px var(--shadow);
    z-index: 1001;
    display: flex;
    align-items: center;
    gap: var(--spacing-sm);
    transform: translateX(100%);
    opacity: 0;
    transition: all 0.3s ease;
    min-width: 150px;
}

.theme-notification.show {
    transform: translateX(0);
    opacity: 1;
}

.theme-notification i {
    color: var(--accent-primary);
}

.theme-toggle {
    position: fixed;
    top: 80px;
    right: 20px;
    z-index: 1000;
    border-radius: 50%;
    width: 50px;
    height: 50px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-tertiary);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
    box-shadow: 0 4px 12px var(--shadow);
    transition: all 0.3s ease;
    cursor: pointer;
}

.theme-toggle:hover {
    transform: scale(1.1) rotate(180deg);
    box-shadow: 0 6px 20px var(--shadow);
    background: var(--accent-primary);
    color: white;
}

.theme-toggle:focus {
    outline: 2px solid var(--accent-primary);
    outline-offset: 2px;
}

@media (max-width: 768px) {
    .theme-toggle {
        top: 70px;
        right: 15px;
        width: 40px;
        height: 40px;
    }
    
    .theme-notification {
        top: 120px;
        right: 15px;
        min-width: 120px;
        font-size: 0.9rem;
    }
}
`;

// Add styles to document
if (!document.querySelector('#theme-styles')) {
    const styleSheet = document.createElement('style');
    styleSheet.id = 'theme-styles';
    styleSheet.textContent = themeNotificationStyles;
    document.head.appendChild(styleSheet);
}

// Initialize theme manager
let themeManager;

// Wait for DOM to be ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        themeManager = new ThemeManager();
        window.themeManager = themeManager; // Make globally available
    });
} else {
    themeManager = new ThemeManager();
    window.themeManager = themeManager;
}

// Global functions for backward compatibility
function toggleTheme() {
    if (window.themeManager) {
        window.themeManager.toggleTheme();
    }
}

function setTheme(theme) {
    if (window.themeManager) {
        window.themeManager.setTheme(theme);
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ThemeManager;
}