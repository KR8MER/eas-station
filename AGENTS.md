# Agent Development Guidelines

This document provides guidelines for AI agents (like Claude) working on the EAS Station codebase.

## Environment Variables

### Adding New Environment Variables

When adding a new environment variable to the system, you MUST update these files:

1. **`.env.example`** - Add the variable with documentation and a default value
2. **`stack.env`** - Add the variable with the default value for Docker deployments
3. **`docker-entrypoint.sh`** - Add the variable to the initialization section (around line 170) if it needs to be available during container startup
4. **`webapp/admin/environment.py`** - Add the variable to the appropriate category in `ENV_CATEGORIES` to make it accessible in the web UI settings page
5. **`app_utils/setup_wizard.py`** - If the variable is part of initial setup, add it to the appropriate wizard section with matching validation

### Keeping Validation in Sync

**CRITICAL:** Validation rules MUST match between `webapp/admin/environment.py` and `app_utils/setup_wizard.py`. Users should not be able to enter invalid values in either interface.

When adding validation:
- **SECRET_KEY**: Use `_validate_secret_key` in setup wizard (min 32 chars), `minlength: 32, pattern: ^[A-Za-z0-9]{32,}$` in environment.py
- **Port numbers**: Use `_validate_port` in setup wizard, `min: 1, max: 65535` in environment.py
- **IP addresses**: Use `_validate_ipv4` in setup wizard, `pattern: IPv4 regex` in environment.py
- **GPIO pins**: Use `_validate_gpio_pin` in setup wizard, `min: 2, max: 27` in environment.py
- **Station IDs**: Use `_validate_station_id` in setup wizard, `pattern: ^[A-Z0-9/]{1,8}$` in environment.py
- **Originator codes**: Use dropdown in both (4 options: WXR, EAS, PEP, CIV)

### Example: Adding WEB_ACCESS_LOG

Here's an example of properly adding an environment variable:

```python
# In webapp/admin/environment.py, add to appropriate category:
{
    'key': 'WEB_ACCESS_LOG',
    'label': 'Web Server Access Logs',
    'type': 'boolean',
    'default': 'false',
    'description': 'Enable web server access logs (shows all HTTP requests). Disable to reduce log clutter and only show errors.',
},
```

### Variable Types in environment.py

- `text` - Text input field
- `number` - Numeric input with optional min/max/step
- `password` - Password field with masking (set `sensitive: True`)
- `select` - Dropdown with predefined options
- `textarea` - Multi-line text input

**IMPORTANT:** Never use `boolean` type. Always use `select` with `options: ['false', 'true']` for yes/no or true/false values. This prevents end users from inputting invalid responses and breaking functionality.

```python
# ❌ WRONG - Don't use boolean type
{
    'key': 'SOME_FLAG',
    'type': 'boolean',
    'default': 'false',
}

# ✅ CORRECT - Use select with explicit options
{
    'key': 'SOME_FLAG',
    'type': 'select',
    'options': ['false', 'true'],
    'default': 'false',
}
```

### Input Validation

**ALWAYS add validation attributes to prevent invalid input:**

**Important Principle:** If a field has only a fixed set of valid values (e.g., 4 originator codes, specific status codes), use a `select` dropdown instead of a `text` field with regex validation. This provides the best user experience and prevents any possibility of invalid input.

#### Port Numbers

```python
{
    'key': 'SOME_PORT',
    'label': 'Port',
    'type': 'number',
    'default': '8080',
    'min': 1,          # Ports start at 1
    'max': 65535,      # Maximum valid port
}
```

#### IP Addresses

```python
{
    'key': 'SOME_IP',
    'label': 'IP Address',
    'type': 'text',
    'pattern': '^((25[0-5]|(2[0-4]|1\\d|[1-9]|)\\d)\\.?\\b){4}$',
    'title': 'Must be a valid IPv4 address (e.g., 192.168.1.100)',
    'placeholder': '192.168.1.100',
}
```

#### GPIO Pins (Raspberry Pi BCM)

```python
{
    'key': 'GPIO_PIN',
    'label': 'GPIO Pin',
    'type': 'number',
    'min': 2,    # Valid GPIO range
    'max': 27,   # Standard BCM numbering
    'placeholder': 'e.g., 17',
}
```

#### Alphanumeric Fields with Restricted Character Sets

Use regex patterns to enforce specific character requirements:

```python
# SECRET_KEY - at least 32 alphanumeric characters
{
    'key': 'SECRET_KEY',
    'label': 'Secret Key',
    'type': 'password',
    'required': True,
    'minlength': 32,
    'pattern': '^[A-Za-z0-9]{32,}$',
    'title': 'SECRET_KEY must be at least 32 characters long and contain only alphanumeric characters.',
    'sensitive': True,
}

# EAS Station ID - uppercase letters, numbers, forward slash only (no hyphens)
{
    'key': 'EAS_STATION_ID',
    'label': 'Station ID',
    'type': 'text',
    'maxlength': 8,
    'pattern': '^[A-Z0-9/]{1,8}$',
    'title': 'Must contain only uppercase letters (A-Z), numbers (0-9), and forward slash (/). No hyphens or lowercase letters.',
}

# When there are only specific valid values, use a dropdown instead of text with validation
{
    'key': 'EAS_ORIGINATOR',
    'label': 'Originator Code',
    'type': 'select',
    'options': ['WXR', 'EAS', 'PEP', 'CIV'],
    'default': 'WXR',
    'description': 'EAS originator code: WXR (Weather), EAS (Broadcast), PEP (Primary Entry Point), CIV (Civil Authority)',
}
```

