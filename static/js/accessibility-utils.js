/**
 * Accessibility Utilities
 * Provides WCAG 2.1 AA compliance features and enhancements
 */

class AccessibilityUtils {
    constructor() {
        this.focusableElements = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
        this.lastFocusedElement = null;
        this.keyboardUser = false;
        this.init();
    }

    init() {
        // Add CSS if not already included
        this.ensureStylesheet();
        // Setup keyboard detection
        this.setupKeyboardDetection();
        // Setup focus management
        this.setupFocusManagement();
        // Setup ARIA live regions
        this.setupLiveRegions();
        // Setup enhanced form validation
        this.setupFormAccessibility();
        // Setup screen reader announcements
        this.setupScreenReaderAnnouncements();
    }

    ensureStylesheet() {
        if (!document.querySelector('link[href*="accessibility.css"]')) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = '/static/css/accessibility.css';
            document.head.appendChild(link);
        }
    }

    // Keyboard Detection
    setupKeyboardDetection() {
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Tab') {
                this.keyboardUser = true;
                document.body.classList.add('keyboard-user');
            }
        });

        document.addEventListener('mousedown', () => {
            this.keyboardUser = false;
            document.body.classList.remove('keyboard-user');
        });
    }

    // Focus Management
    setupFocusManagement() {
        // Track last focused element before modal opens
        document.addEventListener('focusin', (e) => {
            this.lastFocusedElement = e.target;
        });

        // Setup focus trapping for modals
        document.addEventListener('shown.bs.modal', (e) => {
            this.trapFocus(e.target);
        });

        document.addEventListener('hidden.bs.modal', (e) => {
            this.removeFocusTrap(e.target);
            if (this.lastFocusedElement) {
                this.lastFocusedElement.focus();
            }
        });
    }

    trapFocus(container) {
        const focusableElements = container.querySelectorAll(this.focusableElements);
        const firstFocusable = focusableElements[0];
        const lastFocusable = focusableElements[focusableElements.length - 1];

        container.addEventListener('keydown', (e) => {
            if (e.key === 'Tab') {
                if (e.shiftKey) {
                    if (document.activeElement === firstFocusable) {
                        lastFocusable.focus();
                        e.preventDefault();
                    }
                } else {
                    if (document.activeElement === lastFocusable) {
                        firstFocusable.focus();
                        e.preventDefault();
                    }
                }
            }
        });

        // Focus first element
        if (firstFocusable) {
            firstFocusable.focus();
        }
    }

    removeFocusTrap(container) {
        // Remove event listeners (simplified - in production, use proper cleanup)
        container.focusTrapActive = false;
    }

    // ARIA Live Regions
    setupLiveRegions() {
        // Create live regions if they don't exist
        if (!document.getElementById('aria-live-polite')) {
            const politeRegion = document.createElement('div');
            politeRegion.id = 'aria-live-polite';
            politeRegion.className = 'aria-live-polite';
            politeRegion.setAttribute('aria-live', 'polite');
            politeRegion.setAttribute('aria-atomic', 'true');
            document.body.appendChild(politeRegion);
        }

        if (!document.getElementById('aria-live-assertive')) {
            const assertiveRegion = document.createElement('div');
            assertiveRegion.id = 'aria-live-assertive';
            assertiveRegion.className = 'aria-live-assertive';
            assertiveRegion.setAttribute('aria-live', 'assertive');
            assertiveRegion.setAttribute('aria-atomic', 'true');
            document.body.appendChild(assertiveRegion);
        }
    }

    // Screen Reader Announcements
    setupScreenReaderAnnouncements() {
        // Create status announcement element
        if (!document.getElementById('status-announcement')) {
            const statusDiv = document.createElement('div');
            statusDiv.id = 'status-announcement';
            statusDiv.className = 'status-announcement';
            statusDiv.setAttribute('aria-live', 'polite');
            statusDiv.setAttribute('aria-atomic', 'true');
            document.body.appendChild(statusDiv);
        }
    }

    // Public Methods
    announce(message, priority = 'polite') {
        const region = document.getElementById(`aria-live-${priority}`);
        if (region) {
            region.textContent = message;
            // Clear after announcement
            setTimeout(() => {
                region.textContent = '';
            }, 1000);
        }
    }

    announceStatus(message) {
        const statusDiv = document.getElementById('status-announcement');
        if (statusDiv) {
            statusDiv.textContent = message;
            setTimeout(() => {
                statusDiv.textContent = '';
            }, 3000);
        }
    }

    // Form Accessibility
    setupFormAccessibility() {
        // Enhance all forms with accessibility features
        document.querySelectorAll('form').forEach(form => {
            this.enhanceFormAccessibility(form);
        });

        // Watch for dynamically added forms
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        if (node.tagName === 'FORM') {
                            this.enhanceFormAccessibility(node);
                        } else if (node.querySelector) {
                            node.querySelectorAll('form').forEach(form => {
                                this.enhanceFormAccessibility(form);
                            });
                        }
                    }
                });
            });
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }

    enhanceFormAccessibility(form) {
        // Add proper labels to all inputs
        form.querySelectorAll('input, select, textarea').forEach(field => {
            this.enhanceFieldAccessibility(field);
        });

        // Add form submission feedback
        form.addEventListener('submit', (e) => {
            this.announce('Form submitted');
        });

        // Add error handling
        form.addEventListener('invalid', (e) => {
            e.preventDefault();
            this.handleFormError(form, e.target);
        });
    }

    enhanceFieldAccessibility(field) {
        // Ensure field has a label
        if (!field.hasAttribute('aria-label') && !field.hasAttribute('aria-labelledby')) {
            let label = field.closest('label');
            if (!label) {
                const id = field.id || `field-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
                field.id = id;
                
                // Look for label with for attribute
                label = document.querySelector(`label[for="${id}"]`);
            }

            if (label) {
                const labelId = label.id || `label-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
                label.id = labelId;
                field.setAttribute('aria-labelledby', labelId);
            }
        }

        // Add required field indicators
        if (field.hasAttribute('required')) {
            const label = document.querySelector(`label[for="${field.id}"]`) || 
                         document.querySelector(`#${field.getAttribute('aria-labelledby')}`);
            if (label && !label.querySelector('.required-indicator')) {
                const indicator = document.createElement('span');
                indicator.className = 'required-indicator';
                indicator.setAttribute('aria-hidden', 'true');
                indicator.textContent = ' *';
                label.appendChild(indicator);
            }

            field.setAttribute('aria-required', 'true');
        }

        // Add validation states
        field.addEventListener('invalid', () => {
            field.setAttribute('aria-invalid', 'true');
            this.describeFieldError(field);
        });

        field.addEventListener('input', () => {
            if (field.validity.valid) {
                field.setAttribute('aria-invalid', 'false');
                this.clearFieldError(field);
            }
        });
    }

    describeFieldError(field) {
        const errorId = `${field.id}-error`;
        let errorElement = document.getElementById(errorId);

        if (!errorElement) {
            errorElement = document.createElement('div');
            errorElement.id = errorId;
            errorElement.className = 'error-message';
            errorElement.setAttribute('role', 'alert');
            errorElement.setAttribute('aria-live', 'polite');

            field.parentNode.appendChild(errorElement);
        }

        errorElement.textContent = field.validationMessage;
        field.setAttribute('aria-describedby', errorId);

        // Focus the field for correction
        field.focus();
        this.announce(`Error in ${field.name || field.id}: ${field.validationMessage}`);
    }

    clearFieldError(field) {
        const errorId = `${field.id}-error`;
        const errorElement = document.getElementById(errorId);

        if (errorElement) {
            errorElement.remove();
        }

        field.removeAttribute('aria-describedby');
    }

    handleFormError(form, invalidField) {
        const firstInvalidField = form.querySelector(':invalid');
        if (firstInvalidField) {
            firstInvalidField.focus();
            this.announce('Please correct the errors in the form');
        }
    }

    // Navigation Accessibility
    enhanceNavigation(nav) {
        // Add ARIA labels and roles
        if (!nav.hasAttribute('role')) {
            nav.setAttribute('role', 'navigation');
        }

        if (!nav.hasAttribute('aria-label') && !nav.hasAttribute('aria-labelledby')) {
            nav.setAttribute('aria-label', 'Main navigation');
        }

        // Enhance navigation links
        nav.querySelectorAll('a').forEach(link => {
            if (!link.hasAttribute('aria-label') && link.textContent.trim()) {
                link.setAttribute('aria-label', link.textContent.trim());
            }

            // Add current page indicator
            if (link.href === window.location.href) {
                link.setAttribute('aria-current', 'page');
            }
        });

        // Setup keyboard navigation
        this.setupNavigationKeyboard(nav);
    }

    setupNavigationKeyboard(nav) {
        const links = nav.querySelectorAll('a');
        let currentIndex = -1;

        nav.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
                e.preventDefault();
                currentIndex = (currentIndex + 1) % links.length;
                links[currentIndex].focus();
            } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
                e.preventDefault();
                currentIndex = currentIndex <= 0 ? links.length - 1 : currentIndex - 1;
                links[currentIndex].focus();
            }
        });
    }

    // Table Accessibility
    enhanceTable(table) {
        // Add caption if missing
        if (!table.querySelector('caption')) {
            const caption = document.createElement('caption');
            caption.textContent = 'Data table';
            table.appendChild(caption);
        }

        // Add scope to headers
        table.querySelectorAll('th').forEach(header => {
            if (!header.hasAttribute('scope')) {
                header.setAttribute('scope', 'col');
            }
        });

        // Add ARIA labels for sortable columns
        table.querySelectorAll('th[onclick]').forEach(header => {
            if (!header.hasAttribute('aria-sort')) {
                header.setAttribute('aria-sort', 'none');
                header.setAttribute('role', 'columnheader');
                header.setAttribute('tabindex', '0');
            }
        });
    }

    // Modal Accessibility
    enhanceModal(modal) {
        // Add proper roles and labels
        if (!modal.hasAttribute('role')) {
            modal.setAttribute('role', 'dialog');
        }

        const modalTitle = modal.querySelector('.modal-title');
        if (modalTitle && !modal.hasAttribute('aria-labelledby')) {
            const titleId = modalTitle.id || `modal-title-${Date.now()}`;
            modalTitle.id = titleId;
            modal.setAttribute('aria-labelledby', titleId);
        }

        if (!modal.hasAttribute('aria-modal')) {
            modal.setAttribute('aria-modal', 'true');
        }

        // Close on Escape key
        modal.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const closeButton = modal.querySelector('.btn-close, [data-bs-dismiss="modal"]');
                if (closeButton) {
                    closeButton.click();
                }
            }
        });
    }

    // Progress Bar Accessibility
    updateProgressBar(progressBar, value, max = 100) {
        progressBar.setAttribute('aria-valuenow', value);
        progressBar.setAttribute('aria-valuemin', '0');
        progressBar.setAttribute('aria-valuemax', max);
        progressBar.style.width = `${(value / max) * 100}%`;

        const percentageText = Math.round((value / max) * 100);
        this.announce(`Progress: ${percentageText}%`);
    }

    // Tab Accessibility
    enhanceTabInterface(tabContainer) {
        const tabList = tabContainer.querySelector('[role="tablist"]');
        const tabs = tabContainer.querySelectorAll('[role="tab"]');
        const panels = tabContainer.querySelectorAll('[role="tabpanel"]');

        // Setup keyboard navigation
        tabs.forEach((tab, index) => {
            tab.addEventListener('keydown', (e) => {
                let targetIndex;

                switch (e.key) {
                    case 'ArrowLeft':
                    case 'ArrowUp':
                        e.preventDefault();
                        targetIndex = index === 0 ? tabs.length - 1 : index - 1;
                        tabs[targetIndex].focus();
                        tabs[targetIndex].click();
                        break;
                    case 'ArrowRight':
                    case 'ArrowDown':
                        e.preventDefault();
                        targetIndex = index === tabs.length - 1 ? 0 : index + 1;
                        tabs[targetIndex].focus();
                        tabs[targetIndex].click();
                        break;
                    case 'Home':
                        e.preventDefault();
                        tabs[0].focus();
                        tabs[0].click();
                        break;
                    case 'End':
                        e.preventDefault();
                        tabs[tabs.length - 1].focus();
                        tabs[tabs.length - 1].click();
                        break;
                }
            });
        });
    }

    // Color Contrast Checker
    checkColorContrast(element) {
        const styles = window.getComputedStyle(element);
        const backgroundColor = styles.backgroundColor;
        const color = styles.color;

        // Convert RGB to hex for comparison
        const bgHex = this.rgbToHex(backgroundColor);
        const textHex = this.rgbToHex(color);

        // Calculate contrast ratio
        const contrast = this.calculateContrast(bgHex, textHex);
        
        return {
            contrast: contrast,
            passesAA: contrast >= 4.5,
            passesAAA: contrast >= 7,
            backgroundColor: bgHex,
            textColor: textHex
        };
    }

    rgbToHex(rgb) {
        const result = rgb.match(/\d+/g);
        if (!result) return '#000000';
        
        const r = parseInt(result[0]);
        const g = parseInt(result[1]);
        const b = parseInt(result[2]);
        
        return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
    }

    calculateContrast(hex1, hex2) {
        const lum1 = this.getLuminance(hex1);
        const lum2 = this.getLuminance(hex2);
        
        const brightest = Math.max(lum1, lum2);
        const darkest = Math.min(lum1, lum2);
        
        return (brightest + 0.05) / (darkest + 0.05);
    }

    getLuminance(hex) {
        const rgb = this.hexToRgb(hex);
        const [r, g, b] = [rgb.r, rgb.g, rgb.b].map(val => {
            val = val / 255;
            return val <= 0.03928 ? val / 12.92 : Math.pow((val + 0.055) / 1.055, 2.4);
        });
        
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    }

    hexToRgb(hex) {
        const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
        return result ? {
            r: parseInt(result[1], 16),
            g: parseInt(result[2], 16),
            b: parseInt(result[3], 16)
        } : { r: 0, g: 0, b: 0 };
    }

    // Auto-enhance page elements
    autoEnhancePage() {
        // Enhance navigation
        document.querySelectorAll('nav').forEach(nav => this.enhanceNavigation(nav));

        // Enhance tables
        document.querySelectorAll('table').forEach(table => this.enhanceTable(table));

        // Enhance modals
        document.querySelectorAll('.modal').forEach(modal => this.enhanceModal(modal));

        // Enhance tab interfaces
        document.querySelectorAll('[role="tablist"]').forEach(tabs => this.enhanceTabInterface(tabs.parentElement));

        // Add landmark roles
        this.addLandmarkRoles();

        // Setup heading hierarchy
        this.setupHeadingHierarchy();
    }

    addLandmarkRoles() {
        // Add banner role to header
        const header = document.querySelector('header');
        if (header && !header.hasAttribute('role')) {
            header.setAttribute('role', 'banner');
        }

        // Add main role if missing
        const main = document.querySelector('main');
        if (main && !main.hasAttribute('role')) {
            main.setAttribute('role', 'main');
        }

        // Add contentinfo role to footer
        const footer = document.querySelector('footer');
        if (footer && !footer.hasAttribute('role')) {
            footer.setAttribute('role', 'contentinfo');
        }

        // Add complementary role to aside
        document.querySelectorAll('aside').forEach(aside => {
            if (!aside.hasAttribute('role')) {
                aside.setAttribute('role', 'complementary');
            }
        });
    }

    setupHeadingHierarchy() {
        // Check for proper heading structure
        const headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
        let lastLevel = 0;

        headings.forEach(heading => {
            const currentLevel = parseInt(heading.tagName.substring(1));
            
            if (lastLevel > 0 && currentLevel > lastLevel + 1) {
                console.warn(`Heading hierarchy jump: h${lastLevel} to h${currentLevel} at:`, heading.textContent);
            }
            
            lastLevel = currentLevel;
        });
    }

    // Utility method to check if user prefers reduced motion
    prefersReducedMotion() {
        return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }

    // Utility method to check if user prefers high contrast
    prefersHighContrast() {
        return window.matchMedia('(prefers-contrast: high)').matches;
    }
}

// Initialize the utilities
window.accessibilityUtils = new AccessibilityUtils();
window.AccessibilityUtils = AccessibilityUtils;

// Auto-enhance page when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.accessibilityUtils.autoEnhancePage();
});

// Convenience functions
window.announce = (message, priority) => window.accessibilityUtils.announce(message, priority);
window.announceStatus = (message) => window.accessibilityUtils.announceStatus(message);