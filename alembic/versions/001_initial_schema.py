"""001_initial_schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-07-29

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Enable pgcrypto extension for UUID generation
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # Create Companies Table
    op.create_table(
        'companies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('industry', sa.String(length=255), nullable=True),
        sa.Column('company_size', sa.String(length=100), nullable=True),
        sa.Column('website_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('idx_companies_domain', 'companies', ['domain'], unique=True)

    # Create Leads Table
    op.create_table(
        'leads',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('first_name', sa.String(length=150), nullable=True),
        sa.Column('last_name', sa.String(length=150), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('work_email', sa.String(length=255), nullable=False),
        sa.Column('phones', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('linkedin_url', sa.Text(), nullable=True),
        sa.Column('email_verified', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('mx_valid', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('disposable_flag', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('idx_leads_work_email', 'leads', ['work_email'], unique=True)

    # Create Company Technologies Table
    op.create_table(
        'company_technologies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tech_name', sa.String(length=150), nullable=False),
        sa.Column('category', sa.String(length=150), nullable=True),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # Create Scrape Logs Table
    op.create_table(
        'scrape_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('engine_used', sa.String(length=50), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('scraped_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('idx_scrape_logs_domain_scraped_at', 'scrape_logs', ['domain', sa.text('scraped_at DESC')])

def downgrade() -> None:
    op.drop_index('idx_scrape_logs_domain_scraped_at', table_name='scrape_logs')
    op.drop_table('scrape_logs')
    op.drop_table('company_technologies')
    op.drop_index('idx_leads_work_email', table_name='leads')
    op.drop_table('leads')
    op.drop_index('idx_companies_domain', table_name='companies')
    op.drop_table('companies')
