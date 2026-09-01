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

"""Regression tests for the setup wizard onboarding redesign.

Before this fix, only SECRET_KEY was blanked in the wizard form when it
already held a real, install.sh-configured value -- the four POSTGRES_*
credential fields (explicitly commented "NOT shown in wizard, managed by
install.sh" in app_utils/setup_wizard.py) were rendered with their real
values pre-filled anyway, and a user re-submitting the form without
touching them would resubmit stale/legitimate values as if freshly typed.
_is_managed_field_present() generalizes the SECRET_KEY-only check
(app_utils/setup_wizard.py's SYSTEM_MANAGED_FIELDS) to all five fields.

Also guards that every WIZARD_SECTIONS section carries the metadata the
redesigned template (accordion with headers/descriptions/field counts)
depends on.
"""

import pytest

from app_utils.setup_wizard import (
    PLACEHOLDER_SECRET_VALUES,
    SYSTEM_MANAGED_FIELDS,
    WIZARD_SECTIONS,
    WizardField,
)
from webapp.routes_setup import _is_managed_field_present

pytestmark = pytest.mark.unit


class TestIsManagedFieldPresent:
    def test_empty_value_is_not_present(self):
        field = SYSTEM_MANAGED_FIELDS[0]
        assert _is_managed_field_present(field, "") is False
        assert _is_managed_field_present(field, "   ") is False

    def test_secret_key_placeholder_value_is_not_present(self):
        secret_field = next(f for f in SYSTEM_MANAGED_FIELDS if f.key == "SECRET_KEY")
        for placeholder in PLACEHOLDER_SECRET_VALUES:
            assert _is_managed_field_present(secret_field, placeholder) is False

    def test_secret_key_valid_value_is_present(self):
        secret_field = next(f for f in SYSTEM_MANAGED_FIELDS if f.key == "SECRET_KEY")
        assert _is_managed_field_present(secret_field, "a" * 64) is True

    def test_postgres_field_with_a_real_value_is_present(self):
        host_field = next(f for f in SYSTEM_MANAGED_FIELDS if f.key == "POSTGRES_HOST")
        assert _is_managed_field_present(host_field, "127.0.0.1") is True

    def test_postgres_port_rejects_invalid_value_via_its_validator(self):
        port_field = next(f for f in SYSTEM_MANAGED_FIELDS if f.key == "POSTGRES_PORT")
        assert _is_managed_field_present(port_field, "not-a-port") is False
        assert _is_managed_field_present(port_field, "5432") is True

    def test_every_system_managed_field_with_a_value_is_detected(self):
        """Every field install.sh is documented to configure must be
        detected as present when it genuinely holds a valid value -- this
        is what drives blanking it in the wizard form."""
        sample_values = {
            "SECRET_KEY": "b" * 64,
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "eas_station",
            "POSTGRES_USER": "eas_station",
            "POSTGRES_PASSWORD": "hunter2",
        }
        for field in SYSTEM_MANAGED_FIELDS:
            assert field.key in sample_values, f"Add a sample value for {field.key}"
            assert _is_managed_field_present(field, sample_values[field.key]) is True


class TestWizardSectionsMetadata:
    """The redesigned setup_wizard.html renders WIZARD_SECTIONS as an
    accordion (title, description, per-section field count); every section
    must carry that metadata non-empty."""

    def test_every_section_has_a_title_and_description(self):
        for section in WIZARD_SECTIONS:
            assert section.title.strip()
            assert section.description.strip()

    def test_every_section_has_at_least_one_field(self):
        for section in WIZARD_SECTIONS:
            assert len(section.fields) > 0

    def test_core_section_is_first(self):
        """Core (system-managed) settings must stay first so its fields are
        collected before any user-facing section in the rendered form."""
        assert WIZARD_SECTIONS[0].name == "core"

    def test_location_and_eas_sections_exist(self):
        """The template expands these two sections by default (the ones a
        fresh install genuinely needs); they must exist under these names."""
        names = {section.name for section in WIZARD_SECTIONS}
        assert "location" in names
        assert "eas" in names


class TestSetupWizardTemplateStructure:
    """Guards against silently reverting the onboarding redesign back to a
    single flat, unsectioned field wall."""

    def _template_source(self) -> str:
        from pathlib import Path
        path = Path(__file__).parent.parent / "templates" / "setup_wizard.html"
        return path.read_text(encoding="utf-8")

    def test_iterates_sections_not_the_flat_field_list(self):
        html = self._template_source()
        assert "{% for section in env_sections %}" in html
        assert "{% for field in section.fields %}" in html
        # The old flat loop must be gone, not just supplemented.
        assert "{% for field in env_fields %}" not in html

    def test_renders_accordion_with_section_metadata(self):
        html = self._template_source()
        assert 'class="accordion' in html
        assert "{{ section.title }}" in html
        assert "{{ section.description }}" in html

    def test_uses_generalized_managed_present_not_secret_only(self):
        html = self._template_source()
        assert "managed_present" in html
