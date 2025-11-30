"""Add admin_id to events table"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_admin_id_to_events'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Add admin_id column to events table
    op.add_column('events', sa.Column('admin_id', sa.Integer(), nullable=False, server_default='0'))
    
    # Create index for better query performance
    op.create_index(op.f('ix_events_admin_id'), 'events', ['admin_id'], unique=False)

def downgrade():
    # Drop the index first
    op.drop_index(op.f('ix_events_admin_id'), table_name='events')
    # Then drop the column
    op.drop_column('events', 'admin_id')
