"""Interactive CLI wrapper around the setup wizard helpers."""

from __future__ import annotations

import sys
from typing import Dict

from app_utils.setup_wizard import (
    WIZARD_FIELDS,
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
    for field in WIZARD_FIELDS:
        default_value = defaults.get(field.key, "")
        if field.key == "SECRET_KEY" and (not default_value or "replace" in default_value.lower()):
            if _prompt_yes_no("Generate a random Flask SECRET_KEY?", True):
                default_value = generate_secret_key()
                print("Generated SECRET_KEY; you may accept or overwrite it.")
        prompt_message = f"{field.label}"
        answers[field.key] = _prompt(prompt_message, default_value)
    return answers


def main() -> int:
    try:
        state = load_wizard_state()
    except FileNotFoundError as exc:
        print(exc)
        return 1

    print("EAS Station setup wizard (CLI)")
    print("Type 'exit' at any prompt to cancel.\n")

    defaults = state.defaults
    answers = _collect_answers(defaults)

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
