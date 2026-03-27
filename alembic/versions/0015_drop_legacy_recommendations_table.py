"""drop legacy recommendations table

Revision ID: 0015_drop_legacy_recommendations_table
Revises: 0014_recommendation_outcomes
Create Date: 2026-03-24 06:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_drop_legacy_recommendations_table"
down_revision = "0014_recommendation_outcomes"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _get_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    tables = _get_tables()
    if "recommendations" not in tables:
        return
    indexes = _get_indexes("recommendations")
    if "ix_recommendations_ticker" in indexes:
        op.drop_index("ix_recommendations_ticker", table_name="recommendations")
    if "ix_recommendations_run_id" in indexes:
        op.drop_index("ix_recommendations_run_id", table_name="recommendations")
    op.drop_table("recommendations")


def downgrade() -> None:
    if "recommendations" in _get_tables():
        return
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("take_profit", sa.Float(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("analysis_json", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw_output", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_recommendations_run_id", "recommendations", ["run_id"], unique=False)
    op.create_index("ix_recommendations_ticker", "recommendations", ["ticker"], unique=False)
