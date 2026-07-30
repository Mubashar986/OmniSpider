"""002_company_tech_unique

Revision ID: 002_company_tech_unique
Revises: 001_initial_schema
Create Date: 2026-07-30

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002_company_tech_unique'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Clean up potential existing duplicate rows before creating unique constraint
    op.execute("""
        DELETE FROM company_technologies a USING company_technologies b
        WHERE a.id < b.id AND a.company_id = b.company_id AND a.tech_name = b.tech_name;
    """)

    # Create unique constraint on (company_id, tech_name)
    op.create_unique_constraint(
        "uq_company_tech",
        "company_technologies",
        ["company_id", "tech_name"]
    )

def downgrade() -> None:
    op.drop_constraint(
        "uq_company_tech",
        "company_technologies",
        type_="unique"
    )
