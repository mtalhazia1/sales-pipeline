"""reminders are the owner's only: drop the agent follow-up column

Revision ID: a3e9f2c7b815
Revises: 8f1c3b7d2a64
Create Date: 2026-10-19 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3e9f2c7b815'
down_revision: Union[str, Sequence[str], None] = '8f1c3b7d2a64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('reminders', schema=None) as batch_op:
        batch_op.drop_column('agent')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('reminders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('agent', sa.String(length=120), nullable=True))
