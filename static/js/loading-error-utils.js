/**
 * Loading States & Error Handling Utilities
 * Provides consistent loading states, error handling, and user feedback
 */

class LoadingErrorUtils {
    constructor() {
        this.activeLoadingStates = new Set();
        this.retryAttempts = new Map();
        this.maxRetries = 3;
        this.init();
    }

    init() {
        // Add CSS files if not already included
        this.ensureStylesheets();
        // Initialize global error handlers
        this.setupGlobalErrorHandlers();
    }

    ensureStylesheets() {
        const stylesheets = [
            '/static/css/loading-states.css',
            '/static/css/error-handling.css'
        ];

        stylesheets.forEach(href => {
            if (!document.querySelector(`link[href="${href}"]`)) {
                const link = document.createElement('link');
                link.rel = 'stylesheet';
                link.href = href;
                document.head.appendChild(link);
            }
        });
    }

    setupGlobalErrorHandlers() {
        // Handle unhandled promise rejections
        window.addEventListener('unhandledrejection', (event) => {
            console.error('Unhandled promise rejection:', event.reason);
            this.showNetworkError('An unexpected error occurred. Please try again.');
            event.preventDefault();
        });

        // Handle uncaught errors
        window.addEventListener('error', (event) => {
            console.error('Uncaught error:', event.error);
            this.showError(null, 'An unexpected error occurred. Please refresh the page.');
        });
    }

    // Loading State Management
    showLoading(element, options = {}) {
        const {
            overlay = false,
            text = 'Loading...',
            size = 'normal',
            dark = false
        } = options;

        if (typeof element === 'string') {
            element = document.querySelector(element);
        }

        if (!element) return;

        this.activeLoadingStates.add(element);

        if (overlay) {
            this.showLoadingOverlay(element, text, size, dark);
        } else {
            element.classList.add('loading');
            if (element.tagName === 'BUTTON') {
                element.dataset.originalText = element.textContent;
                element.textContent = text;
            }
        }
    }

    hideLoading(element) {
        if (typeof element === 'string') {
            element = document.querySelector(element);
        }

        if (!element) return;

        this.activeLoadingStates.delete(element);

        // Remove overlay if present
        const overlay = element.querySelector('.spinner-overlay');
        if (overlay) {
            overlay.remove();
        }

        element.classList.remove('loading');
        if (element.tagName === 'BUTTON' && element.dataset.originalText) {
            element.textContent = element.dataset.originalText;
            delete element.dataset.originalText;
        }
    }

    showLoadingOverlay(element, text, size, dark) {
        const overlay = document.createElement('div');
        overlay.className = `spinner-overlay ${dark ? 'dark' : ''}`;
        overlay.innerHTML = `
            <div class="text-center">
                <div class="spinner-custom ${size} mb-2"></div>
                <div class="text-muted">${text}</div>
            </div>
        `;
        element.style.position = 'relative';
        element.appendChild(overlay);
    }

    // Skeleton Loading
    showSkeleton(container, type = 'card', count = 1) {
        if (typeof container === 'string') {
            container = document.querySelector(container);
        }

        if (!container) return;

        container.innerHTML = '';
        container.classList.add('loading-state');

        for (let i = 0; i < count; i++) {
            container.appendChild(this.createSkeletonElement(type));
        }
    }

    createSkeletonElement(type) {
        const skeleton = document.createElement('div');
        skeleton.className = 'skeleton';

        switch (type) {
            case 'text':
                skeleton.className += ' skeleton-text';
                break;
            case 'title':
                skeleton.className += ' skeleton-text title';
                break;
            case 'button':
                skeleton.className += ' skeleton-button';
                break;
            case 'avatar':
                skeleton.className += ' skeleton-avatar';
                break;
            case 'card':
                skeleton.className += ' skeleton-card';
                break;
            case 'row':
                skeleton.className = 'skeleton-row';
                skeleton.innerHTML = `
                    <div class="skeleton skeleton-avatar"></div>
                    <div class="skeleton skeleton-text"></div>
                `;
                break;
            case 'table':
                skeleton.className = 'skeleton-table';
                skeleton.innerHTML = `
                    <div class="skeleton-table-row">
                        <div class="skeleton skeleton-table-cell"></div>
                        <div class="skeleton skeleton-table-cell"></div>
                        <div class="skeleton skeleton-table-cell"></div>
                    </div>
                    <div class="skeleton-table-row">
                        <div class="skeleton skeleton-table-cell short"></div>
                        <div class="skeleton skeleton-table-cell"></div>
                        <div class="skeleton skeleton-table-cell medium"></div>
                    </div>
                    <div class="skeleton-table-row">
                        <div class="skeleton skeleton-table-cell"></div>
                        <div class="skeleton skeleton-table-cell short"></div>
                        <div class="skeleton skeleton-table-cell"></div>
                    </div>
                `;
                break;
            case 'metric':
                skeleton.className = 'skeleton-metric';
                skeleton.innerHTML = `
                    <div class="skeleton skeleton-metric-value"></div>
                    <div class="skeleton skeleton-metric-label"></div>
                `;
                break;
            default:
                skeleton.className += ' skeleton-card';
        }

        return skeleton;
    }

