"""baseline: current production schema (no-op)

Revision ID: 6bedcd3557d0
Revises: 
Create Date: 2026-07-27 22:14:23.588886

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6bedcd3557d0'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
