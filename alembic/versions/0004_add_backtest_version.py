"""add backtest_run strategy_version and git_commit_hash

Revision ID: 0004_add_backtest_version
Revises: 0003_add_backtest_runs
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_add_backtest_version"
down_revision = "0003_add_backtest_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('backtest_runs', sa.Column('strategy_version', sa.String(length=64), nullable=True))
    op.add_column('backtest_runs', sa.Column('git_commit_hash', sa.String(length=40), nullable=True))


def downgrade():
    op.drop_column('backtest_runs', 'git_commit_hash')
    op.drop_column('backtest_runs', 'strategy_version')
