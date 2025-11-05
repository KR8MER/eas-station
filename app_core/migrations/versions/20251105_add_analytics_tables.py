"""Add analytics tables for trend analysis and anomaly detection.

Revision ID: 20251105_add_analytics_tables
Revises: 20251105_add_rbac_and_mfa
Create Date: 2025-11-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


revision = "20251105_add_analytics_tables"
down_revision = "20251105_add_rbac_and_mfa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create analytics tables for metrics, trends, and anomalies."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # ========================================================================
    # Create metric_snapshots table
    # ========================================================================
    if "metric_snapshots" not in inspector.get_table_names():
        op.create_table(
            "metric_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("metric_category", sa.String(length=50), nullable=False),
            sa.Column("metric_name", sa.String(length=100), nullable=False),
            sa.Column("snapshot_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("aggregation_period", sa.String(length=20), nullable=False),
            sa.Column("value", sa.Float(), nullable=False),
            sa.Column("min_value", sa.Float(), nullable=True),
            sa.Column("max_value", sa.Float(), nullable=True),
            sa.Column("avg_value", sa.Float(), nullable=True),
            sa.Column("stddev_value", sa.Float(), nullable=True),
            sa.Column("sample_count", sa.Integer(), nullable=True),
            sa.Column("entity_id", sa.String(length=100), nullable=True),
            sa.Column("entity_type", sa.String(length=50), nullable=True),
            sa.Column("metadata", JSONB, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

        # Create indexes
        op.create_index(
            "ix_metric_snapshots_metric_category",
            "metric_snapshots",
            ["metric_category"],
        )
        op.create_index(
            "ix_metric_snapshots_metric_name",
            "metric_snapshots",
            ["metric_name"],
        )
        op.create_index(
            "ix_metric_snapshots_snapshot_time",
            "metric_snapshots",
            ["snapshot_time"],
        )
        op.create_index(
            "ix_metric_snapshots_aggregation_period",
            "metric_snapshots",
            ["aggregation_period"],
        )
        op.create_index(
            "ix_metric_snapshots_entity_id",
            "metric_snapshots",
            ["entity_id"],
        )

        # Create composite indexes
        op.create_index(
            "idx_metric_snapshots_composite",
            "metric_snapshots",
            ["metric_category", "metric_name", "aggregation_period", "snapshot_time"],
        )
        op.create_index(
            "idx_metric_snapshots_entity",
            "metric_snapshots",
            ["entity_type", "entity_id", "metric_name", "snapshot_time"],
        )

    # ========================================================================
    # Create trend_records table
    # ========================================================================
    if "trend_records" not in inspector.get_table_names():
        op.create_table(
            "trend_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("metric_category", sa.String(length=50), nullable=False),
            sa.Column("metric_name", sa.String(length=100), nullable=False),
            sa.Column("analysis_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("window_days", sa.Integer(), nullable=False),
            sa.Column("entity_id", sa.String(length=100), nullable=True),
            sa.Column("entity_type", sa.String(length=50), nullable=True),
            sa.Column("trend_direction", sa.String(length=20), nullable=False),
            sa.Column("trend_strength", sa.String(length=20), nullable=True),
            sa.Column("slope", sa.Float(), nullable=True),
            sa.Column("intercept", sa.Float(), nullable=True),
            sa.Column("r_squared", sa.Float(), nullable=True),
            sa.Column("p_value", sa.Float(), nullable=True),
            sa.Column("data_points", sa.Integer(), nullable=False),
            sa.Column("mean_value", sa.Float(), nullable=True),
            sa.Column("median_value", sa.Float(), nullable=True),
            sa.Column("stddev_value", sa.Float(), nullable=True),
            sa.Column("min_value", sa.Float(), nullable=True),
            sa.Column("max_value", sa.Float(), nullable=True),
            sa.Column("absolute_change", sa.Float(), nullable=True),
            sa.Column("percent_change", sa.Float(), nullable=True),
            sa.Column("rate_per_day", sa.Float(), nullable=True),
            sa.Column("forecast_days_ahead", sa.Integer(), nullable=True),
            sa.Column("forecast_value", sa.Float(), nullable=True),
            sa.Column("forecast_confidence", sa.Float(), nullable=True),
            sa.Column("metadata", JSONB, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

        # Create indexes
        op.create_index(
            "ix_trend_records_metric_category",
            "trend_records",
            ["metric_category"],
        )
        op.create_index(
            "ix_trend_records_metric_name",
            "trend_records",
            ["metric_name"],
        )
        op.create_index(
            "ix_trend_records_analysis_time",
            "trend_records",
            ["analysis_time"],
        )
        op.create_index(
            "ix_trend_records_entity_id",
            "trend_records",
            ["entity_id"],
        )

        # Create composite indexes
        op.create_index(
            "idx_trend_records_composite",
            "trend_records",
            ["metric_category", "metric_name", "window_days", "analysis_time"],
        )
        op.create_index(
            "idx_trend_records_entity",
            "trend_records",
            ["entity_type", "entity_id", "metric_name", "analysis_time"],
        )

    # ========================================================================
    # Create anomaly_records table
    # ========================================================================
    if "anomaly_records" not in inspector.get_table_names():
        op.create_table(
            "anomaly_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("metric_category", sa.String(length=50), nullable=False),
            sa.Column("metric_name", sa.String(length=100), nullable=False),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("metric_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("entity_id", sa.String(length=100), nullable=True),
            sa.Column("entity_type", sa.String(length=50), nullable=True),
            sa.Column("anomaly_type", sa.String(length=50), nullable=False),
            sa.Column("severity", sa.String(length=20), nullable=False),
            sa.Column("observed_value", sa.Float(), nullable=False),
            sa.Column("expected_value", sa.Float(), nullable=True),
            sa.Column("expected_min", sa.Float(), nullable=True),
            sa.Column("expected_max", sa.Float(), nullable=True),
            sa.Column("deviation", sa.Float(), nullable=True),
            sa.Column("z_score", sa.Float(), nullable=True),
            sa.Column("percentile", sa.Float(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("baseline_window_days", sa.Integer(), nullable=True),
            sa.Column("baseline_mean", sa.Float(), nullable=True),
            sa.Column("baseline_stddev", sa.Float(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("acknowledged_by", sa.String(length=100), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("resolved_by", sa.String(length=100), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolution_notes", sa.Text(), nullable=True),
            sa.Column("false_positive", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("false_positive_reason", sa.Text(), nullable=True),
            sa.Column("metadata", JSONB, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
        )

        # Create indexes
        op.create_index(
            "ix_anomaly_records_metric_category",
            "anomaly_records",
            ["metric_category"],
        )
        op.create_index(
            "ix_anomaly_records_metric_name",
            "anomaly_records",
            ["metric_name"],
        )
        op.create_index(
            "ix_anomaly_records_detected_at",
            "anomaly_records",
            ["detected_at"],
        )
        op.create_index(
            "ix_anomaly_records_entity_id",
            "anomaly_records",
            ["entity_id"],
        )
        op.create_index(
            "ix_anomaly_records_anomaly_type",
            "anomaly_records",
            ["anomaly_type"],
        )
        op.create_index(
            "ix_anomaly_records_acknowledged",
            "anomaly_records",
            ["acknowledged"],
        )
        op.create_index(
            "ix_anomaly_records_resolved",
            "anomaly_records",
            ["resolved"],
        )

        # Create composite indexes
        op.create_index(
            "idx_anomaly_records_composite",
            "anomaly_records",
            ["metric_category", "metric_name", "detected_at"],
        )
        op.create_index(
            "idx_anomaly_records_entity",
            "anomaly_records",
            ["entity_type", "entity_id", "detected_at"],
        )
        op.create_index(
            "idx_anomaly_records_status",
            "anomaly_records",
            ["acknowledged", "resolved", "severity"],
        )


def downgrade() -> None:
    """Remove analytics tables."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Drop anomaly_records table
    if "anomaly_records" in inspector.get_table_names():
        op.drop_index("idx_anomaly_records_status", table_name="anomaly_records")
        op.drop_index("idx_anomaly_records_entity", table_name="anomaly_records")
        op.drop_index("idx_anomaly_records_composite", table_name="anomaly_records")
        op.drop_index("ix_anomaly_records_resolved", table_name="anomaly_records")
        op.drop_index("ix_anomaly_records_acknowledged", table_name="anomaly_records")
        op.drop_index("ix_anomaly_records_anomaly_type", table_name="anomaly_records")
        op.drop_index("ix_anomaly_records_entity_id", table_name="anomaly_records")
        op.drop_index("ix_anomaly_records_detected_at", table_name="anomaly_records")
        op.drop_index("ix_anomaly_records_metric_name", table_name="anomaly_records")
        op.drop_index("ix_anomaly_records_metric_category", table_name="anomaly_records")
        op.drop_table("anomaly_records")

    # Drop trend_records table
    if "trend_records" in inspector.get_table_names():
        op.drop_index("idx_trend_records_entity", table_name="trend_records")
        op.drop_index("idx_trend_records_composite", table_name="trend_records")
        op.drop_index("ix_trend_records_entity_id", table_name="trend_records")
        op.drop_index("ix_trend_records_analysis_time", table_name="trend_records")
        op.drop_index("ix_trend_records_metric_name", table_name="trend_records")
        op.drop_index("ix_trend_records_metric_category", table_name="trend_records")
        op.drop_table("trend_records")

    # Drop metric_snapshots table
    if "metric_snapshots" in inspector.get_table_names():
        op.drop_index("idx_metric_snapshots_entity", table_name="metric_snapshots")
        op.drop_index("idx_metric_snapshots_composite", table_name="metric_snapshots")
        op.drop_index("ix_metric_snapshots_entity_id", table_name="metric_snapshots")
        op.drop_index("ix_metric_snapshots_aggregation_period", table_name="metric_snapshots")
        op.drop_index("ix_metric_snapshots_snapshot_time", table_name="metric_snapshots")
        op.drop_index("ix_metric_snapshots_metric_name", table_name="metric_snapshots")
        op.drop_index("ix_metric_snapshots_metric_category", table_name="metric_snapshots")
        op.drop_table("metric_snapshots")
