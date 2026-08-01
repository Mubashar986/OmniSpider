"""003_add_extra_metadata

Revision ID: 003_add_extra_metadata
Revises: 002_company_tech_unique
Create Date: 2026-08-01

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '003_add_extra_metadata'
down_revision: Union[str, None] = '002_company_tech_unique'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('companies', sa.Column('extra_metadata', JSONB(), server_default='{}', nullable=True))

def downgrade() -> None:
    op.drop_column('companies', 'extra_metadata')
