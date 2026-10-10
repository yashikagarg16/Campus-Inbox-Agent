"""users and per-user data

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-10 14:23:30.054291
"""
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=True),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('usage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.String(length=10), nullable=False),
    sa.Column('llm_calls', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'day', name='uq_usage_user_day')
    )
    with op.batch_alter_table('usage', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_usage_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_audit_events_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('emails', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_emails_user_id'), ['user_id'], unique=False)
        batch_op.create_foreign_key('fk_emails_user_id_users', 'users', ['user_id'], ['id'], ondelete='CASCADE')

    with op.batch_alter_table('profile', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint('uq_profile_user_id', ['user_id'])
        batch_op.create_foreign_key('fk_profile_user_id_users', 'users', ['user_id'], ['id'], ondelete='CASCADE')

    # Data from before accounts existed belongs to the single local user.
    conn = op.get_bind()
    existing = (conn.execute(sa.text("SELECT COUNT(*) FROM emails")).scalar()
                + conn.execute(sa.text("SELECT COUNT(*) FROM profile")).scalar())
    if existing:
        conn.execute(sa.text("INSERT INTO users (email, role, created_at) VALUES ('local@localhost', 'local', :now)"),
                     {"now": datetime.now()})
        local_id = conn.execute(sa.text("SELECT id FROM users WHERE email = 'local@localhost'")).scalar()
        for table in ("emails", "profile", "audit_events"):
            conn.execute(sa.text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"), {"uid": local_id})


def downgrade() -> None:
    with op.batch_alter_table('profile', schema=None) as batch_op:
        batch_op.drop_constraint('fk_profile_user_id_users', type_='foreignkey')
        batch_op.drop_constraint('uq_profile_user_id', type_='unique')
        batch_op.drop_column('user_id')

    with op.batch_alter_table('emails', schema=None) as batch_op:
        batch_op.drop_constraint('fk_emails_user_id_users', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_emails_user_id'))
        batch_op.drop_column('user_id')

    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_events_user_id'))
        batch_op.drop_column('user_id')

    with op.batch_alter_table('usage', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_usage_user_id'))

    op.drop_table('usage')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
