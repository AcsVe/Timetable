"""user ui prefs

The side menu's favourites and folded groups (app_user.ui_prefs), and the audit foreign keys that the
holidays/plans migration left out. generator_run's are skipped on purpose (autogenerate repeats them).

Revision ID: 9df23ede9717
Revises: 6460d0aed9ca
Create Date: 2026-10-19 22:47:36.046719

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '9df23ede9717'
down_revision = '6460d0aed9ca'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('app_user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ui_prefs', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))

    with op.batch_alter_table('holiday', schema=None) as batch_op:
        batch_op.create_foreign_key(batch_op.f('fk_holiday_created_by_app_user'), 'app_user', ['created_by'], ['id'], use_alter=True)
        batch_op.create_foreign_key(batch_op.f('fk_holiday_updated_by_app_user'), 'app_user', ['updated_by'], ['id'], use_alter=True)

    with op.batch_alter_table('period_plan', schema=None) as batch_op:
        batch_op.create_foreign_key(batch_op.f('fk_period_plan_created_by_app_user'), 'app_user', ['created_by'], ['id'], use_alter=True)
        batch_op.create_foreign_key(batch_op.f('fk_period_plan_updated_by_app_user'), 'app_user', ['updated_by'], ['id'], use_alter=True)



def downgrade():
    with op.batch_alter_table('period_plan', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_period_plan_updated_by_app_user'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('fk_period_plan_created_by_app_user'), type_='foreignkey')

    with op.batch_alter_table('holiday', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_holiday_updated_by_app_user'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('fk_holiday_created_by_app_user'), type_='foreignkey')

    with op.batch_alter_table('app_user', schema=None) as batch_op:
        batch_op.drop_column('ui_prefs')

