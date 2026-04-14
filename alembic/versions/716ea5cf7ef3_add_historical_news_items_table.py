"""Add historical_news_items table

Revision ID: 716ea5cf7ef3
Revises: 23f22508e92b
Create Date: 2026-04-13 19:28:39.860082
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '716ea5cf7ef3'
down_revision = '23f22508e92b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('historical_news_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(length=120), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('link', sa.String(length=512), nullable=False),
        sa.Column('publisher', sa.String(length=120), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ticker', 'link', 'published_at', name='uq_historical_news_items_ticker_link_published_at')
    )
    op.create_index('idx_historical_news_ticker_published', 'historical_news_items', ['ticker', 'published_at'], unique=False)
    op.create_index(op.f('ix_historical_news_items_link'), 'historical_news_items', ['link'], unique=False)
    op.create_index(op.f('ix_historical_news_items_provider'), 'historical_news_items', ['provider'], unique=False)
    op.create_index(op.f('ix_historical_news_items_published_at'), 'historical_news_items', ['published_at'], unique=False)
    op.create_index(op.f('ix_historical_news_items_ticker'), 'historical_news_items', ['ticker'], unique=False)


def downgrade() -> None:
    op.drop_table('historical_news_items')
