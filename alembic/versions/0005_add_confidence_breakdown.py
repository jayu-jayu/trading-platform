"""add confidence score breakdown + market regime detail columns to signal_history — Phase 2

Purely additive: 6 new nullable columns on an existing table. No default
required, no existing row touched, no other table altered.

Revision ID: 0005_add_confidence_breakdown
Revises: 0004_add_shadow_ledger
Create Date: 2026-08-09

"""
from alembic import op
import sqlalchemy as sa

revision = "0005_add_confidence_breakdown"
down_revision = "0004_add_shadow_ledger"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("signal_history", sa.Column("trend_score", sa.Float(), nullable=True))
    op.add_column("signal_history", sa.Column("volume_score", sa.Float(), nullable=True))
    op.add_column("signal_history", sa.Column("momentum_score", sa.Float(), nullable=True))
    op.add_column("signal_history", sa.Column("vwap_score", sa.Float(), nullable=True))
    op.add_column("signal_history", sa.Column("market_score", sa.Float(), nullable=True))
    op.add_column("signal_history", sa.Column("market_regime_detail", sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column("signal_history", "market_regime_detail")
    op.drop_column("signal_history", "market_score")
    op.drop_column("signal_history", "vwap_score")
    op.drop_column("signal_history", "momentum_score")
    op.drop_column("signal_history", "volume_score")
    op.drop_column("signal_history", "trend_score")
