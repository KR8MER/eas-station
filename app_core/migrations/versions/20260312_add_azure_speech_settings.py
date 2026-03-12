"""Add Azure Cognitive Services Speech fields to tts_settings

Revision ID: 20260312_add_azure_speech_settings
Revises: 20260224_add_stream_url_to_metadata_log
Create Date: 2026-03-12 16:36:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260312_add_azure_speech_settings'
down_revision = '20260224_add_stream_url_to_metadata_log'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tts_settings', sa.Column('azure_speech_key', sa.String(length=500), nullable=True))
    op.add_column('tts_settings', sa.Column('azure_speech_region', sa.String(length=100), nullable=True))
    op.add_column('tts_settings', sa.Column('azure_speech_voice', sa.String(length=100), nullable=False, server_default='en-US-AriaNeural'))
    op.add_column('tts_settings', sa.Column('azure_speech_sample_rate', sa.Integer(), nullable=False, server_default='24000'))


def downgrade():
    op.drop_column('tts_settings', 'azure_speech_sample_rate')
    op.drop_column('tts_settings', 'azure_speech_voice')
    op.drop_column('tts_settings', 'azure_speech_region')
    op.drop_column('tts_settings', 'azure_speech_key')
