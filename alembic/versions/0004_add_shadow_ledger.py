"""add shadow_ledger table — Replay Shadow Ledger (gold dataset) schema

Purely additive: one new table, no existing table altered. Nothing writes
to this table yet — see app/models/shadow_ledger.py docstring — this
migration only settles the schema shape ahead of that future work.

Revision ID: 0004_add_shadow_ledger
Revises: 0003_add_backtest_runs
Create Date: 2026-08-08

"""
from alembic import op
import sqlalchemy as sa

revision = "0004_add_shadow_ledger"
down_revision = "0003_add_backtest_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shadow_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signal_history.id"), nullable=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("asset_type", sa.String(length=10), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("rules_passed", sa.JSON(), nullable=False),
        sa.Column("market_regime", sa.String(length=20), nullable=True),
        sa.Column("entry_time", sa.DateTime(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("target_1", sa.Float(), nullable=False),
        sa.Column("target_2", sa.Float(), nullable=True),
        sa.Column("exit_time", sa.DateTime(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("exit_reason", sa.String(length=30), nullable=True),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.Column("pnl_pct", sa.Float(), nullable=True),
        sa.Column("holding_time_minutes", sa.Integer(), nullable=True),
        sa.Column("trend_score", sa.Float(), nullable=True),
        sa.Column("volume_score", sa.Float(), nullable=True),
        sa.Column("momentum_score", sa.Float(), nullable=True),
        sa.Column("vwap_score", sa.Float(), nullable=True),
        sa.Column("failure_reason", sa.String(length=50), nullable=True),
        sa.Column("screenshot_ref", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="OPEN"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_shadow_ledger_symbol", "shadow_ledger", ["symbol"])
    op.create_index("ix_shadow_ledger_tier", "shadow_ledger", ["tier"])
    op.create_index("ix_shadow_ledger_status", "shadow_ledger", ["status"])


def downgrade():
    op.drop_index("ix_shadow_ledger_status", table_name="shadow_ledger")
    op.drop_index("ix_shadow_ledger_tier", table_name="shadow_ledger")
    op.drop_index("ix_shadow_ledger_symbol", table_name="shadow_ledger")
    op.drop_table("shadow_ledger")
