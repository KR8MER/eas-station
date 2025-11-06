# Security Best Practices for EAS Station Development

## JavaScript XSS Prevention

### ❌ Avoid Using `innerHTML` with Dynamic Content

When displaying user-provided or dynamic content, **never** use `innerHTML` as it can lead to XSS (Cross-Site Scripting) vulnerabilities.

**Bad Example:**
```javascript
// VULNERABLE TO XSS!
element.innerHTML = `<div>${userInput}</div>`;
```

### ✅ Use Safe Alternatives

#### 1. Use `textContent` for Plain Text
```javascript
// Safe - automatically escapes HTML
element.textContent = userInput;
```

#### 2. Use EASUtils Helper Functions

The EAS Station provides security utilities in `/static/js/core/utils.js`:

```javascript
// Escape HTML entities
const safe = window.EASUtils.escapeHtml(userInput);

// Safely set text content
window.EASUtils.setSafeText('#element-id', userInput);

// Create elements programmatically
const div = window.EASUtils.createSafeElement(
    parentElement,
    'div',
    { className: 'alert' },
    userInput  // Automatically escaped
);
```

#### 3. Use DOM Methods
```javascript
// Safe - create elements programmatically
const div = document.createElement('div');
div.className = 'alert';
div.textContent = userInput;  // Automatically escaped
parentElement.appendChild(div);
```

### When `innerHTML` is Acceptable

Only use `innerHTML` with **static, trusted content** that you control:

```javascript
// OK - static HTML template
container.innerHTML = `
    <div class="spinner-border" role="status">
        <span class="visually-hidden">Loading...</span>
    </div>
`;
```

### File Upload Security

Always validate file uploads:

```python
# Python example from routes_vfd.py
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# Validate extension
file_ext = os.path.splitext(file.filename)[1].lower()
if file_ext not in ALLOWED_EXTENSIONS:
    return error_response("Invalid file type")

# Validate size
file.seek(0, os.SEEK_END)
file_size = file.tell()
if file_size > MAX_FILE_SIZE:
    return error_response("File too large")

# Validate actual file content
from PIL import Image
try:
    img = Image.open(io.BytesIO(file_data))
    img.verify()
except Exception:
    return error_response("Invalid image file")
```

## Docker Security

### ❌ Avoid Privileged Containers

**Never** use `privileged: true` in docker-compose.yml unless absolutely necessary.

```yaml
# BAD - gives container full host access
privileged: true
```

### ✅ Use Specific Capabilities

Grant only the capabilities needed:

```yaml
# GOOD - minimal permissions for USB devices
cap_add:
  - SYS_RAWIO
security_opt:
  - no-new-privileges:true
```

## Python Security

### ❌ Avoid Bare Exception Handlers

```python
# BAD - catches everything including KeyboardInterrupt
try:
    do_something()
except:
    pass
```

### ✅ Catch Specific Exceptions

```python
# GOOD - only catch expected exceptions
try:
    do_something()
except (OSError, IOError) as e:
    logger.error(f"Operation failed: {e}")
```

### ❌ Avoid render_template_string

```python
# BAD - potential template injection
return render_template_string(f"<h1>{user_input}</h1>")
```

### ✅ Use Template Files

```python
# GOOD - use proper template files
return render_template('errors/error.html', message=user_input)
```

## SQL Injection Prevention

### ✅ Use SQLAlchemy ORM (Already Implemented)

EAS Station uses SQLAlchemy which provides automatic SQL injection protection:

```python
# GOOD - parameterized query via ORM
user = User.query.filter_by(username=user_input).first()

# GOOD - using text() with bound parameters
from sqlalchemy import text
result = db.session.execute(
    text("SELECT * FROM users WHERE username = :username"),
    {"username": user_input}
)
```

## Environment Variables

### ✅ Never Commit Secrets

- Use `.env` files for configuration
- Keep `.env` in `.gitignore`
- Provide `.env.example` with placeholder values
- Document all required variables

### ✅ Use Strong Defaults

```bash
# BAD - weak default
SECRET_KEY=secret123

# GOOD - require generation
SECRET_KEY=replace-with-a-long-random-string
# Generate with: python3 -c 'import secrets; print(secrets.token_hex(32))'
```

## Code Review Checklist

Before submitting a PR, verify:

- [ ] No `innerHTML` with user/dynamic content
- [ ] All file uploads validated (type, size, content)
- [ ] No bare `except:` clauses
- [ ] No `render_template_string` with user input
- [ ] No hardcoded credentials
- [ ] No `privileged: true` in Docker configs
- [ ] All SQL queries parameterized
- [ ] Error messages don't leak sensitive info
- [ ] Input validation on all user inputs
- [ ] Output encoding for all dynamic content

## Reporting Security Issues

If you discover a security vulnerability:

1. **Do not** create a public GitHub issue
2. Email security concerns to the maintainers
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [OWASP XSS Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html)
- [Flask Security Best Practices](https://flask.palletsprojects.com/en/latest/security/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)

---

*Last Updated: 2025-11-06*
*Part of the EAS Station Security Initiative*
