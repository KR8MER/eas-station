"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Interactive CLI wrapper around the setup wizard helpers."""

from __future__ import annotations

import sys
from typing import Dict

from app_utils.setup_wizard import (
    WIZARD_FIELDS,
    WIZARD_SECTIONS,
    clean_submission,
    generate_secret_key,
    load_wizard_state,
    write_env_file,
)


class WizardAbort(RuntimeError):
    """Raised when the operator explicitly aborts the wizard."""


def _prompt(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        response = input(f"{message}{suffix}: ").strip()
        if not response and default:
            return default
        if response.lower() == "exit":
            raise WizardAbort("Operator aborted the wizard")
        if response:
            return response
        print("A value is required. Type 'exit' to cancel.")


def _prompt_yes_no(message: str, default: bool = True) -> bool:
    default_token = "Y/n" if default else "y/N"
    while True:
        response = input(f"{message} [{default_token}]: ").strip().lower()
        if not response:
            return default
        if response in {"y", "yes"}:
            return True
        if response in {"n", "no"}:
            return False
        if response == "exit":
            raise WizardAbort("Operator aborted the wizard")
        print("Please answer with 'y' or 'n'.")


def _collect_answers(defaults: Dict[str, str]) -> Dict[str, str]:
    answers: Dict[str, str] = {}

    # Process sections one at a time
    for section_idx, section in enumerate(WIZARD_SECTIONS, 1):
        print(f"\n{'='*70}")
        print(f"Section {section_idx}/{len(WIZARD_SECTIONS)}: {section.title}")
        print(f"{section.description}")
        print(f"{'='*70}\n")

        # Allow skipping optional sections
        if section.name != "core":
            if not _prompt_yes_no(f"Configure {section.title}?", default=True):
                print(f"Skipping {section.title} section.")
                print("Existing configuration values will be preserved.\n")
                # Preserve existing values for skipped section
                for field in section.fields:
                    if field.key in defaults:
                        answers[field.key] = defaults[field.key]
                continue

        # Collect answers for each field in the section
        for field in section.fields:
            default_value = defaults.get(field.key, "")

            # Special handling for SECRET_KEY generation
            if field.key == "SECRET_KEY" and (not default_value or "replace" in default_value.lower()):
                if _prompt_yes_no("Generate a random Flask SECRET_KEY?", True):
                    default_value = generate_secret_key()
                    print("Generated SECRET_KEY; you may accept or overwrite it.")

            # Show field description
            print(f"\n{field.description}")
            prompt_message = f"{field.label}"

            # Get user input
            user_input = _prompt(prompt_message, default_value) if field.required else _prompt_optional(prompt_message, default_value)
            answers[field.key] = user_input

    return answers


def _prompt_optional(message: str, default: str | None = None) -> str:
    """Prompt for optional value, allowing empty responses."""
    suffix = f" [{default}]" if default else " (optional, press Enter to skip)"
    response = input(f"{message}{suffix}: ").strip()
    if not response and default:
        return default
    if response.lower() == "exit":
        raise WizardAbort("Operator aborted the wizard")
    return response


def main() -> int:
    try:
        state = load_wizard_state()
    except FileNotFoundError as exc:
        print(exc)
        return 1

    print("\n" + "="*70)
    print("EAS Station Interactive Setup Wizard")
    print("="*70)
    print("\nThis wizard will guide you through configuring your EAS Station.")
    print("The configuration will be saved to .env in the project root.")
    print("\nTips:")
    print("  - Press Enter to accept default values shown in [brackets]")
    print("  - Type 'exit' at any prompt to cancel the wizard")
    print("  - Optional sections can be skipped and configured later")
    if state.env_exists:
        print("\nNote: Existing .env detected - defaults will be loaded from it.")
    print()

    defaults = state.defaults
    answers = _collect_answers(defaults)

    print("\n" + "="*70)
    print("Configuration Complete")
    print("="*70)

    try:
        cleaned = clean_submission(answers)
    except Exception as exc:  # pragma: no cover - CLI convenience
        print(f"Validation failed: {exc}")
        if hasattr(exc, "errors"):
            for key, message in exc.errors.items():
                print(f" - {key}: {message}")
        return 1

    create_backup = _prompt_yes_no("Backup existing .env if present?", True)

    try:
        destination = write_env_file(state=state, updates=cleaned, create_backup=create_backup)
    except Exception as exc:  # pragma: no cover - CLI convenience
        print(f"Failed to write .env: {exc}")
        return 1

    if destination.name.startswith(".env.backup"):
        print(f"Backup created at {destination}")
        print("New configuration written to .env")
    else:
        print(f"Configuration written to {destination}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WizardAbort:
        print("Setup wizard cancelled.")
        raise SystemExit(1)