    hideSkeleton(container) {
        if (typeof container === 'string') {
            container = document.querySelector(container);
        }

        if (!container) return;

        container.classList.remove('loading-state');
        container.innerHTML = '';
    }

    // Error Handling
    showError(container, message, title = 'Error', actions = null) {
        if (typeof container === 'string') {
            container = document.querySelector(container);
        }

        if (!container) {
            // Show as toast if no container specified
            this.showToast(message, 'error', title);
            return;
        }

        const errorElement = document.createElement('div');
        errorElement.className = 'error-container fade-in';
        errorElement.innerHTML = `
            <div class="error-icon">
                <i class="fas fa-exclamation-triangle"></i>
            </div>
            <div class="error-title">${title}</div>
            <div class="error-message">${message}</div>
            ${actions ? `<div class="error-actions">${actions}</div>` : ''}
        `;

        container.innerHTML = '';
        container.appendChild(errorElement);
    }

    showWarning(container, message, title = 'Warning', actions = null) {
        if (typeof container === 'string') {
            container = document.querySelector(container);
        }

        if (!container) {
            this.showToast(message, 'warning', title);
            return;
        }

        const warningElement = document.createElement('div');
        warningElement.className = 'warning-container fade-in';
        warningElement.innerHTML = `
            <div class="warning-icon">
                <i class="fas fa-exclamation-triangle"></i>
            </div>
            <div class="warning-title">${title}</div>
            <div class="warning-message">${message}</div>
            ${actions ? `<div class="warning-actions">${actions}</div>` : ''}
        `;

        container.innerHTML = '';
        container.appendChild(warningElement);
    }

    showSuccess(container, message, title = 'Success', actions = null) {
        if (typeof container === 'string') {
            container = document.querySelector(container);
        }

        if (!container) {
            this.showToast(message, 'success', title);
            return;
        }

        const successElement = document.createElement('div');
        successElement.className = 'success-container fade-in';
        successElement.innerHTML = `
            <div class="success-icon">
                <i class="fas fa-check-circle"></i>
            </div>
            <div class="success-title">${title}</div>
            <div class="success-message">${message}</div>
            ${actions ? `<div class="success-actions">${actions}</div>` : ''}
        `;

        container.innerHTML = '';
        container.appendChild(successElement);
    }

    showEmpty(container, message, title = 'No Data', actions = null) {
        if (typeof container === 'string') {
            container = document.querySelector(container);
        }

        if (!container) return;

        const emptyElement = document.createElement('div');
        emptyElement.className = 'empty-state fade-in';
        emptyElement.innerHTML = `
            <div class="empty-state-icon">
                <i class="fas fa-inbox"></i>
            </div>
            <div class="empty-state-title">${title}</div>
            <div class="empty-state-message">${message}</div>
            ${actions ? `<div class="empty-state-actions">${actions}</div>` : ''}
        `;

        container.innerHTML = '';
        container.appendChild(emptyElement);
    }

