"""historical_news_link_to_text

Revision ID: 8c3d2f4a9e10
Revises: 716ea5cf7ef3
Create Date: 2026-04-14 21:20:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8c3d2f4a9e10'
down_revision = '716ea5cf7ef3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'historical_news_items',
        'link',
        existing_type=sa.String(length=512),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'historical_news_items',
        'link',
        existing_type=sa.Text(),
        type_=sa.String(length=512),
        existing_nullable=False,
    )
