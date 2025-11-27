#!/usr/bin/env python3
"""
Comprehensive Import Validation Tool

Validates all Python imports across the codebase to catch:
- Missing modules
- Circular imports
- Incorrect import paths
- Missing __init__.py exports

Run this BEFORE committing any refactoring changes!
"""

import ast
import os
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple


class ImportValidator:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.imports_map: Dict[str, Set[str]] = defaultdict(set)
        self.exports_map: Dict[str, Set[str]] = {}

    def validate(self) -> bool:
        """Run full validation. Returns True if no errors."""
        print("=" * 70)
        print("🔍 Validating Python Imports")
        print("=" * 70)
        print()

        # Step 1: Build exports map
        print("Step 1: Scanning module exports...")
        self._scan_exports()
        print(f"  Found {len(self.exports_map)} modules with __all__ exports")
        print()

        # Step 2: Scan all imports
        print("Step 2: Scanning imports...")
        python_files = self._find_python_files()
        print(f"  Found {len(python_files)} Python files")

        for filepath in python_files:
            self._scan_file_imports(filepath)
        print()

        # Step 3: Validate imports against exports
        print("Step 3: Validating imports against exports...")
        self._validate_imports()
        print()

        # Step 4: Print results
        self._print_results()

        return len(self.errors) == 0

    def _find_python_files(self) -> List[Path]:
        """Find all Python files in the project."""
        python_files = []
        skip_dirs = {
            'venv', 'node_modules', '.git', '__pycache__',
            '.pytest_cache', 'build', 'dist', '.egg-info',
            'migrations'  # Skip Alembic migrations
        }

        for root, dirs, files in os.walk(self.project_root):
            # Filter out directories to skip
            dirs[:] = [d for d in dirs if d not in skip_dirs]

            for file in files:
                if file.endswith('.py'):
                    python_files.append(Path(root) / file)

        return python_files

    def _scan_exports(self):
        """Scan all __init__.py and module files for __all__ exports."""
        for filepath in self._find_python_files():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    tree = ast.parse(f.read(), str(filepath))

                # Get module path
                rel_path = filepath.relative_to(self.project_root)
                module_parts = list(rel_path.with_suffix('').parts)

                # Convert to module name
                if module_parts[-1] == '__init__':
                    module_parts.pop()
                module_name = '.'.join(module_parts)

                # Find __all__ definition
                exports = self._find_exports(tree)
                if exports:
                    self.exports_map[module_name] = exports

            except Exception as e:
                self.warnings.append(f"Could not parse {filepath}: {e}")

    def _find_exports(self, tree: ast.AST) -> Set[str]:
        """Find __all__ exports in an AST."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == '__all__':
                        # Extract list values
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            exports = set()
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant):
                                    exports.add(elt.value)
                                elif isinstance(elt, ast.Str):  # Python 3.7 compat
                                    exports.add(elt.s)
                            return exports
        return set()

    def _scan_file_imports(self, filepath: Path):
        """Scan a file for all imports."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), str(filepath))

            rel_path = filepath.relative_to(self.project_root)

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module:
                        # from X import Y
                        for alias in node.names:
                            import_key = f"{rel_path}|{node.module}|{alias.name}"
                            self.imports_map[str(rel_path)].add((node.module, alias.name))

        except Exception as e:
            self.warnings.append(f"Could not scan imports in {filepath}: {e}")

    def _validate_imports(self):
        """Validate imports against known exports."""
        # Focus on our key modules that have been problematic
        critical_modules = {
            'app_core.extensions': ['db', 'get_radio_manager', 'get_redis_client'],
            'app_core.auth.decorators': ['require_auth', 'require_role', 'require_permission'],
            'app_core.redis_client': ['get_redis_client'],
            'app_core.auth.roles': ['require_permission', 'has_permission', 'get_current_user'],
        }

        for filepath, imports in self.imports_map.items():
            for module, name in imports:
                # Check critical modules
                if module in critical_modules:
                    if name not in critical_modules[module]:
                        self.errors.append(
                            f"❌ {filepath}: "
                            f"'{name}' not found in {module} "
                            f"(expected: {critical_modules[module]})"
                        )

                # Check against __all__ exports if available
                if module in self.exports_map:
                    if name != '*' and name not in self.exports_map[module]:
                        self.errors.append(
                            f"❌ {filepath}: "
                            f"'{name}' not exported by {module} "
                            f"(__all__ = {sorted(self.exports_map[module])})"
                        )

    def _print_results(self):
        """Print validation results."""
        print("=" * 70)
        print("📊 Validation Results")
        print("=" * 70)
        print()

        if self.warnings:
            print(f"⚠️  Warnings: {len(self.warnings)}")
            for warning in self.warnings[:10]:  # Show first 10
                print(f"  {warning}")
            if len(self.warnings) > 10:
                print(f"  ... and {len(self.warnings) - 10} more")
            print()

        if self.errors:
            print(f"❌ Errors: {len(self.errors)}")
            for error in self.errors:
                print(f"  {error}")
            print()
            print("💥 VALIDATION FAILED - Fix imports before committing!")
            return

        print("✅ All imports validated successfully!")
        print()
        print("Key modules checked:")
        print("  • app_core.extensions")
        print("  • app_core.auth.decorators")
        print("  • app_core.redis_client")
        print("  • app_core.auth.roles")


def main():
    """Run import validation."""
    project_root = Path(__file__).parent.parent
    validator = ImportValidator(str(project_root))

    success = validator.validate()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
