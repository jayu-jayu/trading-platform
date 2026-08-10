"""add MTF confirmation + sector relative strength columns to signal_history — Phase 3

Purely additive: 2 new nullable columns on an existing table. No default
required, no existing row touched, no other table altered.

Revision ID: 0006_add_phase3_fields
Revises: 0005_add_confidence_breakdown
Create Date: 2026-08-10

"""
from alembic import op
import sqlalchemy as sa

revision = "0006_add_phase3_fields"
down_revision = "0005_add_confidence_breakdown"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("signal_history", sa.Column("mtf_confirmed", sa.Boolean(), nullable=True))
    op.add_column("signal_history", sa.Column("sector_relative_strength_pct", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("signal_history", "sector_relative_strength_pct")
    op.drop_column("signal_history", "mtf_confirmed")
