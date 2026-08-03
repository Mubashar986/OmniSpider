"""004_lead_verification_company_contact

Adds the SRS-aligned verification and firmographic columns:
- leads: email_status, email_verified_at, source_platform, seniority, department
- companies: hq_phone, linkedin_url, twitter_url

Revision ID: 004_lead_verif_company_contact
Revises: 003_add_extra_metadata
Create Date: 2026-08-02

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '004_lead_verif_company_contact'
down_revision: Union[str, None] = '003_add_extra_metadata'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('leads', sa.Column('email_status', sa.String(50), server_default='unverified', nullable=False))
    op.add_column('leads', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('leads', sa.Column('source_platform', sa.String(100), nullable=True))
    op.add_column('leads', sa.Column('seniority', sa.String(50), nullable=True))
    op.add_column('leads', sa.Column('department', sa.String(100), nullable=True))
    op.add_column('companies', sa.Column('hq_phone', sa.String(50), nullable=True))
    op.add_column('companies', sa.Column('linkedin_url', sa.String(500), nullable=True))
    op.add_column('companies', sa.Column('twitter_url', sa.String(500), nullable=True))

    # Backfill email_status from the legacy boolean flags.
    op.execute(
        """
        UPDATE leads SET email_status = CASE
            WHEN disposable_flag THEN 'disposable'
            WHEN email_verified AND mx_valid THEN 'verified'
            WHEN NOT mx_valid THEN 'invalid'
            ELSE 'unverified'
        END
        """
    )


def downgrade() -> None:
    op.drop_column('companies', 'twitter_url')
    op.drop_column('companies', 'linkedin_url')
    op.drop_column('companies', 'hq_phone')
    op.drop_column('leads', 'department')
    op.drop_column('leads', 'seniority')
    op.drop_column('leads', 'source_platform')
    op.drop_column('leads', 'email_verified_at')
    op.drop_column('leads', 'email_status')
