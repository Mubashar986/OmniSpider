-- PostgreSQL Initial Migration for Lead Generation Engine
-- Migration: 001_initial_schema.sql

-- Enable pgcrypto for gen_random_uuid() if available
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Companies Table
CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    industry VARCHAR(255),
    company_size VARCHAR(100),
    website_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Leads Table
CREATE TABLE IF NOT EXISTS leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    first_name VARCHAR(150),
    last_name VARCHAR(150),
    title VARCHAR(255),
    work_email VARCHAR(255) UNIQUE NOT NULL,
    phones JSONB DEFAULT '[]'::jsonb,
    linkedin_url TEXT,
    email_verified BOOLEAN DEFAULT FALSE,
    mx_valid BOOLEAN DEFAULT FALSE,
    disposable_flag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Company Technologies Table (Tech Stack tracking)
CREATE TABLE IF NOT EXISTS company_technologies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    tech_name VARCHAR(150) NOT NULL,
    category VARCHAR(150),
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Scrape Logs Table (7-day frequency control & error tracking)
CREATE TABLE IF NOT EXISTS scrape_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url TEXT NOT NULL,
    domain VARCHAR(255) NOT NULL,
    status_code INTEGER,
    engine_used VARCHAR(50),
    error_message TEXT,
    scraped_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Unique & Frequency Indexes
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain);
CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_work_email ON leads(work_email);
CREATE INDEX IF NOT EXISTS idx_scrape_logs_domain_scraped_at ON scrape_logs(domain, scraped_at DESC);