    // Network Error Handling
    showNetworkError(message = 'Network error occurred. Please check your connection.') {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'network-error fade-in';
        errorDiv.innerHTML = `
            <div class="network-error-title">
                <i class="fas fa-wifi"></i>
                Connection Error
            </div>
            <div class="network-error-message">${message}</div>
        `;

        // Insert at the top of the main content area
        const mainContent = document.querySelector('main') || document.body;
        mainContent.insertBefore(errorDiv, mainContent.firstChild);

        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (errorDiv.parentNode) {
                errorDiv.remove();
            }
        }, 5000);
    }

    // Toast Notifications
    showToast(message, type = 'info', title = '', duration = 5000) {
        const toastContainer = document.querySelector('.toast-container') || this.createToastContainer();

        const toast = document.createElement('div');
        toast.className = `toast toast-notification toast-${type} fade-in`;
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.innerHTML = `
            <div class="toast-body d-flex align-items-center">
                <div class="flex-grow-1">
                    ${title ? `<strong class="d-block">${title}</strong>` : ''}
                    ${message}
                </div>
                <button type="button" class="btn-close btn-close-white ms-2" onclick="this.closest('.toast').remove()"></button>
            </div>
        `;

        toastContainer.appendChild(toast);

        // Auto-remove after duration
        setTimeout(() => {
            if (toast.parentNode) {
                toast.classList.add('fade-out');
                setTimeout(() => toast.remove(), 300);
            }
        }, duration);
    }

    createToastContainer() {
        const container = document.createElement('div');
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
        return container;
    }

    // Retry Logic
    async retryWithBackoff(operation, context = 'operation') {
        const key = `${context}_${Date.now()}`;
        let attempts = 0;

        while (attempts < this.maxRetries) {
            try {
                this.retryAttempts.set(key, attempts);
                return await operation();
            } catch (error) {
                attempts++;
                
                if (attempts >= this.maxRetries) {
                    this.retryAttempts.delete(key);
                    throw error;
                }

                // Calculate backoff delay (exponential with jitter)
                const baseDelay = 1000; // 1 second
                const maxDelay = 10000; // 10 seconds
                const exponentialDelay = Math.min(baseDelay * Math.pow(2, attempts - 1), maxDelay);
                const jitter = Math.random() * 1000;
                const delay = exponentialDelay + jitter;

                console.warn(`Attempt ${attempts} failed for ${context}. Retrying in ${Math.round(delay)}ms:`, error);
                
                // Show retry notification
                if (attempts === 1) {
                    this.showToast(`Connection issue. Retrying... (${attempts}/${this.maxRetries})`, 'warning', 'Network Error', 3000);
                }

                await new Promise(resolve => setTimeout(resolve, delay));
            }
        }

        this.retryAttempts.delete(key);
    }

    // Form Validation
    validateForm(formElement) {
        const errors = [];
        const inputs = formElement.querySelectorAll('input, select, textarea');

        inputs.forEach(input => {
            const formGroup = input.closest('.form-group');
            const errorElement = formGroup?.querySelector('.inline-error');
            
            // Remove previous error state
            input.classList.remove('field-error');
            if (errorElement) {
                errorElement.remove();
            }

            // Check required fields
            if (input.hasAttribute('required') && !input.value.trim()) {
                this.showFieldError(input, 'This field is required');
                errors.push(`${input.name || input.id} is required`);
            }

            // Check email format
            if (input.type === 'email' && input.value && !this.isValidEmail(input.value)) {
                this.showFieldError(input, 'Please enter a valid email address');
                errors.push(`${input.name || input.id} has invalid email format`);
            }

            // Check min/max length
            if (input.hasAttribute('minlength') && input.value.length < parseInt(input.getAttribute('minlength'))) {
                this.showFieldError(input, `Minimum ${input.getAttribute('minlength')} characters required`);
                errors.push(`${input.name || input.id} is too short`);
            }

            if (input.hasAttribute('maxlength') && input.value.length > parseInt(input.getAttribute('maxlength'))) {
                this.showFieldError(input, `Maximum ${input.getAttribute('maxlength')} characters allowed`);
                errors.push(`${input.name || input.id} is too long`);
            }
        });

        return {
            isValid: errors.length === 0,
            errors: errors
        };
    }

    showFieldError(input, message) {
        const formGroup = input.closest('.form-group');
        if (!formGroup) return;

        formGroup.classList.add('error');
        input.classList.add('field-error');

        let errorElement = formGroup.querySelector('.inline-error');
        if (!errorElement) {
            errorElement = document.createElement('div');
            errorElement.className = 'inline-error';
            formGroup.appendChild(errorElement);
        }
        
        errorElement.textContent = message;
    }

    clearFieldErrors(input) {
        const formGroup = input.closest('.form-group');
        if (!formGroup) return;

        formGroup.classList.remove('error');
        input.classList.remove('field-error');

        const errorElement = formGroup.querySelector('.inline-error');
        if (errorElement) {
            errorElement.remove();
        }
    }

    isValidEmail(email) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(email);
    }

    // Utility Methods
    createRetryButton(onClick, text = 'Retry') {
        const button = document.createElement('button');
        button.className = 'btn btn-retry';
        button.innerHTML = `
            <i class="fas fa-redo"></i>
            ${text}
        `;
        button.onclick = onClick;
        return button;
    }

    createCancelButton(onClick, text = 'Cancel') {
        const button = document.createElement('button');
        button.className = 'btn btn-outline-secondary';
        button.innerHTML = `
            <i class="fas fa-times"></i>
            ${text}
        `;
        button.onclick = onClick;
        return button;
    }

    // Progress indication
    showProgress(container, message = 'Processing...') {
        if (typeof container === 'string') {
            container = document.querySelector(container);
        }

        if (!container) return;

        container.innerHTML = `
            <div class="text-center py-4">
                <div class="progress-loading mb-3">
                    <div class="progress-loading-bar"></div>
                </div>
                <div class="text-muted">${message}</div>
                <div class="loading-dots mt-2">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
            </div>
        `;
    }
}

// Initialize the utilities
window.loadingErrorUtils = new LoadingErrorUtils();

// Export for global access
window.LoadingErrorUtils = LoadingErrorUtils;

// Convenience functions
window.showLoading = (element, options) => window.loadingErrorUtils.showLoading(element, options);
window.hideLoading = (element) => window.loadingErrorUtils.hideLoading(element);
window.showError = (container, message, title, actions) => window.loadingErrorUtils.showError(container, message, title, actions);
window.showSuccess = (container, message, title, actions) => window.loadingErrorUtils.showSuccess(container, message, title, actions);
window.showToast = (message, type, title, duration) => window.loadingErrorUtils.showToast(message, type, title, duration);
window.retryWithBackoff = (operation, context) => window.loadingErrorUtils.retryWithBackoff(operation, context);