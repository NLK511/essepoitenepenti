"""recommendation diagnostics fields

Revision ID: 0003_recommendation_diagnostics_fields
Revises: 0002_job_last_enqueued_at
Create Date: 2026-03-14 00:50:00
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_recommendation_diagnostics_fields"
down_revision = "0002_job_last_enqueued_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recommendations", sa.Column("provider_errors_json", sa.Text(), nullable=False, server_default=""))
    op.add_column("recommendations", sa.Column("problems_json", sa.Text(), nullable=False, server_default=""))
    op.add_column("recommendations", sa.Column("news_feed_errors_json", sa.Text(), nullable=False, server_default=""))
    op.add_column("recommendations", sa.Column("summary_error", sa.Text(), nullable=False, server_default=""))
    op.add_column("recommendations", sa.Column("llm_error", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("recommendations", "llm_error")
    op.drop_column("recommendations", "summary_error")
    op.drop_column("recommendations", "news_feed_errors_json")
    op.drop_column("recommendations", "problems_json")
    op.drop_column("recommendations", "provider_errors_json")
