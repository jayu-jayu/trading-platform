"""add market_score column to shadow_ledger — completes the 5-part confidence breakdown

The shadow_ledger schema (migration 0004) captured 4 of the 5 confidence
sub-scores when it was written, before the Market sub-score existed
(added in Phase 2, migration 0005, on signal_history only). This closes
that gap before the Phase 4 writer starts populating rows, so every
shadow ledger entry captures the full breakdown from day one instead of
being permanently missing one field for anything written before a future
fix. Purely additive: one new nullable column, no existing row touched.

Revision ID: 0007_add_shadow_ledger_market_score
Revises: 0006_add_phase3_fields
Create Date: 2026-08-11

"""
from alembic import op
import sqlalchemy as sa

revision = "0007_add_shadow_ledger_market_score"
down_revision = "0006_add_phase3_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("shadow_ledger", sa.Column("market_score", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("shadow_ledger", "market_score")
