"""add backtest_runs and backtest_trades tables — Phase 1 backtesting foundation

Purely additive: two new tables, no existing table altered. Safe to apply
to the live database without any downtime or data-migration risk.

Revision ID: 0003_add_backtest_runs
Revises: 0002_add_price_cache
Create Date: 2026-08-07

"""
from alembic import op
import sqlalchemy as sa

revision = "0003_add_backtest_runs"
down_revision = "0002_add_price_cache"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("interval", sa.String(length=10), nullable=False, server_default="15m"),
        sa.Column("start_date", sa.DateTime(), nullable=False),
        sa.Column("end_date", sa.DateTime(), nullable=False),
        sa.Column("total_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("institutional_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("developing_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winning_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_rate_pct", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=True),
        sa.Column("total_pnl", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="RUNNING"),
        sa.Column("error_detail", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("asset_type", sa.String(length=10), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("rules_passed", sa.JSON(), nullable=False),
        sa.Column("entry_time", sa.DateTime(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("exit_time", sa.DateTime(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("exit_reason", sa.String(length=30), nullable=True),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.Column("pnl_pct", sa.Float(), nullable=True),
    )
    op.create_index("ix_backtest_trades_run_id", "backtest_trades", ["run_id"])


def downgrade():
    op.drop_index("ix_backtest_trades_run_id", table_name="backtest_trades")
    op.drop_table("backtest_trades")
    op.drop_table("backtest_runs")
