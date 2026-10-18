"""message categories as data, template review flags, per-message usage on events

Revision ID: c3f1a9d2e7b4
Revises: db45fef45016
Create Date: 2026-10-15 10:00:00

"""
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f1a9d2e7b4'
down_revision: Union[str, Sequence[str], None] = 'db45fef45016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The three categories that used to be fixed in domain.py, with the agent rules that used to live in the
# MCP instructions now as their purpose (the owner can edit them).
SEED = [
    ("linkedin", "LinkedIn message", False,
     "First contact on LinkedIn (connection note or InMail), only while the deal is still a lead (nothing sent to them yet)."),
    ("cold_email", "Cold email", True,
     "First email to someone who doesn't know the owner, only while the deal is still a lead (nothing sent to them yet). "
     "A LinkedIn connection alone is still cold."),
    ("warm_email", "Warm email", True,
     "First email to someone who knows the owner, or whose deal came through a referral or FirstGlance "
     "(network = referral / firstglance), only while the deal is still a lead (nothing sent to them yet)."),
]


def upgrade() -> None:
    """Upgrade schema."""
    categories = op.create_table('message_categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=True),
    sa.Column('has_subject', sa.Boolean(), nullable=False),
    sa.Column('needs_review', sa.Boolean(), nullable=False),
    sa.Column('updated_by', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('archived_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(categories, [{"key": k, "name": n, "has_subject": subj, "purpose": p, "needs_review": False,
                                 "created_at": now, "updated_at": now} for k, n, subj, p in SEED])

    # The rebuild also adds AUTOINCREMENT: a removed message's id is never handed to a new one (agents keep ids).
    with op.batch_alter_table('message_templates', schema=None, recreate='always',
                              table_kwargs={'sqlite_autoincrement': True}) as batch_op:
        batch_op.alter_column('category', type_=sa.String(length=40), existing_type=sa.String(length=20),
                              existing_nullable=False)
        batch_op.add_column(sa.Column('needs_review', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('updated_by', sa.String(length=120), nullable=True))

    # Batch mode rebuilds `events` (SQLite can't add a foreign key in place); nothing references events.
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('channel', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('template_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_events_template_id', 'message_templates', ['template_id'], ['id'],
                                    ondelete='SET NULL')
    op.create_index('ix_events_template_id', 'events', ['template_id'], unique=False)

    # Backfill: every message you sent went out on the deal's channel; a deal's recorded first message was
    # used by its earliest my_message.
    op.execute("UPDATE events SET channel = (SELECT channel FROM opportunities o WHERE o.id = events.opportunity_id) "
               "WHERE kind = 'my_message'")
    op.execute("""
        UPDATE events SET template_id = (SELECT template_id FROM opportunities o WHERE o.id = events.opportunity_id)
        WHERE id IN (
            SELECT (SELECT e.id FROM events e WHERE e.opportunity_id = o.id AND e.kind = 'my_message'
                    ORDER BY e.occurred_at, e.id LIMIT 1)
            FROM opportunities o WHERE o.template_id IS NOT NULL)
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_events_template_id', table_name='events')
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_constraint('fk_events_template_id', type_='foreignkey')
        batch_op.drop_column('template_id')
        batch_op.drop_column('channel')
    with op.batch_alter_table('message_templates', schema=None) as batch_op:
        batch_op.drop_column('updated_by')
        batch_op.drop_column('needs_review')
        batch_op.alter_column('category', type_=sa.String(length=20), existing_type=sa.String(length=40),
                              existing_nullable=False)
    op.drop_table('message_categories')
