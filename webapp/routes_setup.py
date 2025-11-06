"""Public routes for the web-based setup wizard."""

from __future__ import annotations

from flask import flash, g, jsonify, redirect, render_template, request, url_for

from app_utils.setup_wizard import (
    PLACEHOLDER_SECRET_VALUES,
    WIZARD_FIELDS,
    SetupValidationError,
    clean_submission,
    format_led_lines_for_display,
    generate_secret_key,
    load_wizard_state,
    write_env_file,
)
from flask import session
import secrets


SETUP_REASON_MESSAGES = {
    "secret-key": "SECRET_KEY is missing or using a placeholder value.",
    "database": "The application could not connect to the configured database.",
}

CSRF_SESSION_KEY = '_csrf_token'


def _ensure_csrf_token():
    """Ensure a CSRF token exists in the session and return it."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


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
        current_user = getattr(g, "current_user", None)
        is_authenticated = bool(current_user and current_user.is_authenticated)

        if not setup_active and not is_authenticated:
            next_url = request.full_path if request.query_string else request.path
            if request.method == "GET":
                flash("Please sign in to access the setup wizard.")
                return redirect(url_for("login", next=next_url))
            return jsonify({"error": "Authentication required"}), 401

        try:
            state = load_wizard_state()
        except FileNotFoundError as exc:
            flash(str(exc))
            csrf_token = _ensure_csrf_token()
            return render_template(
                "setup_wizard.html",
                env_fields=WIZARD_FIELDS,
                form_data={},
                errors={},
                env_exists=False,
                setup_reasons=reason_messages,
                setup_active=setup_active,
                secret_present=False,
                csrf_token=csrf_token,
            )

        defaults = {
            key: (value or "")
            for key, value in state.defaults.items()
        }
        existing_secret = state.current_values.get("SECRET_KEY", "").strip()
        has_valid_secret = (
            bool(existing_secret)
            and existing_secret not in PLACEHOLDER_SECRET_VALUES
            and len(existing_secret) >= 32
        )
        if has_valid_secret:
            defaults["SECRET_KEY"] = ""
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

            if has_valid_secret and not submitted["SECRET_KEY"].strip():
                submitted["SECRET_KEY"] = existing_secret

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
                    # Provide detailed instructions based on deployment type
                    flash(
                        "Configuration saved successfully! "
                        "⚠️ IMPORTANT: For Portainer deployments, changes persist on container RESTART "
                        "but are lost on REDEPLOY. For permanent config, copy your values to Portainer's "
                        "Environment Variables section.",
                        "success"
                    )
                    # Store the cleaned values in session so we can show them on the success page
                    session['_setup_saved_config'] = cleaned
                    return redirect(url_for("setup_success"))

        csrf_token = _ensure_csrf_token()
        return render_template(
            "setup_wizard.html",
            env_fields=WIZARD_FIELDS,
            form_data=form_data,
            errors=errors,
            env_exists=state.env_exists,
            setup_reasons=reason_messages,
            setup_active=setup_active,
            secret_present=has_valid_secret,
            csrf_token=csrf_token,
        )

    @app.route("/setup/generate-secret", methods=["POST"])
    def setup_generate_secret():
        setup_active = app.config.get("SETUP_MODE", False)
        current_user = getattr(g, "current_user", None)
        is_authenticated = bool(current_user and current_user.is_authenticated)

        if not setup_active and not is_authenticated:
            return jsonify({"error": "Authentication required"}), 401

        token = generate_secret_key()
        return jsonify({"secret_key": token})

    @app.route("/setup/success")
    def setup_success():
        """Show configuration success page with export instructions."""
        setup_active = app.config.get("SETUP_MODE", False)
        current_user = getattr(g, "current_user", None)
        is_authenticated = bool(current_user and current_user.is_authenticated)

        if not setup_active and not is_authenticated:
            return redirect(url_for("login"))

        # Get the saved config from session
        saved_config = session.pop('_setup_saved_config', {})
        if not saved_config:
            flash("No configuration to display. Please complete the setup wizard first.")
            return redirect(url_for("setup_wizard"))

        # Filter out empty values and format for Portainer
        portainer_env_vars = []
        for key, value in sorted(saved_config.items()):
            if value and value.strip():
                # Mask sensitive values
                display_value = value
                if key in ('SECRET_KEY', 'POSTGRES_PASSWORD', 'AZURE_OPENAI_KEY'):
                    display_value = value[:8] + '...' + value[-4:] if len(value) > 12 else '***'
                portainer_env_vars.append({
                    'key': key,
                    'value': value,
                    'display_value': display_value,
                    'is_sensitive': key in ('SECRET_KEY', 'POSTGRES_PASSWORD', 'AZURE_OPENAI_KEY')
                })

        return render_template(
            "setup_success.html",
            env_vars=portainer_env_vars,
        )

    @app.route("/setup/derive-zone-codes", methods=["POST"])
    def setup_derive_zone_codes():
        """Derive NWS zone codes from FIPS county codes."""
        setup_active = app.config.get("SETUP_MODE", False)
        current_user = getattr(g, "current_user", None)
        is_authenticated = bool(current_user and current_user.is_authenticated)

        if not setup_active and not is_authenticated:
            return jsonify({"error": "Authentication required"}), 401

        try:
            from app_core.location import _derive_county_zone_codes_from_fips
            from app_utils.zones import load_zone_lookup

            data = request.get_json() or {}
            fips_codes_str = data.get("fips_codes", "")

            # Parse comma-separated FIPS codes
            fips_codes = [code.strip() for code in fips_codes_str.split(",") if code.strip()]

            if not fips_codes:
                return jsonify({"zone_codes": []})

            # Load zone lookup
            zone_lookup = load_zone_lookup()

            # Derive zone codes
            derived = _derive_county_zone_codes_from_fips(fips_codes, zone_lookup)

            return jsonify({"zone_codes": derived})
        except Exception as exc:
            setup_logger.exception("Failed to derive zone codes")
            return jsonify({"error": str(exc)}), 500


__all__ = ["register"]
