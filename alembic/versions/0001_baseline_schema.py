"""baseline schema — matches the current live Render deployment exactly

This migration exists so a BRAND NEW deployment can run `alembic upgrade
head` and get the complete schema from scratch. If you're upgrading an
ALREADY-DEPLOYED database (tables already exist), do NOT run this — run
`alembic stamp head` instead to mark it as already applied without
executing any DDL. See README for the exact commands.

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-08-07

"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "portfolio",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("virtual_capital", sa.Float(), nullable=False, server_default="500000.0"),
        sa.Column("available_capital", sa.Float(), nullable=False, server_default="500000.0"),
        sa.Column("total_realized_pnl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winning_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "signal_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("asset_type", sa.String(length=10), nullable=False, server_default="STOCK"),
        sa.Column("signal_type", sa.String(length=10), nullable=False, server_default="BUY"),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("atr_value", sa.Float(), nullable=False),
        sa.Column("rsi_value", sa.Float(), nullable=True),
        sa.Column("vwap_value", sa.Float(), nullable=True),
        sa.Column("volume_ratio", sa.Float(), nullable=True),
        sa.Column("rules_passed", sa.JSON(), nullable=False),
        sa.Column("sector_proxy", sa.String(length=20), nullable=True),
        sa.Column("market_regime", sa.String(length=20), nullable=False),
        sa.Column("strength_score", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False, server_default="OPEN"),
        sa.Column("outcome_recorded_at", sa.DateTime(), nullable=True),
        sa.Column("tier", sa.String(length=20), nullable=True, server_default="INSTITUTIONAL"),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_signal_history_symbol", "signal_history", ["symbol"])
    op.create_index("ix_signal_history_outcome", "signal_history", ["outcome"])
    op.create_index("ix_signal_history_generated_at", "signal_history", ["generated_at"])

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signal_history.id"), nullable=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="OPEN"),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("realized_pnl", sa.Float(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_positions_symbol", "positions", ["symbol"])
    op.create_index("ix_positions_status", "positions", ["status"])


def downgrade():
    op.drop_table("positions")
    op.drop_table("signal_history")
    op.drop_table("portfolio")
