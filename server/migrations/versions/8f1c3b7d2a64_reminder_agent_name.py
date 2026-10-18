"""reminders: name the agent a follow-up belongs to (replaces the for_agent flag)

Revision ID: 8f1c3b7d2a64
Revises: 5d2e8a41c9f7
Create Date: 2026-10-19 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f1c3b7d2a64'
down_revision: Union[str, Sequence[str], None] = '5d2e8a41c9f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('reminders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('agent', sa.String(length=120), nullable=True))
    # A flagged follow-up belonged to the agent that created it.
    op.execute("UPDATE reminders SET agent = created_by WHERE for_agent")
    with op.batch_alter_table('reminders', schema=None) as batch_op:
        batch_op.drop_column('for_agent')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('reminders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('for_agent', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE reminders SET for_agent = 1 WHERE agent IS NOT NULL")
    with op.batch_alter_table('reminders', schema=None) as batch_op:
        batch_op.drop_column('agent')
