"""empty message

Revision ID: 572061846d99
Revises: 4b7249230300
Create Date: 2026-10-23 14:03:34.882691

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '572061846d99'
down_revision = '4b7249230300'
branch_labels = None
depends_on = None


def _existing_unique_names(table_name):
    """DB에 이미 존재하는 UNIQUE 제약조건 이름 목록"""
    insp = inspect(op.get_bind())
    return {uc["name"] for uc in insp.get_unique_constraints(table_name)}


def upgrade():
    existing = _existing_unique_names('user')
    with op.batch_alter_table('user', schema=None) as batch_op:
        if 'uq_user_email' not in existing:
            batch_op.create_unique_constraint(batch_op.f('uq_user_email'), ['email'])
        if 'uq_user_username' not in existing:
            batch_op.create_unique_constraint(batch_op.f('uq_user_username'), ['username'])

    # ### end Alembic commands ###


def downgrade():
    existing = _existing_unique_names('user')
    with op.batch_alter_table('user', schema=None) as batch_op:
        if 'uq_user_username' in existing:
            batch_op.drop_constraint(batch_op.f('uq_user_username'), type_='unique')
        if 'uq_user_email' in existing:
            batch_op.drop_constraint(batch_op.f('uq_user_email'), type_='unique')

    # ### end Alembic commands ###
