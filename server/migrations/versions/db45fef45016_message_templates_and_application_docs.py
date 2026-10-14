"""message templates and application docs

Revision ID: db45fef45016
Revises: a7305af822bb
Create Date: 2026-10-14 17:53:03.935664

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db45fef45016'
down_revision: Union[str, Sequence[str], None] = 'a7305af822bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('message_templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('subject', sa.String(length=300), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('archived_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_message_templates_category', 'message_templates', ['category'], unique=False)

    # Batch mode rebuilds `opportunities` (SQLite can't add a foreign key in place). Safe: this connection
    # doesn't enable PRAGMA foreign_keys, so dropping the old table doesn't cascade into reminders/events.
    with op.batch_alter_table('opportunities', schema=None) as batch_op:
        batch_op.add_column(sa.Column('resume_url', sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column('resume_version', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('cover_letter_url', sa.String(length=1000), nullable=True))
        batch_op.add_column(sa.Column('template_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_opportunities_template_id', 'message_templates', ['template_id'], ['id'],
                                    ondelete='SET NULL')
    op.create_index('ix_opportunities_template_id', 'opportunities', ['template_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_opportunities_template_id', table_name='opportunities')
    with op.batch_alter_table('opportunities', schema=None) as batch_op:
        batch_op.drop_constraint('fk_opportunities_template_id', type_='foreignkey')
        for col in ('template_id', 'cover_letter_url', 'resume_version', 'resume_url'):
            batch_op.drop_column(col)
    op.drop_index('ix_message_templates_category', table_name='message_templates')
    op.drop_table('message_templates')
