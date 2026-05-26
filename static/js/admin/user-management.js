/**
 * Admin Panel - User Management Module
 * Handles user CRUD operations, password management, and user role handling
 */

/**
 * Initialize user management functionality
 * Sets up event listeners and loads user accounts
 */
window.initializeUserManagement = function() {
    const form = document.getElementById('createUserForm') || document.getElementById('createUserForm-setup');
    const passwordInput = document.getElementById('newUserPassword') || document.getElementById('newUserPassword-setup');
    const confirmInput = document.getElementById('newUserPasswordConfirm') || document.getElementById('newUserPasswordConfirm-setup');
    if (!form || !passwordInput || !confirmInput) {
        return;
    }
    const refreshButton = document.getElementById('refreshUserList');
    if (refreshButton) {
        refreshButton.addEventListener('click', () => loadUserAccounts());
    }
    const validatePasswordMatch = () => {
        if (confirmInput.value !== passwordInput.value) {
            confirmInput.setCustomValidity('Passwords must match.');
        } else {
            confirmInput.setCustomValidity('');
        }
    };
    passwordInput.addEventListener('input', validatePasswordMatch);
    confirmInput.addEventListener('input', validatePasswordMatch);
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        event.stopPropagation();
        validatePasswordMatch();
        if (!form.checkValidity()) {
            form.classList.add('was-validated');
            return;
        }
        const username = form.username.value.trim();
        const password = passwordInput.value;
        try {
            const response = await fetch('/admin/users', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ username, password })
            });
            if (response.status === 401) {
                window.location.href = '/login';
                return;
            }
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                showStatus(data.error || 'Failed to create user.', 'danger');
                return;
            }
            form.reset();
            form.classList.remove('was-validated');
            confirmInput.setCustomValidity('');
            const successMessage = data.message || 'User created successfully.';
            const finalMessage = window.ADMIN_SETUP_MODE ? `${successMessage} Redirecting to sign in…` : successMessage;
            showStatus(finalMessage, 'success', window.ADMIN_SETUP_MODE ? 0 : 5000);
            loadUserAccounts();
            if (window.ADMIN_SETUP_MODE) {
                setTimeout(() => {
                    window.location.href = '/login';
                }, 1800);
            }
        } catch (error) {
            console.error('Failed to create user', error);
            showStatus('Unexpected error while creating user.', 'danger');
        }
    });
    const tableBody = document.getElementById('userTableBody');
    if (tableBody) {
        tableBody.addEventListener('click', (event) => {
            const button = event.target.closest('button[data-action]');
            if (!button) {
                return;
            }
            const userId = button.dataset.userId;
            const username = button.dataset.username;
            if (button.dataset.action === 'reset-password') {
                handleUserPasswordReset(userId, username);
            } else if (button.dataset.action === 'delete-user') {
                handleUserDeletion(userId, username);
            }
        });
    }
    loadUserAccounts();
};

/**
 * Load and display user accounts
 */
async function loadUserAccounts() {
    const tableBody = document.getElementById('userTableBody');
    if (!tableBody) {
        return;
    }
    tableBody.innerHTML = `
        <tr>
            <td colspan="4" class="text-center text-muted py-4">
                <div class="loading-spinner"></div>
                <span class="ms-2">Loading users...</span>
            </td>
        </tr>
    `;
    try {
        const response = await fetch('/admin/users', {
            headers: { 'Accept': 'application/json' }
        });
        if (response.status === 401) {
            window.location.href = '/login';
            return;
        }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            showStatus(data.error || 'Unable to load users.', 'danger');
            return;
        }
        const users = data.users || [];
        if (!users.length) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="4" class="text-center text-muted py-4">
                        No administrator accounts found.
                    </td>
                </tr>
            `;
            return;
        }
        tableBody.innerHTML = '';
        users.forEach(user => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td data-label="Username" class="text-nowrap"><strong>${user.username}</strong></td>
                <td data-label="Created" class="text-nowrap">${formatUserTimestamp(user.created_at)}</td>
                <td data-label="Last Login" class="text-nowrap">${formatUserTimestamp(user.last_login_at)}</td>
                <td class="text-end">
                    <div class="btn-group" role="group">
                        <button type="button" class="btn btn-sm btn-outline-primary" data-action="reset-password" data-user-id="${user.id}" data-username="${user.username}">
                            <i class="fas fa-key"></i> Reset
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-danger" data-action="delete-user" data-user-id="${user.id}" data-username="${user.username}">
                            <i class="fas fa-user-times"></i> Delete
                        </button>
                    </div>
                </td>
            `;
            tableBody.appendChild(row);
        });
    } catch (error) {
        console.error('Failed to load users', error);
        showStatus('Unexpected error while loading users.', 'danger');
    }
}

/**
 * Handle user password reset
 * @param {string} userId - User ID
 * @param {string} username - Username
 */
async function handleUserPasswordReset(userId, username) {
    if (!userId) {
        return;
    }
    const newPassword = prompt(`Enter a new password for ${username} (minimum 8 characters):`);
    if (newPassword === null) {
        return;
    }
    if (newPassword.trim().length < 8) {
        showStatus('Password must be at least 8 characters long.', 'warning');
        return;
    }
    try {
        const response = await fetch(`/admin/users/${userId}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify({ password: newPassword })
        });
        if (response.status === 401) {
            window.location.href = '/login';
            return;
        }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            showStatus(data.error || 'Failed to reset password.', 'danger');
            return;
        }
        showStatus(data.message || 'Password reset successfully.', 'success');
        loadUserAccounts();
    } catch (error) {
        console.error('Failed to reset password', error);
        showStatus('Unexpected error while resetting password.', 'danger');
    }
}

/**
 * Handle user deletion
 * @param {string} userId - User ID
 * @param {string} username - Username
 */
function handleUserDeletion(userId, username) {
    if (!userId) {
        return;
    }
    showConfirmation({
        title: 'Delete Administrator',
        message: `Remove administrator ${username}?`,
        warning: 'This user will immediately lose access to the admin console.',
        type: 'danger',
        confirmText: 'Delete User',
        onConfirm: async () => {
            try {
                const response = await fetch(`/admin/users/${userId}`, {
                    method: 'DELETE',
                    headers: { 'Accept': 'application/json' }
                });
                if (response.status === 401) {
                    window.location.href = '/login';
                    return;
                }
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    showStatus(data.error || 'Failed to delete user.', 'danger');
                    return;
                }
                showStatus(data.message || 'User deleted successfully.', 'success');
                loadUserAccounts();
            } catch (error) {
                console.error('Failed to delete user', error);
                showStatus('Unexpected error while deleting user.', 'danger');
            }
        }
    });
}

/**
 * Format user timestamp for display
 * @param {string} timestamp - ISO timestamp
 * @returns {string} Formatted timestamp or em dash
 */
function formatUserTimestamp(timestamp) {
    if (!timestamp) {
        return '—';
    }
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) {
        return '—';
    }
    return date.toLocaleString();
}

// Self-initialize (scripts load at end of body, so DOM is already parsed)
window.initializeUserManagement();
