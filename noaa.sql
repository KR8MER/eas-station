-- NOAA CAP Alerts and GIS Boundary Mapping System
-- PostgreSQL + PostGIS Database Schema

-- Create boundaries table for static district boundaries
CREATE TABLE boundaries (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL, -- Fire, EMS, Electric, Township, Villages, Telephone, School, County
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add PostGIS geometry column for boundaries (MULTIPOLYGON, SRID 4326)
SELECT AddGeometryColumn('boundaries', 'geom', 4326, 'MULTIPOLYGON', 2);

-- Create spatial index for boundaries
CREATE INDEX idx_boundaries_geom ON boundaries USING GIST(geom);
CREATE INDEX idx_boundaries_type ON boundaries(type);

-- Create CAP alerts table
CREATE TABLE cap_alerts (
    id SERIAL PRIMARY KEY,
    identifier VARCHAR(255) UNIQUE NOT NULL,
    sent TIMESTAMP NOT NULL,
    expires TIMESTAMP,
    status VARCHAR(50) NOT NULL, -- Actual, Exercise, System, Test, Draft
    message_type VARCHAR(50) NOT NULL, -- Alert, Update, Cancel, Ack, Error
    scope VARCHAR(50) NOT NULL, -- Public, Restricted, Private
    category VARCHAR(50), -- Geo, Met, Safety, Security, Rescue, Fire, Health, Env, Transport, Infra, CBRNE, Other
    event VARCHAR(255) NOT NULL,
    urgency VARCHAR(50), -- Immediate, Expected, Future, Past, Unknown
    severity VARCHAR(50), -- Extreme, Severe, Moderate, Minor, Unknown
    certainty VARCHAR(50), -- Observed, Likely, Possible, Unlikely, Unknown
    area_desc TEXT,
    headline TEXT,
    description TEXT,
    instruction TEXT,
    raw_json JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add PostGIS geometry column for CAP alerts (POLYGON, SRID 4326)
SELECT AddGeometryColumn('cap_alerts', 'geom', 4326, 'POLYGON', 2);

-- Create spatial index for CAP alerts
CREATE INDEX idx_cap_alerts_geom ON cap_alerts USING GIST(geom);
CREATE INDEX idx_cap_alerts_identifier ON cap_alerts(identifier);
CREATE INDEX idx_cap_alerts_sent ON cap_alerts(sent);
CREATE INDEX idx_cap_alerts_expires ON cap_alerts(expires);
CREATE INDEX idx_cap_alerts_status ON cap_alerts(status);
CREATE INDEX idx_cap_alerts_event ON cap_alerts(event);

-- Create system log table
CREATE TABLE system_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    level VARCHAR(20) NOT NULL, -- DEBUG, INFO, WARNING, ERROR, CRITICAL
    message TEXT NOT NULL,
    module VARCHAR(100), -- Which part of system generated the log
    details JSONB
);

CREATE INDEX idx_system_log_timestamp ON system_log(timestamp);
CREATE INDEX idx_system_log_level ON system_log(level);

-- Create poll history table
CREATE TABLE poll_history (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL, -- SUCCESS, ERROR, TIMEOUT
    alerts_fetched INTEGER DEFAULT 0,
    alerts_new INTEGER DEFAULT 0,
    alerts_updated INTEGER DEFAULT 0,
    execution_time_ms INTEGER,
    error_message TEXT
);

CREATE INDEX idx_poll_history_timestamp ON poll_history(timestamp);

-- Create LED message history table to mirror application models
CREATE TABLE IF NOT EXISTS led_messages (
    id SERIAL PRIMARY KEY,
    message_type VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    priority INTEGER DEFAULT 2,
    color VARCHAR(20),
    font_size VARCHAR(20),
    effect VARCHAR(20),
    speed VARCHAR(20),
    display_time INTEGER,
    scheduled_time TIMESTAMP WITH TIME ZONE,
    sent_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,
    alert_id INTEGER REFERENCES cap_alerts(id),
    repeat_interval INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_led_messages_created_at ON led_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_led_messages_active ON led_messages(is_active);

-- Create intersections table to log alert-boundary overlaps
CREATE TABLE intersections (
    id SERIAL PRIMARY KEY,
    cap_alert_id INTEGER REFERENCES cap_alerts(id) ON DELETE CASCADE,
    boundary_id INTEGER REFERENCES boundaries(id) ON DELETE CASCADE,
    intersection_area FLOAT, -- Area of intersection in square meters
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_intersections_cap_alert ON intersections(cap_alert_id);
CREATE INDEX idx_intersections_boundary ON intersections(boundary_id);

-- Create notifications table for email/SMS alerts
CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    cap_alert_id INTEGER REFERENCES cap_alerts(id) ON DELETE CASCADE,
    boundary_id INTEGER REFERENCES boundaries(id) ON DELETE CASCADE,
    notification_type VARCHAR(20) NOT NULL, -- EMAIL, SMS, PUSH
    recipient VARCHAR(255) NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'PENDING' -- PENDING, SENT, FAILED
);

CREATE INDEX idx_notifications_cap_alert ON notifications(cap_alert_id);
CREATE INDEX idx_notifications_boundary ON notifications(boundary_id);

-- Create LED sign status table used by the dashboard and background pollers
CREATE TABLE IF NOT EXISTS led_sign_status (
    id SERIAL PRIMARY KEY,
    sign_ip VARCHAR(15) NOT NULL,
    brightness_level INTEGER DEFAULT 10,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    last_update TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_connected BOOLEAN DEFAULT FALSE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_led_sign_status_ip ON led_sign_status(sign_ip);

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for updated_at
CREATE TRIGGER update_boundaries_updated_at BEFORE UPDATE ON boundaries
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_cap_alerts_updated_at BEFORE UPDATE ON cap_alerts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create view for active alerts (not expired)
CREATE VIEW active_alerts AS
SELECT * FROM cap_alerts
WHERE expires IS NULL OR expires > CURRENT_TIMESTAMP;

-- Create view for boundary statistics
CREATE VIEW boundary_stats AS
SELECT
    type,
    COUNT(*) as count,
    MIN(created_at) as earliest_created,
    MAX(updated_at) as latest_updated
FROM boundaries
GROUP BY type;

-- Grant permissions to noaa_user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO noaa_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO noaa_user;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO noaa_user;