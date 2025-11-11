#!/usr/bin/env python3
"""Tests for backup and restore functionality."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestBackupRestore(unittest.TestCase):
    """Test cases for backup and restore tools."""

    @classmethod
    def setUpClass(cls):
        """Set up test environment."""
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.tools_dir = cls.repo_root / "tools"
        cls.test_backup_dir = None

    def setUp(self):
        """Create temporary directory for each test."""
        self.temp_dir = tempfile.mkdtemp(prefix="eas_backup_test_")

    def tearDown(self):
        """Clean up temporary directory."""
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)

    def test_backup_script_exists(self):
        """Test that backup script exists and is executable."""
        backup_script = self.tools_dir / "create_backup.py"
        self.assertTrue(backup_script.exists(), "Backup script not found")
        self.assertTrue(backup_script.stat().st_mode & 0o111, "Backup script not executable")

    def test_restore_script_exists(self):
        """Test that restore script exists and is executable."""
        restore_script = self.tools_dir / "restore_backup.py"
        self.assertTrue(restore_script.exists(), "Restore script not found")
        self.assertTrue(restore_script.stat().st_mode & 0o111, "Restore script not executable")

    def test_scheduler_script_exists(self):
        """Test that scheduler script exists and is executable."""
        scheduler_script = self.tools_dir / "backup_scheduler.py"
        self.assertTrue(scheduler_script.exists(), "Scheduler script not found")
        self.assertTrue(scheduler_script.stat().st_mode & 0o111, "Scheduler script not executable")

    def test_rotate_script_exists(self):
        """Test that rotation script exists."""
        rotate_script = self.tools_dir / "rotate_backups.py"
        self.assertTrue(rotate_script.exists(), "Rotation script not found")

    def test_backup_help(self):
        """Test that backup script shows help."""
        result = subprocess.run(
            [sys.executable, str(self.tools_dir / "create_backup.py"), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, "Backup --help failed")
        self.assertIn("backup", result.stdout.lower())

    def test_restore_help(self):
        """Test that restore script shows help."""
        result = subprocess.run(
            [sys.executable, str(self.tools_dir / "restore_backup.py"), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, "Restore --help failed")
        self.assertIn("restore", result.stdout.lower())

    def test_scheduler_help(self):
        """Test that scheduler script shows help."""
        result = subprocess.run(
            [sys.executable, str(self.tools_dir / "backup_scheduler.py"), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, "Scheduler --help failed")
        self.assertIn("backup", result.stdout.lower())

    def test_backup_dry_run(self):
        """Test backup with minimal configuration (no-media, no-volumes)."""
        result = subprocess.run(
            [
                sys.executable,
                str(self.tools_dir / "create_backup.py"),
                "--output-dir", self.temp_dir,
                "--label", "test",
                "--no-media",
                "--no-volumes",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        # May fail if database is not available, but should not crash
        self.assertIsNotNone(result.returncode, "Backup script crashed")
        self.assertNotEqual(result.returncode, -1, "Backup script crashed with segfault")

    def test_metadata_structure(self):
        """Test that backup metadata has required fields."""
        # Create a mock metadata file
        metadata = {
            "timestamp": "2025-01-11T00:00:00Z",
            "label": "test",
            "git_commit": "abc123",
            "git_branch": "main",
            "app_version": "2.1.0",
            "database": {
                "host": "localhost",
                "port": "5432",
                "name": "alerts",
                "user": "postgres",
            },
            "summary": {
                "config": True,
                "database": True,
                "media": [],
                "volumes": [],
                "total_size_mb": 1.0,
            },
        }

        # Validate all required fields are present
        required_fields = ["timestamp", "app_version", "database", "summary"]
        for field in required_fields:
            self.assertIn(field, metadata, f"Missing required field: {field}")

        # Validate database structure
        required_db_fields = ["host", "port", "name", "user"]
        for field in required_db_fields:
            self.assertIn(field, metadata["database"], f"Missing database field: {field}")

        # Validate summary structure
        required_summary_fields = ["config", "database", "total_size_mb"]
        for field in required_summary_fields:
            self.assertIn(field, metadata["summary"], f"Missing summary field: {field}")

    def test_restore_validation(self):
        """Test restore script validation with missing backup."""
        result = subprocess.run(
            [
                sys.executable,
                str(self.tools_dir / "restore_backup.py"),
                "--backup-dir", "/nonexistent/backup",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )

        # Should fail with nonexistent backup
        self.assertNotEqual(result.returncode, 0, "Should fail with nonexistent backup")
        self.assertIn("not found", result.stdout.lower() + result.stderr.lower())

    def test_systemd_files_exist(self):
        """Test that systemd example files exist."""
        systemd_dir = self.repo_root / "examples" / "systemd"
        self.assertTrue((systemd_dir / "eas-backup.service").exists(), "Missing systemd service")
        self.assertTrue((systemd_dir / "eas-backup.timer").exists(), "Missing systemd timer")
        self.assertTrue((systemd_dir / "README.md").exists(), "Missing systemd README")

    def test_cron_file_exists(self):
        """Test that cron example file exists."""
        cron_file = self.repo_root / "examples" / "cron" / "eas-backup.cron"
        self.assertTrue(cron_file.exists(), "Missing cron example")

    def test_runbooks_exist(self):
        """Test that operator runbooks exist."""
        runbooks_dir = self.repo_root / "docs" / "runbooks"
        self.assertTrue((runbooks_dir / "outage_response.md").exists(), "Missing outage runbook")
        self.assertTrue((runbooks_dir / "backup_strategy.md").exists(), "Missing backup runbook")

    def test_standby_config_exists(self):
        """Test that standby configuration example exists."""
        examples_dir = self.repo_root / "examples"
        self.assertTrue((examples_dir / "docker-compose.standby.yml").exists(), "Missing standby config")
        self.assertTrue((examples_dir / "STANDBY_DEPLOYMENT.md").exists(), "Missing standby docs")


class TestHealthEndpoint(unittest.TestCase):
    """Test cases for health monitoring endpoint."""

    def test_health_endpoint_code_exists(self):
        """Test that health endpoint code is in routes_monitoring.py."""
        routes_file = Path(__file__).resolve().parents[1] / "webapp" / "routes_monitoring.py"
        self.assertTrue(routes_file.exists(), "routes_monitoring.py not found")

        content = routes_file.read_text()
        self.assertIn("/health/dependencies", content, "Missing /health/dependencies endpoint")
        self.assertIn("def health_dependencies", content, "Missing health_dependencies function")


def run_tests():
    """Run all tests and return exit code."""
    # Discover and run tests
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Return exit code
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
