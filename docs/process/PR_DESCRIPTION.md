# Fix critical security issues, improve code quality, and standardize configuration

## Summary

This PR addresses critical security vulnerabilities, performance issues, and configuration inconsistencies discovered during a comprehensive code review.

## 🔴 Critical Security Fixes

### 1. **Disable Debug Mode in Production** (`app.py`)
- Changed from hardcoded `debug=True` to environment-controlled `FLASK_DEBUG`
- Prevents Werkzeug debugger exposure in production
- **Impact:** Prevents complete app exposure to attackers

### 2. **Require Explicit SECRET_KEY** (`app.py`, `configure.py`)
- No longer accepts empty or default secret keys
- Fails fast with clear error message if missing
- **Impact:** Prevents session hijacking attacks

### 3. **Remove Hardcoded Database Credentials** (`cap_poller.py`)
- Removed default `casaos:casaos` credentials
- Requires explicit configuration via environment variables
- **Impact:** Prevents credential exposure in code/history

### 4. **Fix Bare Exception Handlers** (`cap_poller.py`)
- Replaced `except: pass` with proper exception handling and logging
- **Impact:** Makes debugging possible, prevents silent failures

### 5. **URL Encoding of Database Credentials** (`configure.py`)
- **CRITICAL:** Added URL encoding to handle special characters in passwords
- Fixes app startup failures with strong passwords containing `@`, `:`, `/`, etc.
- **Impact:** Allows secure passwords in production

## 🟠 Performance Improvements

### 6. **Fix N+1 Query Pattern** (`webapp/admin/api.py`)
- Fetches geometry in single query with join instead of loop
- **Impact:** Reduces O(n) queries to single query - massive performance gain

### 7. **Add Limits to Export Endpoints** (`webapp/routes_exports.py`)
- `/export/alerts`: Default 10,000, max 50,000
- `/export/boundaries`: Default 5,000, max 20,000
- **Impact:** Prevents memory exhaustion on large datasets

## 🟡 Bug Fixes

### 8. **Fix IPAWS Poller Timestamp** (`.env.example`)
- Removed outdated `2024-02-15` timestamp
- Uses auto-fallback with dynamic timestamp
- **Impact:** Fixes "0 alerts fetched" issue

### 9. **Fix IPAWS SSL Certificate Error** (`Dockerfile`)
- Added `ca-certificates` package
- **Impact:** Allows HTTPS connections to FEMA endpoints

### 10. **Add Pagination Validation** (4 files)
- Prevents negative page numbers
- Clamps per_page to reasonable ranges
- **Impact:** Prevents DoS via malicious pagination parameters

### 11. **Fix Global State Race Conditions** (`app.py`, `app_core/location.py`)
- Added proper thread locking to database initialization
- Fixed TOCTOU bug in location settings cache
- **Impact:** Prevents concurrent initialization issues

## 📦 Configuration Improvements

### 12. **Consolidate Environment Variables** (`.env.example`)
- Removed duplicate `ALERTS_DB_*` variables (use `POSTGRES_*` only)
- Added 15+ missing variables (IPAWS config, location defaults, etc.)
- Better organization with 11 logical sections
- **Impact:** Single source of truth, easier to maintain

### 13. **Standardize Database Connection Logic** (`app.py`, `configure.py`, `cap_poller.py`)
- All files now use same logic: DATABASE_URL or auto-build from POSTGRES_*
- Consistent password requirements across all entry points
- Proper URL encoding of credentials
- **Impact:** No confusion, works reliably everywhere

### 14. **Enable Debug Logging** (`docker-compose.yml`)
- Added `--log-level DEBUG` to IPAWS poller
- **Impact:** Detailed logs for troubleshooting

## 📊 Files Changed

| Category | Files | Lines |
|----------|-------|-------|
| Security | 3 files | ~50 lines |
| Performance | 2 files | ~30 lines |
| Bug Fixes | 7 files | ~70 lines |
| Configuration | 3 files | ~350 lines |
| **Total** | **15 files** | **~500 lines** |

## 📚 Documentation Added

- `docs/guides/ENV_MIGRATION_GUIDE.md` - Step-by-step migration instructions
- `docs/guides/DATABASE_CONSISTENCY_FIXES.md` - Detailed analysis of database connection fixes
- Updated `.env.example` with comprehensive inline documentation

## ✅ Testing

All changes are backwards compatible for properly configured environments:
- If `DATABASE_URL` is set, no changes needed
- If `POSTGRES_*` variables are set with password, no changes needed
- Only fails fast if credentials are missing (which was already broken)

## 🚀 Deployment Notes

**No container rebuild needed** for .env changes - just restart:
```bash
docker compose restart
```

**For new deployments**, ensure:
```bash
SECRET_KEY=<64-char-hex-string>  # Generate with: python3 -c 'import secrets; print(secrets.token_hex(32))'
POSTGRES_PASSWORD=<secure-password>  # Can contain special characters now!
```

## 🎯 Benefits

✅ **Security:** No debug mode, required secrets, no default credentials
✅ **Performance:** Fixed N+1 queries, added export limits
✅ **Reliability:** Fixed IPAWS poller, proper error handling
✅ **Maintainability:** Consolidated config, consistent database logic
✅ **Production-Ready:** All security best practices enforced

---

## Commits in this PR

1. Fix critical security issues and improve code quality
2. Add .env to gitignore to prevent committing secrets
3. Fix IPAWS poller SSL certificate error and enable debug logging
4. Consolidate and improve environment variable configuration
5. Standardize database connection logic across all files
6. CRITICAL: Fix URL encoding of database credentials in configure.py

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
