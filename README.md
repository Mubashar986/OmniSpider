# 🕷️ OmniSpider — Unblockable Multi-Tier Stealth Web Scraper & Lead Generation Engine

OmniSpider is an enterprise-grade, high-performance B2B web scraping, lead generation, and email verification engine. Built with **Python 3.12**, **Celery**, **Upstash Cloud Redis**, **PostgreSQL 16**, **SQLAlchemy 2.0**, and **Alembic**, OmniSpider bypasses advanced Web Application Firewalls (Cloudflare Turnstile, Incapsula, Akamai) using an automated dual-engine fallback pipeline.

---

## ⚡ Key Features

* **🛡️ Dual-Engine Stealth Pipeline:**
  * **Tier 1 (`curl_cffi`):** High-speed HTTP request spoofing Chrome TLS/JA3/JA4 fingerprints (~0.2s latency).
  * **Tier 2 (`nodriver`):** Direct Chrome DevTools Protocol (CDP) over WebSockets for bypassing Cloudflare Turnstile & executing JavaScript SPAs.
* **✉️ 4-Stage B2B Email & SMTP Verification Engine:**
  * **Stage 1 (Syntax):** RFC 5322 regex validation.
  * **Stage 2 (Disposable Filter):** Rejects temporary burner email domains (`mailinator.com`, `tempmail.com`, etc.).
  * **Stage 3 (DNS MX Resolution):** Resolves target domain mail server hostnames with layered RAM & Redis caching.
  * **Stage 4 (Non-Sending SMTP Handshake):** Connects to remote mail servers via TCP Port 25 (`EHLO`, `MAIL FROM`, `RCPT TO`) with random UUID catch-all probe detection.
* **📁 Directory Routing & B2B Platform Protection:**
  * Classifies pages into `DIRECTORY_LISTING`, `DIRECTORY_PROFILE`, or `COMPANY_SITE`.
  * Prevents middleman directory sites (Clutch.co, GoodFirms.co, G2.com) from polluting PostgreSQL company records.
* **💻 Technographic Stack Extraction:**
  * Automatically matches script signatures against [`config/tech_signatures.json`](file:///C:/Users/Mubashar%20Ashraf/scraper/config/tech_signatures.json) (Next.js, React, HubSpot, Shopify, WordPress).
* **🔄 7-Day Frequency Control Cooldown:**
  * Checks PostgreSQL `scrape_logs` by exact URL to prevent redundant scraping of recently processed targets.
* **🌐 Controlled Recursive Domain Subpage Crawling:**
  * Discovers internal domain links (`/about`, `/team`, `/contact`) with session deduplication (`_session_claim`) and depth ceilings.
* **🗄️ Thread-Safe PostgreSQL Persistence:**
  * Native PostgreSQL `ON CONFLICT DO UPDATE` (UPSERT) operations for deduplicating companies, leads, and JSONB phone structures.

---

## 🏗️ Project Architecture Layout

```text
OmniSpider/
├── .env                             # Local environment configuration
├── .env.example                     # Environment template for PostgreSQL, Redis, & Scraper pipeline
├── requirements.txt                 # Dependencies (SQLAlchemy 2.0, Alembic, Celery, Redis, curl_cffi, nodriver, dnspython, aiosmtplib)
├── alembic.ini                      # Alembic migration configuration
├── alembic/                         # Database migration scripts (001 -> 004 lead verification)
├── config/                          # Tech stack signatures & profile configurations
├── app/
│   ├── core/                        # Settings registry (config.py), DB session, & Redis client
│   ├── models/                      # SQLAlchemy 2.0 ORM Models (Company, Lead, ScrapeLog, Technology)
│   ├── schemas/                     # Pydantic Validation Schemas
│   ├── repositories/                # PostgreSQL Repositories (Company, Lead, ScrapeLog)
│   ├── services/scrapers/           # Scraping Engines (Tier 1 & Tier 2), Email Verifier, & HTML Parser
│   └── tasks/                       # Celery Task Queue Pipeline (`scrape_url_task`)
├── scripts/                         # Environment diagnostics, quality report, & CLI scraper
└── tests/                           # Unit test suites (Pytest)
```

---

## 🚀 Quickstart & Setup Guide

### 1. Environment Setup
```powershell
# Create & activate Python 3.12 virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install required dependencies + test runner
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pytest pytest-asyncio
```

### 2. Environment Configuration
Copy `.env.example` to `.env` and fill in your PostgreSQL and Upstash Cloud Redis credentials:
```powershell
cp .env.example .env
```

### 3. Run Environment Diagnostics & Database Migrations
```powershell
# Verify DB, Redis, and Python package dependencies
python scripts/check_env.py

# Apply database schema migrations
alembic upgrade head
```

---

## 🧪 Testing & Quality Reports

### 1. Run Automated Unit Test Suites
```powershell
# Test Email Verifier service
python -m pytest tests/test_email_verifier.py -v

# Test HTML Parser service
python -m pytest tests/test_parser_service.py -v

# Run all unit tests
python -m pytest tests/ -v
```

### 2. Run Lead Quality Report
```powershell
python scripts/quality_report.py
```

---

## 💻 Usage CLI & Worker Commands

### Step 1: Start Celery Worker (Terminal 1)
```powershell
# Windows Local Execution Pool
python -m celery -A app.tasks.celery_app worker --pool=solo -l info
```

### Step 2: Run Universal Scraper CLI (Terminal 2)

#### Scrape a single company website:
```powershell
python scripts/scrape.py https://stripe.com --no-cooldown
```

#### Scrape recursively (Crawling `/about`, `/team`, `/contact`):
```powershell
python scripts/scrape.py https://stripe.com -r -d 1 --no-cooldown
```

#### Scrape a B2B Directory Page (GoodFirms / Clutch):
```powershell
python scripts/scrape.py https://www.goodfirms.co/directory/languages/top-software-development-companies/python -r -d 1 --no-cooldown
```

#### Purge Celery Task Queue:
```powershell
python -m celery -A app.tasks.celery_app purge -f
```

---

## 📜 License
Licensed under the MIT License.
