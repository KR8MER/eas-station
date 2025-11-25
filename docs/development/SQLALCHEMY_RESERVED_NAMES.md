# SQLAlchemy Reserved Names and Common Pitfalls

## ⚠️ CRITICAL: Reserved Column Names

**DO NOT** use the following names as column names in SQLAlchemy models. These are reserved by SQLAlchemy's Declarative API and will cause `InvalidRequestError`:

### Reserved Names (DO NOT USE)
- `metadata` - Reserved by SQLAlchemy for database metadata
- `query` - Reserved by Flask-SQLAlchemy for query operations
- `registry` - Reserved by SQLAlchemy's declarative base

### Safe Alternatives
Instead of these reserved names, use descriptive alternatives:

```python
# ❌ WRONG - Will cause error
class MyModel(db.Model):
    metadata = db.Column(JSONB)  # ERROR: InvalidRequestError

# ✅ CORRECT - Use alternative name
class MyModel(db.Model):
    extra_metadata = db.Column(JSONB)  # Safe
    # OR
    model_metadata = db.Column(JSONB)   # Safe
    # OR
    meta_data = db.Column(JSONB)        # Safe (different name)
```

## Error Messages

If you use a reserved name, you'll see an error like:
```
sqlalchemy.exc.InvalidRequestError: Attribute name 'metadata' is reserved when using the Declarative API.
```

## Files That Were Fixed

This issue has occurred in the following files (search these if the error resurfaces):

1. **app_core/analytics/models.py**
   - `MetricSnapshot.extra_metadata` (was `metadata`)
   - `TrendRecord.extra_metadata` (was `metadata`)
   - `AnomalyRecord.extra_metadata` (was `metadata`)

## API Compatibility Note

When renaming columns, the `to_dict()` method should still return the expected API key:

```python
class MetricSnapshot(db.Model):
    # Database column uses safe name
    extra_metadata = db.Column(JSONB)

    def to_dict(self):
        return {
            # API key can still be 'metadata' for backwards compatibility
            'metadata': self.extra_metadata,
        }
```

This allows the database schema to use safe names while maintaining API compatibility.

## Other SQLAlchemy Reserved Names

While `metadata` is the most common issue, be aware of these other reserved names:

- Any attribute starting with `_sa_` (SQLAlchemy internal)
- `c` - Column collection shorthand
- `columns` - Column collection
- `mapper` - Model mapper
- `table` - Table reference
- `__tablename__` - Already used for table name definition
- `__table__` - The actual table object
- `__mapper__` - The mapper object

## Best Practices

1. **Prefix data columns** with descriptive names (e.g., `user_metadata`, `extra_metadata`, `config_metadata`)
2. **Check for errors early** - Run migrations in development before pushing to production
3. **Use migration scripts** - Always create Alembic migrations for schema changes
4. **Test imports** - Ensure all models can be imported without errors before deployment

## Quick Fix Checklist

If you encounter the 'metadata' error:

1. [ ] Find the model with the `metadata` column
2. [ ] Rename column to `extra_metadata` (or similar)
3. [ ] Update any code that accesses the column directly
4. [ ] Update `to_dict()` method if present (map `extra_metadata` → `'metadata'` in output)
5. [ ] Create an Alembic migration to rename the column in existing databases
6. [ ] Test the migration
7. [ ] Commit and push the fix

## Related Documentation

- [SQLAlchemy Declarative API](https://docs.sqlalchemy.org/en/14/orm/declarative_styles.html)
- [Flask-SQLAlchemy Models](https://flask-sqlalchemy.palletsprojects.com/en/3.0.x/models/)
- EAS Station: `docs/DATABASE.md` (if exists)

## History

- **2025-11-05**: Fixed `metadata` column issue in analytics models (commit: TBD)
  - Changed `MetricSnapshot.metadata` → `MetricSnapshot.extra_metadata`
  - Changed `TrendRecord.metadata` → `TrendRecord.extra_metadata`
  - Changed `AnomalyRecord.metadata` → `AnomalyRecord.extra_metadata`
  - Maintained API compatibility by mapping to 'metadata' key in `to_dict()`