#### Bounded Numeric Values

Always add `min` and `max` for numeric fields with known constraints:

```python
{
    'key': 'TIMEOUT_SECONDS',
    'type': 'number',
    'min': 10,
    'max': 300,
    'description': 'Timeout in seconds',
}
```

### Conditional Field Visibility

Use the `category` attribute to group fields that should be disabled when their parent feature is disabled.

**Pattern:** When a feature can be enabled/disabled, use this structure:

1. **Enable/Disable Field** - A select dropdown or text field that controls enablement
2. **Dependent Fields** - Fields with `category` attribute linking them to the parent

#### Example: Feature with Enable/Disable Toggle

```python
# Parent enable/disable field
{
    'key': 'EAS_BROADCAST_ENABLED',
    'label': 'Enable EAS Broadcasting',
    'type': 'select',
    'options': ['false', 'true'],
    'default': 'false',
    'description': 'Enable SAME/EAS audio generation',
},

# Dependent fields (will be grayed out when EAS_BROADCAST_ENABLED is false)
{
    'key': 'EAS_STATION_ID',
    'label': 'Station ID',
    'type': 'text',
    'category': 'eas_enabled',  # Links to parent feature
},
```

#### Example: Feature Enabled by Non-Empty Field

For features where an empty field means "disabled":

```python
# Parent field - empty means disabled
{
    'key': 'LED_SIGN_IP',
    'label': 'LED Sign IP Address',
    'type': 'text',
    'description': 'IP address of LED sign (leave empty to disable). Disabling this will gray out other LED settings.',
    'pattern': '^((25[0-5]|(2[0-4]|1\\d|[1-9]|)\\d)\\.?\\b){4}$',
},

# Dependent fields
{
    'key': 'LED_SIGN_PORT',
    'label': 'LED Sign Port',
    'type': 'number',
    'category': 'led_enabled',  # Disabled when LED_SIGN_IP is empty
    'min': 1,
    'max': 65535,
},
```

#### Category Naming Convention

Use descriptive category names that indicate the feature:
- `eas_enabled` - EAS broadcast feature
- `gpio_enabled` - GPIO control feature
- `led_enabled` - LED display feature
- `vfd_enabled` - VFD display feature
- `email` - Email notification sub-fields
- `azure_openai` - Azure OpenAI TTS sub-fields

**Frontend Implementation Note:** The frontend should:
1. Disable (gray out) fields when their parent is disabled/empty
2. Optionally hide fields entirely for cleaner UI
3. Prevent form submission if disabled fields have validation errors

### Variable Categories

Variables are organized into categories in `webapp/admin/environment.py`:

- **core** - Essential application configuration (SECRET_KEY, LOG_LEVEL, etc.)
- **database** - PostgreSQL connection settings
- **polling** - CAP feed polling configuration
- **location** - Default location and coverage area
- **eas** - EAS broadcast settings
- **gpio** - GPIO relay control
- **tts** - Text-to-speech providers
- **led** - LED display configuration
- **vfd** - VFD display configuration
- **notifications** - Email and SMS alerts
- **performance** - Caching and worker settings
- **docker** - Container and infrastructure settings

Choose the most appropriate category for your variable, or create a new one if needed.

## Logging

### Web Server Logs

- Gunicorn access logs can be controlled via `WEB_ACCESS_LOG` environment variable
- Default is `false` (disabled) to reduce log clutter
- Only errors are shown by default
- Users can enable access logs by setting `WEB_ACCESS_LOG=true`

### Application Logs

- Use the standard Python logging module
- Respect the `LOG_LEVEL` environment variable
- Common levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

## Docker and Deployment

### Environment Variable Loading

1. Variables are first defined in `stack.env` or `.env.example`
2. Docker Compose loads them from `.env` or `stack.env`
3. `docker-entrypoint.sh` may set defaults for missing variables
4. The Flask application reads from the environment

### Persistent Configuration

- If `CONFIG_PATH` is set, configuration is stored persistently
- The entrypoint script initializes this file from environment variables
- This allows configuration to survive container rebuilds

## Testing Changes

When adding new environment variables or changing configuration:

1. Update all four files mentioned above
2. Test that the variable appears in the web UI (Settings > Environment)
3. Test that the default value is correct
4. Test that changing the value takes effect after container restart
5. Verify the variable is documented with clear descriptions

## Common Mistakes

❌ **DON'T:**
- Add environment variables without updating `environment.py`
- Forget to add defaults in both `.env.example` and `stack.env`
- Use inconsistent naming conventions
- Use `boolean` type (use `select` instead)
- Forget validation attributes (min/max for numbers, pattern for IPs)
- Allow invalid port numbers (0 or > 65535)
- Create text fields for true/false values
- Forget to add `category` for dependent fields

✅ **DO:**
- Use UPPERCASE_WITH_UNDERSCORES for environment variable names
- Provide clear descriptions for every variable
- Set sensible defaults
- Make variables accessible in the web UI when appropriate
- Document any special requirements or constraints
- Add validation constraints to all numeric fields
- Use regex patterns for IP addresses and other structured data
- Group related fields with `category` attribute
- Add helpful `title` attributes for validation messages
