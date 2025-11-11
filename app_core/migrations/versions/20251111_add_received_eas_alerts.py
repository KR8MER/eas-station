"""Add received_eas_alerts table to track monitored alerts

Revision ID: 20251111_add_received_eas_alerts
Revises: 20251107_merge_radio_and_audio
Create Date: 2025-11-11

This migration adds the received_eas_alerts table to track EAS alerts
received from audio monitoring sources, including:
- Reception details (source, timestamp)
- SAME header data (event, originator, FIPS codes)
- Forwarding decision (forwarded, ignored, error)
- Link to generated EASMessage if forwarded
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251111_add_received_eas_alerts'
down_revision = '20251107_merge_radio_and_audio'
branch_labels = None
depends_on = None


def upgrade():
    """Create received_eas_alerts table."""
    op.create_table(
        'received_eas_alerts',
        sa.Column('id', sa.Integer(), nullable=False),

        # Reception details
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source_name', sa.String(length=100), nullable=False),

        # SAME header data
        sa.Column('raw_same_header', sa.Text(), nullable=True),
        sa.Column('event_code', sa.String(length=8), nullable=True),
        sa.Column('event_name', sa.String(length=255), nullable=True),
        sa.Column('originator_code', sa.String(length=8), nullable=True),
        sa.Column('originator_name', sa.String(length=100), nullable=True),
        sa.Column('fips_codes', sa.JSON(), nullable=True),
        sa.Column('issue_datetime', sa.DateTime(timezone=True), nullable=True),
        sa.Column('purge_datetime', sa.DateTime(timezone=True), nullable=True),
        sa.Column('callsign', sa.String(length=16), nullable=True),

        # Forwarding decision
        sa.Column('forwarding_decision', sa.String(length=20), nullable=False),
        sa.Column('forwarding_reason', sa.Text(), nullable=True),
        sa.Column('matched_fips_codes', sa.JSON(), nullable=True),

        # Link to generated broadcast
        sa.Column('generated_message_id', sa.Integer(), nullable=True),
        sa.Column('forwarded_at', sa.DateTime(timezone=True), nullable=True),

        # Full alert data and quality metrics
        sa.Column('full_alert_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('decode_confidence', sa.Float(), nullable=True),

        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['generated_message_id'], ['eas_messages.id'], ),
    )

    # Create indexes for common queries
    op.create_index('ix_received_eas_alerts_received_at', 'received_eas_alerts', ['received_at'], unique=False)
    op.create_index('ix_received_eas_alerts_source_name', 'received_eas_alerts', ['source_name'], unique=False)
    op.create_index('ix_received_eas_alerts_event_code', 'received_eas_alerts', ['event_code'], unique=False)
    op.create_index('ix_received_eas_alerts_forwarding_decision', 'received_eas_alerts', ['forwarding_decision'], unique=False)


def downgrade():
    """Drop received_eas_alerts table."""
    op.drop_index('ix_received_eas_alerts_forwarding_decision', table_name='received_eas_alerts')
    op.drop_index('ix_received_eas_alerts_event_code', table_name='received_eas_alerts')
    op.drop_index('ix_received_eas_alerts_source_name', table_name='received_eas_alerts')
    op.drop_index('ix_received_eas_alerts_received_at', table_name='received_eas_alerts')
    op.drop_table('received_eas_alerts')
