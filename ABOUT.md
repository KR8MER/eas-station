# ℹ️ About the NOAA CAP Emergency Alert System

The NOAA CAP Emergency Alert System (EAS) is a Flask-powered operations hub that ingests National Oceanic and Atmospheric Administration (NOAA) Common Alerting Protocol (CAP) products, evaluates their geographic impact, and prepares on-air messaging for emergency communications teams. The project is maintained by amateur radio operators supporting Putnam County, Ohio, and ships with tooling for monitoring, manual activations, and LED signage integrations.

## Mission and Scope
- **Primary Goal:** Deliver timely situational awareness to emergency communications volunteers by automating NOAA alert ingestion, enrichment, and dissemination.
- **Deployment Model:** Container-first architecture designed for on-premise or field deployments with an external PostgreSQL/PostGIS database service.
- **Operational Focus:** Supports automatic alert polling, manual CAP overrides, local SAME audio generation, and optional LED signage broadcast.

## Core Services
| Component | Description |
|-----------|-------------|
| **Flask Web Application** | Provides the administrative dashboard, REST APIs, and user authentication for managing alerts and boundaries. |
| **Background Poller** | Continuously retrieves CAP alerts, updates the database, and queues notifications for review or broadcast. |
| **PostgreSQL + PostGIS** | Stores CAP products, SAME messages, and geographic boundaries with spatial indexing and geometry functions. |
| **EAS Audio Pipeline** | Generates SAME data bursts, synthesizes audio, and coordinates GPIO relay control for transmissions. |
| **LED Controller** | Manages Alpha Protocol LED signs for synchronized visual messaging alongside radio broadcasts. |

## Software Stack
The application combines open-source tooling and optional cloud integrations. Versions below match the pinned dependencies in `requirements.txt` unless noted otherwise.

### Application Framework
- Python 3.11 runtime
- Flask 2.3.3 web framework
- Werkzeug 2.3.7 WSGI utilities
- Flask-SQLAlchemy 3.0.5 ORM integration
- SQLAlchemy 2.0.21 ORM core
- Gunicorn 21.2.0 production WSGI server

### Data and Spatial Layer
- PostgreSQL 15 with the PostGIS extension (external service)
- GeoAlchemy2 0.14.1 for spatial ORM bindings
- psycopg2-binary 2.9.7 PostgreSQL driver

### System and Utilities
- requests 2.31.0 for CAP feed retrieval
- pytz 2023.3 timezone utilities
- psutil 5.9.5 system health metrics
- python-dotenv 1.0.0 configuration loading

### Front-End Tooling
- Bootstrap 5 UI framework
- Font Awesome iconography
- Highcharts visualization library

### Optional Integrations
- Azure Cognitive Services Speech SDK 1.38.0 (optional AI narration)
- Docker Engine 24+ and Docker Compose V2 for container orchestration

## Governance and Support
- **Issue Tracking:** Use GitHub issues for bug reports and feature requests.
- **Documentation Updates:** User-facing changes must update the README, HELP, and CHANGELOG entries.
- **Environment Variables:** Any new variables must be mirrored in `.env.example` per contributor guidelines.

For setup instructions, operational tips, and troubleshooting guidance, refer to the dedicated [HELP documentation](HELP.md).
