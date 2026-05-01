"""allow decision samples without recommendation plans

Revision ID: 1f6d8d4c0b2a
Revises: 8c3d2f4a9e10
Create Date: 2026-04-16 12:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "1f6d8d4c0b2a"
down_revision = "8c3d2f4a9e10"
branch_labels = None
depends_on = None


def _get_tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _get_unique_constraints(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {item["name"] for item in inspector.get_unique_constraints(table_name) if item.get("name")}


def upgrade() -> None:
    if "recommendation_decision_samples" not in _get_tables():
        return
    existing_constraints = _get_unique_constraints("recommendation_decision_samples")
    with op.batch_alter_table("recommendation_decision_samples") as batch_op:
        batch_op.alter_column(
            "recommendation_plan_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        if "uq_recommendation_decision_samples_signal_id" not in existing_constraints:
            batch_op.create_unique_constraint(
                "uq_recommendation_decision_samples_signal_id",
                ["ticker_signal_snapshot_id"],
            )


def downgrade() -> None:
    if "recommendation_decision_samples" not in _get_tables():
        return
    existing_constraints = _get_unique_constraints("recommendation_decision_samples")
    op.execute(
        sa.text(
            "DELETE FROM recommendation_decision_samples WHERE recommendation_plan_id IS NULL"
        )
    )
    with op.batch_alter_table("recommendation_decision_samples") as batch_op:
        if "uq_recommendation_decision_samples_signal_id" in existing_constraints:
            batch_op.drop_constraint("uq_recommendation_decision_samples_signal_id", type_="unique")
        batch_op.alter_column(
            "recommendation_plan_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
