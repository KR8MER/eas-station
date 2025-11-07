# Agent Development Guidelines

This document provides guidelines for AI agents (like Claude) working on the EAS Station codebase.

## Environment Variables

### Adding New Environment Variables

When adding a new environment variable to the system, you MUST update these files:

1. **`.env.example`** - Add the variable with documentation and a default value
2. **`stack.env`** - Add the variable with the default value for Docker deployments
3. **`docker-entrypoint.sh`** - Add the variable to the initialization section (around line 170) if it needs to be available during container startup
4. **`webapp/admin/environment.py`** - Add the variable to the appropriate category in `ENV_CATEGORIES` to make it accessible in the web UI settings page

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
- `boolean` - Checkbox (values: 'true'/'false' as strings)
- `password` - Password field with masking (set `sensitive: True`)
- `select` - Dropdown with predefined options
- `textarea` - Multi-line text input

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

✅ **DO:**
- Use UPPERCASE_WITH_UNDERSCORES for environment variable names
- Provide clear descriptions for every variable
- Set sensible defaults
- Make variables accessible in the web UI when appropriate
- Document any special requirements or constraints
