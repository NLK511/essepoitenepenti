"""observability_events

Revision ID: 0040_observability_events
Revises: 0039_run_correlation_id
Create Date: 2026-05-09
"""
from alembic import op
import sqlalchemy as sa


revision = "0040_observability_events"
down_revision = "0039_run_correlation_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "observability_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(length=80), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_observability_events_correlation_id"), "observability_events", ["correlation_id"], unique=False)
    op.create_index(op.f("ix_observability_events_created_at"), "observability_events", ["created_at"], unique=False)
    op.create_index(op.f("ix_observability_events_event_type"), "observability_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_observability_events_job_id"), "observability_events", ["job_id"], unique=False)
    op.create_index(op.f("ix_observability_events_run_id"), "observability_events", ["run_id"], unique=False)
    op.create_index(op.f("ix_observability_events_severity"), "observability_events", ["severity"], unique=False)
    op.create_index(op.f("ix_observability_events_source"), "observability_events", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_observability_events_source"), table_name="observability_events")
    op.drop_index(op.f("ix_observability_events_severity"), table_name="observability_events")
    op.drop_index(op.f("ix_observability_events_run_id"), table_name="observability_events")
    op.drop_index(op.f("ix_observability_events_job_id"), table_name="observability_events")
    op.drop_index(op.f("ix_observability_events_event_type"), table_name="observability_events")
    op.drop_index(op.f("ix_observability_events_created_at"), table_name="observability_events")
    op.drop_index(op.f("ix_observability_events_correlation_id"), table_name="observability_events")
    op.drop_table("observability_events")
