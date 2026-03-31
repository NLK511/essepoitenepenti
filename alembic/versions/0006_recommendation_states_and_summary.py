"""recommendation states and summary

Revision ID: 0006_rec_states_summary
Revises: 0005_run_timing_breakdown
Create Date: 2026-03-12 23:58:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_rec_states_summary"
down_revision = "0005_run_timing_breakdown"
branch_labels = None
depends_on = None


def _get_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _get_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    recommendation_columns = _get_columns("recommendations")
    if "indicator_summary" not in recommendation_columns:
        op.add_column("recommendations", sa.Column("indicator_summary", sa.Text(), nullable=False, server_default=""))
    if "evaluation_state" not in recommendation_columns:
        op.add_column(
            "recommendations",
            sa.Column("evaluation_state", sa.String(length=16), nullable=False, server_default="PENDING"),
        )
    if "evaluated_at" not in recommendation_columns:
        op.add_column("recommendations", sa.Column("evaluated_at", sa.DateTime(), nullable=True))

    recommendation_indexes = _get_indexes("recommendations")
    if "ix_recommendations_evaluation_state" not in recommendation_indexes:
        op.create_index("ix_recommendations_evaluation_state", "recommendations", ["evaluation_state"])


def downgrade() -> None:
    recommendation_indexes = _get_indexes("recommendations")
    if "ix_recommendations_evaluation_state" in recommendation_indexes:
        op.drop_index("ix_recommendations_evaluation_state", table_name="recommendations")

    recommendation_columns = _get_columns("recommendations")
    if "evaluated_at" in recommendation_columns:
        op.drop_column("recommendations", "evaluated_at")
    if "evaluation_state" in recommendation_columns:
        op.drop_column("recommendations", "evaluation_state")
    if "indicator_summary" in recommendation_columns:
        op.drop_column("recommendations", "indicator_summary")
