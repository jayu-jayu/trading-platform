"""add price_cache table — historical OHLCV cache for the backtest engine

Revision ID: 0002_add_price_cache
Revises: 0001_baseline_schema
Create Date: 2026-08-07

"""
from alembic import op
import sqlalchemy as sa

revision = "0002_add_price_cache"
down_revision = "0001_baseline_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "price_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("interval", sa.String(length=10), nullable=False),
        sa.Column("candle_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("symbol", "interval", "candle_timestamp", name="uq_price_cache_symbol_interval_ts"),
    )
    op.create_index(
        "ix_price_cache_symbol_interval_ts", "price_cache", ["symbol", "interval", "candle_timestamp"]
    )


def downgrade():
    op.drop_index("ix_price_cache_symbol_interval_ts", table_name="price_cache")
    op.drop_table("price_cache")
