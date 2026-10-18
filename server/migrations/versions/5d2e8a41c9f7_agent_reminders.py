"""agent reminders: a follow-up an agent will do itself

Revision ID: 5d2e8a41c9f7
Revises: 0b8c5799a1ac
Create Date: 2026-10-19 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d2e8a41c9f7'
down_revision: Union[str, Sequence[str], None] = '0b8c5799a1ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('reminders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('for_agent', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('reminders', schema=None) as batch_op:
        batch_op.drop_column('for_agent')
