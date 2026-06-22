"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

"""Tests to ensure system health template field names match backend data structure."""
import sys
from pathlib import Path

import pytest

# Add parent directory to path to allow importing app modules
# This is required in test environment where package is not installed
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app_utils import system as system_utils


# Mock objects used for testing
class MockDB:
    """Mock database session for testing."""
    class session:
        @staticmethod
        def execute(query):
            class MockResult:
                def scalar(self):
                    return "PostgreSQL 15.0"
                def fetchone(self):
                    return ("100 MB",)
            return MockResult()


class MockLogger:
    """Mock logger for testing."""
    def debug(self, *args, **kwargs):
        pass
    def info(self, *args, **kwargs):
        pass
    def warning(self, *args, **kwargs):
        pass
    def error(self, *args, **kwargs):
        pass


class TestSystemHealthFieldNames:
    """Test that template field names match backend data structure."""

    def test_backend_returns_cpu_usage_percent(self):
        """Verify backend returns cpu_usage_percent, not overall_percent."""
        # Get health data
        try:
            health_data = system_utils.build_system_health_snapshot(MockDB(), MockLogger())
        except (ImportError, AttributeError, OSError) as e:
            # Skip if missing required dependencies or system access
            pytest.skip(f"Cannot run without full environment: {e}")
            return
        
        # Verify CPU field structure
        assert "cpu" in health_data, "Health data should contain 'cpu' key"
        cpu_data = health_data["cpu"]
        
        # Check for correct field name
        assert "cpu_usage_percent" in cpu_data, \
            "CPU data should contain 'cpu_usage_percent' field"
        
        # Verify old incorrect field doesn't exist
        assert "overall_percent" not in cpu_data, \
            "CPU data should NOT contain 'overall_percent' field (old name)"

    def test_backend_returns_disk_not_partitions(self):
        """Verify backend returns 'disk', not 'partitions'."""
        try:
            health_data = system_utils.build_system_health_snapshot(MockDB(), MockLogger())
        except (ImportError, AttributeError, OSError) as e:
            pytest.skip(f"Cannot run without full environment: {e}")
            return
        
        # Verify disk field structure
        assert "disk" in health_data, "Health data should contain 'disk' key"
        assert "partitions" not in health_data, \
            "Health data should NOT contain 'partitions' key (old name)"

    def test_disk_entries_have_percentage_not_percent_used(self):
        """Verify disk entries have 'percentage', not 'percent_used'."""
        try:
            health_data = system_utils.build_system_health_snapshot(MockDB(), MockLogger())
        except (ImportError, AttributeError, OSError) as e:
            pytest.skip(f"Cannot run without full environment: {e}")
            return
        
        disk_data = health_data.get("disk", [])
        if disk_data:
            # Check first disk entry
            first_disk = disk_data[0]
            assert "percentage" in first_disk, \
                "Disk entries should contain 'percentage' field"
            assert "percent_used" not in first_disk, \
                "Disk entries should NOT contain 'percent_used' field (old name)"

    def test_backend_returns_memory_percentage(self):
        """Verify backend returns memory with 'percentage' field, not 'percent'."""
        try:
            health_data = system_utils.build_system_health_snapshot(MockDB(), MockLogger())
        except (ImportError, AttributeError, OSError) as e:
            pytest.skip(f"Cannot run without full environment: {e}")
            return
        
        # Verify memory field structure
        assert "memory" in health_data, "Health data should contain 'memory' key"
        memory_data = health_data["memory"]
        
        # Check for correct field name
        assert "percentage" in memory_data, \
            "Memory data should contain 'percentage' field"
        
        # Verify old incorrect field doesn't exist
        assert "percent" not in memory_data, \
            "Memory data should NOT contain 'percent' field (would conflict with psutil object)"


class TestSystemHealthTemplateFieldNames:
    """Test that template uses correct field names."""

    def test_template_uses_cpu_usage_percent(self):
        """Verify template references cpu.cpu_usage_percent, not cpu.overall_percent."""
        template_path = Path(__file__).parent.parent / "templates" / "system_health.html"
        content = template_path.read_text()
        
        # Check that old incorrect field name is not used
        assert "cpu.overall_percent" not in content, \
            "Template should NOT reference 'cpu.overall_percent' (old field name)"
        
        # Check that correct field name is used
        assert "cpu.cpu_usage_percent" in content, \
            "Template should reference 'cpu.cpu_usage_percent' (correct field name)"

    def test_template_uses_disk_not_partitions(self):
        """Verify template references 'disk' variable, not 'partitions' in quick stats."""
        template_path = Path(__file__).parent.parent / "templates" / "system_health.html"
        content = template_path.read_text()
        
        # Extract the quick stats section
        quick_stats_start = content.find("<!-- Quick Stats Summary -->")
        quick_stats_end = content.find("<!-- System Stats Cards -->")
        quick_stats = content[quick_stats_start:quick_stats_end]
        
        # Check that template uses correct variable name
        assert "for partition in disk" in quick_stats, \
            "Template should iterate 'for partition in disk' in quick stats"
        
        # Check that old incorrect variable is not used
        assert "for partition in partitions" not in quick_stats, \
            "Template should NOT iterate 'for partition in partitions' in quick stats (old name)"

    def test_template_uses_percentage_not_percent_used(self):
        """Verify template references partition.percentage, not partition.percent_used."""
        template_path = Path(__file__).parent.parent / "templates" / "system_health.html"
        content = template_path.read_text()
        
        # Extract the quick stats section
        quick_stats_start = content.find("<!-- Quick Stats Summary -->")
        quick_stats_end = content.find("<!-- System Stats Cards -->")
        quick_stats = content[quick_stats_start:quick_stats_end]
        
        # Check that template uses correct field name
        assert "partition.percentage" in quick_stats, \
            "Template should reference 'partition.percentage' in quick stats"
        
        # Check that old incorrect field is not used
        assert "percent_used" not in quick_stats, \
            "Template should NOT reference 'percent_used' in quick stats (old field name)"

    def test_template_uses_memory_percentage_not_percent(self):
        """Verify template references memory.percentage, not memory.percent."""
        template_path = Path(__file__).parent.parent / "templates" / "system_health.html"
        content = template_path.read_text()
        
        # Use word boundary regex to check for exact field name (not as substring of percentage)
        import re
        
        # Check that old incorrect field name is not used (with word boundary)
        # This matches "memory.percent" but NOT "memory.percentage"
        old_field_pattern = r'memory\.percent\b'
        assert not re.search(old_field_pattern, content), \
            "Template should NOT reference 'memory.percent' (old field name)"
        
        # Check that correct field name is used
        assert "memory.percentage" in content, \
            "Template should reference 'memory.percentage' (correct field name)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
