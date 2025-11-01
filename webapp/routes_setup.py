"""Public routes for the web-based setup wizard."""

from __future__ import annotations

from flask import flash, jsonify, redirect, render_template, request, url_for

from app_utils.setup_wizard import (
    WIZARD_FIELDS,
    SetupValidationError,
    clean_submission,
    format_led_lines_for_display,
    generate_secret_key,
    load_wizard_state,
    write_env_file,
)


SETUP_REASON_MESSAGES = {
    "secret-key": "SECRET_KEY is missing or using a placeholder value.",
    "database": "The application could not connect to the configured database.",
}


def register(app, logger):
    """Register setup wizard routes on the Flask app."""

    setup_logger = logger.getChild("setup")

    @app.route("/setup", methods=["GET", "POST"])
    def setup_wizard():
        setup_reasons = app.config.get("SETUP_MODE_REASONS", ())
        reason_messages = [
            SETUP_REASON_MESSAGES.get(reason, reason.replace('-', ' '))
            for reason in setup_reasons
        ]
        setup_active = app.config.get("SETUP_MODE", False)

        try:
            state = load_wizard_state()
        except FileNotFoundError as exc:
            flash(str(exc))
            return render_template(
                "setup_wizard.html",
                env_fields=WIZARD_FIELDS,
                form_data={},
                errors={},
                env_exists=False,
                setup_reasons=reason_messages,
                setup_active=setup_active,
            )

        defaults = {
            key: (value or "")
            for key, value in state.defaults.items()
        }
        defaults["DEFAULT_LED_LINES"] = format_led_lines_for_display(
            defaults.get("DEFAULT_LED_LINES", "")
        )

        errors = {}
        form_data = dict(defaults)

        if request.method == "POST":
            form_data = {
                field.key: request.form.get(field.key, "")
                for field in WIZARD_FIELDS
            }
            submitted = dict(form_data)
            if "DEFAULT_LED_LINES" in submitted:
                submitted["DEFAULT_LED_LINES"] = submitted["DEFAULT_LED_LINES"].replace("\r", "")

            try:
                cleaned = clean_submission(submitted)
            except SetupValidationError as exc:
                errors = exc.errors
                flash("Please correct the highlighted issues and try again.")
            else:
                create_backup = request.form.get("create_backup", "yes") == "yes"
                try:
                    write_env_file(state=state, updates=cleaned, create_backup=create_backup)
                except Exception as exc:  # pragma: no cover - unexpected filesystem errors
                    setup_logger.exception("Failed to write .env from setup wizard")
                    flash(f"Unable to update configuration: {exc}")
                else:
                    flash("Configuration saved. Restart the stack to load the new settings.")
                    return redirect(url_for("setup_wizard"))

        return render_template(
            "setup_wizard.html",
            env_fields=WIZARD_FIELDS,
            form_data=form_data,
            errors=errors,
            env_exists=state.env_exists,
            setup_reasons=reason_messages,
            setup_active=setup_active,
        )

    @app.route("/setup/generate-secret", methods=["POST"])
    def setup_generate_secret():
        token = generate_secret_key()
        return jsonify({"secret_key": token})


__all__ = ["register"]
