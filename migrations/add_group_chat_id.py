"""Add group_chat_id to events table

Revision ID: 1234
Revises: 
Create Date: 2025-11-26 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1234'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Add group_chat_id column to events table
    op.add_column('events', sa.Column('group_chat_id', sa.Integer(), nullable=True))

def downgrade():
    # Drop group_chat_id column
    op.drop_column('events', 'group_chat_id')
