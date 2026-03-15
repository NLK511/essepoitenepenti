"""add prototype feature vectors

Revision ID: 0009_recommendation_feature_vectors
Revises: 0008_job_types_and_run_metadata
Create Date: 2026-03-15 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_recommendation_feature_vectors"
down_revision = "0008_job_types_and_run_metadata"
branch_labels = None
depends_on = None


def _get_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    columns = _get_columns("recommendations")
    if "feature_vector_json" not in columns:
        op.add_column(
            "recommendations",
            sa.Column("feature_vector_json", sa.Text(), nullable=False, server_default=""),
        )
    if "normalized_feature_vector_json" not in columns:
        op.add_column(
            "recommendations",
            sa.Column("normalized_feature_vector_json", sa.Text(), nullable=False, server_default=""),
        )
    if "aggregations_json" not in columns:
        op.add_column(
            "recommendations",
            sa.Column("aggregations_json", sa.Text(), nullable=False, server_default=""),
        )
    if "confidence_weights_json" not in columns:
        op.add_column(
            "recommendations",
            sa.Column("confidence_weights_json", sa.Text(), nullable=False, server_default=""),
        )
    if "summary_method" not in columns:
        op.add_column(
            "recommendations",
            sa.Column("summary_method", sa.String(length=64), nullable=False, server_default=""),
        )


def downgrade() -> None:
    columns = _get_columns("recommendations")
    if "summary_method" in columns:
        op.drop_column("recommendations", "summary_method")
    if "confidence_weights_json" in columns:
        op.drop_column("recommendations", "confidence_weights_json")
    if "aggregations_json" in columns:
        op.drop_column("recommendations", "aggregations_json")
    if "normalized_feature_vector_json" in columns:
        op.drop_column("recommendations", "normalized_feature_vector_json")
    if "feature_vector_json" in columns:
        op.drop_column("recommendations", "feature_vector_json")
