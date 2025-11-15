# Repository Statistics Feature

## Overview

The EAS Station repository now includes automated tracking and display of repository statistics. This feature provides insights into the codebase structure, including file counts, lines of code, and route distribution.

## Accessing Statistics

### Via Web UI

The repository statistics are accessible through the documentation system:

1. Navigate to the documentation section of the application
2. Go to **Reference** → **Repository Statistics**
3. Or directly access: `/docs/static/REPO_STATS`

### Via File System

The statistics file is located at:
```
static/docs/REPO_STATS.md
```

## Statistics Included

The statistics page shows:

- **Overview**: Total files, directories, lines of code, and routes
- **Files by Type**: Breakdown of files by language/type
- **Lines of Code by Type**: Detailed metrics including code and comment lines
- **Routes by File**: Flask routes organized by file
- **Code Distribution**: Visual representation of language usage

## Automatic Updates

Statistics are automatically regenerated:
- On every push to `main` or `develop` branches
- Via GitHub Actions workflow
- Changes are committed back to the repository

## Manual Generation

To manually regenerate statistics:

```bash
python scripts/generate_repo_stats.py
```

This will update `static/docs/REPO_STATS.md` with the latest statistics.

## Implementation Details

### Files

1. **scripts/generate_repo_stats.py**: Script that analyzes the repository
   - Scans all files and directories
   - Counts lines of code with language-specific comment detection
   - Identifies Flask routes using regex patterns
   - Generates formatted markdown output

2. **static/docs/REPO_STATS.md**: Generated statistics file
   - Served through the documentation system
   - Updated automatically on push

3. **.github/workflows/update-repo-stats.yml**: GitHub Actions workflow
   - Triggers on push to main/develop
   - Runs the statistics generation script
   - Commits changes with `[skip ci]` to prevent infinite loops

4. **webapp/documentation.py**: Enhanced documentation viewer
   - Supports files from `static/docs` directory
   - Includes Repository Statistics in the Reference category

### Security

- Path traversal protection in documentation routes
- Explicit permissions in GitHub Actions workflow
- CodeQL security scanning passed

## Example Output

```markdown
# Repository Statistics

**Generated:** 2025-11-15 14:11:35 UTC

## Overview

- **Total Files:** 559
- **Total Directories:** 71
- **Total Lines:** 190,069
- **Code Lines:** 120,052
- **Comment Lines:** 40,099
- **Total Routes:** 173

## Files by Type

| File Type | Count |
|-----------|-------|
| Python | 230 |
| Markdown | 142 |
| HTML | 66 |
...
```

## Testing

Run the test suite to verify the feature:

```bash
python tests/test_repo_statistics.py
```

Tests validate:
- Statistics file structure and content
- Documentation system integration
- Security checks
- Workflow configuration

## Customization

To add more statistics or modify the output:

1. Edit `scripts/generate_repo_stats.py`
2. Update the `analyze_repository()` function to collect new metrics
3. Modify `generate_markdown()` to format the output
4. Test locally before pushing

## Troubleshooting

**Statistics not updating after push?**
- Check the GitHub Actions workflow status
- Verify you're pushing to `main` or `develop` branch
- Check workflow permissions in repository settings

**Can't access statistics page?**
- Ensure the file exists at `static/docs/REPO_STATS.md`
- Check that the Flask application is running
- Verify documentation routes are registered

**Statistics seem incorrect?**
- Run the script manually: `python scripts/generate_repo_stats.py`
- Check for errors in the output
- Verify excluded directories in the script are correct
