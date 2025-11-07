"""Public routes for the web-based setup wizard."""

from __future__ import annotations

from flask import flash, g, jsonify, redirect, render_template, request, send_file, url_for

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
from app_core.location import _derive_county_zone_codes_from_fips
from flask import session
import secrets
from datetime import datetime


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

            # Auto-populate zone codes from FIPS codes if zone codes are empty
            fips_codes_raw = submitted.get("EAS_MANUAL_FIPS_CODES", "").strip()
            zone_codes_raw = submitted.get("DEFAULT_ZONE_CODES", "").strip()

            if fips_codes_raw and not zone_codes_raw:
                try:
                    # Parse FIPS codes (comma-separated)
                    fips_list = [code.strip() for code in fips_codes_raw.split(",") if code.strip()]

                    # Derive zone codes from FIPS
                    derived_zones = _derive_county_zone_codes_from_fips(fips_list)

                    if derived_zones:
                        submitted["DEFAULT_ZONE_CODES"] = ",".join(derived_zones)
                        setup_logger.info(f"Auto-derived {len(derived_zones)} zone codes from {len(fips_list)} FIPS codes")
                except Exception as zone_exc:
                    setup_logger.warning(f"Failed to auto-derive zone codes from FIPS: {zone_exc}")

            try:
                cleaned = clean_submission(submitted)
            except SetupValidationError as exc:
                errors = exc.errors
                flash("Please correct the highlighted issues and try again.")
            else:
                create_backup = request.form.get("create_backup", "yes") == "yes"
                try:
                    from app_utils.setup_wizard import ENV_OUTPUT_PATH
                    import os

                    # Check BEFORE write
                    setup_logger.info("=== PRE-WRITE DIAGNOSTICS ===")
                    setup_logger.info(f"Current user: uid={os.getuid()}, gid={os.getgid()}")
                    setup_logger.info(f"ENV_OUTPUT_PATH: {ENV_OUTPUT_PATH}")
                    if ENV_OUTPUT_PATH.exists():
                        stat_before = ENV_OUTPUT_PATH.stat()
                        setup_logger.info(f"File exists - size: {stat_before.st_size}, perms: {oct(stat_before.st_mode)}, owner: uid={stat_before.st_uid}")
                        setup_logger.info(f"File is writable: {os.access(ENV_OUTPUT_PATH, os.W_OK)}")
                    else:
                        setup_logger.info("File does not exist yet")
                        parent_dir = ENV_OUTPUT_PATH.parent
                        setup_logger.info(f"Parent dir writable: {os.access(parent_dir, os.W_OK)}")

                    result_path = write_env_file(state=state, updates=cleaned, create_backup=create_backup)

                    # Check AFTER write
                    setup_logger.info("=== POST-WRITE DIAGNOSTICS ===")
                    setup_logger.info(f"Successfully wrote .env file to: {result_path}")
                    setup_logger.info(f".env file exists: {result_path.exists()}")
                    if result_path.exists():
                        stat_after = result_path.stat()
                        setup_logger.info(f".env file size: {stat_after.st_size} bytes")
                        setup_logger.info(f".env file permissions: {oct(stat_after.st_mode)}")
                        setup_logger.info(f".env file owner: uid={stat_after.st_uid}, gid={stat_after.st_gid}")

                        # Try to read back what we just wrote
                        try:
                            content_check = result_path.read_text(encoding='utf-8')
                            setup_logger.info(f".env file content length: {len(content_check)} chars")
                            if 'SECRET_KEY=' in content_check:
                                # Find the SECRET_KEY line to verify it's not empty
                                for line in content_check.split('\n'):
                                    if line.startswith('SECRET_KEY='):
                                        key_value = line.split('=', 1)[1] if '=' in line else ''
                                        setup_logger.info(f"✅ SECRET_KEY found, length: {len(key_value)}")
                                        break
                            else:
                                setup_logger.error("❌ SECRET_KEY NOT found in written file!")
                        except Exception as read_exc:
                            setup_logger.error(f"Failed to read back .env file: {read_exc}")

                except PermissionError as perm_exc:
                    setup_logger.exception("Permission denied writing .env file")
                    flash(f"Permission denied: Cannot write to .env file. File may be read-only or owned by different user. Error: {perm_exc}")
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

    @app.route("/setup/view-env")
    def setup_view_env():
        """View the current .env file contents for debugging."""
        setup_active = app.config.get("SETUP_MODE", False)
        current_user = getattr(g, "current_user", None)
        is_authenticated = bool(current_user and current_user.is_authenticated)

        if not setup_active and not is_authenticated:
            return redirect(url_for("login"))

        from app_utils.setup_wizard import ENV_OUTPUT_PATH
        import os

        env_info = {
            'path': str(ENV_OUTPUT_PATH),
            'absolute_path': str(ENV_OUTPUT_PATH.resolve()),
            'exists': ENV_OUTPUT_PATH.exists(),
            'is_file': ENV_OUTPUT_PATH.is_file() if ENV_OUTPUT_PATH.exists() else False,
            'is_dir': ENV_OUTPUT_PATH.is_dir() if ENV_OUTPUT_PATH.exists() else False,
            'container_id': os.environ.get('HOSTNAME', 'unknown'),
            'working_dir': os.getcwd(),
            'current_user': f"uid={os.getuid()}, gid={os.getgid()}",
        }

        if ENV_OUTPUT_PATH.exists():
            stat_info = ENV_OUTPUT_PATH.stat()
            env_info['size'] = stat_info.st_size
            env_info['permissions'] = oct(stat_info.st_mode)
            env_info['modified'] = stat_info.st_mtime
            env_info['owner'] = f"uid={stat_info.st_uid}, gid={stat_info.st_gid}"
            env_info['writable'] = os.access(ENV_OUTPUT_PATH, os.W_OK)

            if ENV_OUTPUT_PATH.is_file():
                try:
                    env_info['content'] = ENV_OUTPUT_PATH.read_text(encoding='utf-8')
                except Exception as e:
                    env_info['content'] = f"Error reading file: {e}"
            else:
                env_info['content'] = "(path is a directory, not a file)"
        else:
            env_info['content'] = "(file does not exist)"
            # Check parent directory permissions
            parent_dir = ENV_OUTPUT_PATH.parent
            env_info['parent_dir'] = str(parent_dir)
            env_info['parent_writable'] = os.access(parent_dir, os.W_OK)

        return render_template(
            "setup_env_viewer.html",
            env_info=env_info,
        )

    @app.route("/setup/download-env")
    def setup_download_env():
        """Download the current .env file as a backup."""
        setup_active = app.config.get("SETUP_MODE", False)
        current_user = getattr(g, "current_user", None)
        is_authenticated = bool(current_user and current_user.is_authenticated)

        if not setup_active and not is_authenticated:
            return redirect(url_for("login"))

        from app_utils.setup_wizard import ENV_OUTPUT_PATH

        if not ENV_OUTPUT_PATH.exists():
            flash("No .env file exists to download.")
            return redirect(url_for("setup_wizard"))

        # Create a timestamped filename for the download
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        download_name = f"eas-station-backup-{timestamp}.env"

        return send_file(
            ENV_OUTPUT_PATH,
            as_attachment=True,
            download_name=download_name,
            mimetype='text/plain'
        )

    @app.route("/setup/upload-env", methods=["POST"])
    def setup_upload_env():
        """Upload and restore a .env file from backup."""
        setup_active = app.config.get("SETUP_MODE", False)
        current_user = getattr(g, "current_user", None)
        is_authenticated = bool(current_user and current_user.is_authenticated)

        if not setup_active and not is_authenticated:
            return jsonify({"error": "Authentication required"}), 401

        if 'env_file' not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files['env_file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400

        if not file.filename.endswith('.env'):
            return jsonify({"error": "File must have .env extension"}), 400

        try:
            from app_utils.setup_wizard import ENV_OUTPUT_PATH, create_env_backup

            # Create backup of existing file if it exists
            if ENV_OUTPUT_PATH.exists():
                backup_path = create_env_backup()
                setup_logger.info(f"Created backup before restore: {backup_path}")

            # Read and validate the uploaded content
            content = file.read().decode('utf-8')

            # Basic validation - check for SECRET_KEY
            if 'SECRET_KEY=' not in content:
                return jsonify({"error": "Invalid .env file: missing SECRET_KEY"}), 400

            # Write the uploaded content
            ENV_OUTPUT_PATH.write_text(content, encoding='utf-8')
            setup_logger.info(f"Restored .env file from upload: {file.filename}")

            return jsonify({
                "success": True,
                "message": "Configuration restored successfully. Please restart the container for changes to take effect."
            })

        except Exception as exc:
            setup_logger.exception("Failed to restore .env file from upload")
            return jsonify({"error": f"Failed to restore file: {str(exc)}"}), 500

    @app.route("/setup/lookup-county-fips", methods=["POST"])
    def setup_lookup_county_fips():
        """Look up FIPS codes for counties by state and county name."""
        setup_active = app.config.get("SETUP_MODE", False)
        current_user = getattr(g, "current_user", None)
        is_authenticated = bool(current_user and current_user.is_authenticated)

        if not setup_active and not is_authenticated:
            return jsonify({"error": "Authentication required"}), 401

        try:
            from app_utils.fips_codes import get_us_state_county_tree

            data = request.get_json() or {}
            state_code = data.get("state_code", "").strip().upper()
            county_query = data.get("county_name", "").strip().lower()

            if not state_code:
                return jsonify({"error": "State code is required"}), 400

            # Get the state/county tree
            state_tree = get_us_state_county_tree()

            # Find the state
            state_data = None
            for state in state_tree:
                if state.get("abbr", "").upper() == state_code:
                    state_data = state
                    break

            if not state_data:
                return jsonify({"error": f"State {state_code} not found"}), 404

            # If no county query, return all counties for the state
            if not county_query:
                counties = [
                    {
                        "name": county.get("name", ""),
                        "fips": county.get("same", "")
                    }
                    for county in state_data.get("counties", [])
                ]
                return jsonify({"counties": counties})

            # Search for matching counties
            matching_counties = []
            for county in state_data.get("counties", []):
                county_name = county.get("name", "").lower()
                if county_query in county_name:
                    matching_counties.append({
                        "name": county.get("name", ""),
                        "fips": county.get("same", "")
                    })

            return jsonify({"counties": matching_counties})

        except Exception as exc:
            setup_logger.exception("Failed to lookup county FIPS codes")
            return jsonify({"error": str(exc)}), 500

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
