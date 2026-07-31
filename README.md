# 🕷️ OmniSpider — Unblockable Multi-Tier Stealth Web Scraper & Lead Generation Engine

OmniSpider is an enterprise-grade, high-performance B2B web scraping and lead generation engine. Built with **Python 3.12**, **Celery**, **Upstash Cloud Redis**, **PostgreSQL 16**, **SQLAlchemy 2.0**, and **Alembic**, OmniSpider bypasses advanced Web Application Firewalls (Cloudflare Turnstile, Incapsula, Akamai) using an automated dual-engine fallback pipeline.

---

## ⚡ Key Features

* **🛡️ Dual-Engine Stealth Pipeline:**
  * **Tier 1 (`curl_cffi`):** High-speed HTTP request spoofing Chrome 120 TLS/JA3/JA4 fingerprints (~0.2s latency).
  * **Tier 2 (`nodriver`):** Direct Chrome DevTools Protocol (CDP) over WebSockets for bypassing Cloudflare Turnstile & executing JavaScript SPAs without detectable automation flags.
* **✉️ 3-Layer Email & MX Deliverability Verification:**
  * RFC 5322 Regex Syntax Validation.
  * Disposable / Temporary Domain Filtering (`mailinator.com`, `tempmail.com`).
  * Live DNS `MX` Record Resolution via `dnspython`.
* **🔄 Incremental 7-Day Frequency Control Cooldown:**
  * Automatically checks PostgreSQL `scrape_logs` by exact URL to prevent redundant scraping of recently processed targets.
* **🌐 Recursive Domain Subpage Crawling:**
  * Discovers internal domain links (`/about`, `/team`, `/contact`, `/leadership`) and dispatches child tasks into Celery for parallel multi-page extraction.
* **🗄️ Thread-Safe PostgreSQL Persistence:**
  * Native PostgreSQL `ON CONFLICT DO UPDATE` (UPSERT) operations for deduplicating companies, leads, and JSONB phone structures.

---

## 🏗️ Architecture Layout

```text
OmniSpider/
├── .env.example                     # Environment template for PostgreSQL & Upstash Redis
├── requirements.txt                 # Dependencies (SQLAlchemy 2.0, Alembic, Celery, Redis, curl_cffi, nodriver, dnspython)
├── alembic.ini                      # Alembic migration configuration
├── alembic/                         # Database migration scripts
├── app/
│   ├── core/                        # Configuration & Database Sessions
│   ├── models/                      # SQLAlchemy 2.0 ORM Models (Company, Lead, ScrapeLog, Technology)
│   ├── schemas/                     # Pydantic Validation Schemas
│   ├── repositories/                # PostgreSQL Repository Layer (UPSERT & Frequency Control)
│   ├── services/scrapers/           # Scraping Engines, Email Verifier, & HTML Parser
│   └── tasks/                       # Celery Task Queue Pipeline
└── scripts/                         # CLI Scraper & Verification Test Scripts
```

---

## 🚀 Quickstart & Setup Guide

### 1. Environment Setup
```powershell
# Create & activate Python 3.12 virtual environment
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1

# Install required dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration
Copy `.env.example` to `.env` and fill in your PostgreSQL and Upstash Cloud Redis credentials:
```powershell
cp .env.example .env
```

`.env` configuration format:
```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_DB=lead_gen_db

REDIS_URL=rediss://default:your_token@your-instance.upstash.io:6379
```

### 3. Initialize Database Migrations
```powershell
python scripts/init_db.py
```

---

## 🐳 Docker Setup (PostgreSQL + Linux Multiprocessing Celery Worker)

To run **PostgreSQL** and **Celery Workers** inside a native **Linux Docker Container** (enabling multi-core Linux `prefork` process pools with Chrome headless support):

```powershell
# Build and launch PostgreSQL and Celery Worker containers
docker compose up --build -d
```

## 🧪 Usage & Testing

### Step 1: Start Celery Worker (Terminal 1)
```powershell
python -m celery -A app.tasks.celery_app worker --pool=solo -l info
```

### Step 2: Run Universal Scraper CLI (Terminal 2)

#### Scrape a single website:
```powershell
python scripts/scrape.py https://stripe.com
```

#### Scrape a website recursively (Crawling `/about`, `/team`, `/contact`):
```powershell
python scripts/scrape.py https://stripe.com --recursive
```

#### Force Tier 2 (`nodriver` CDP) for Cloudflare-protected targets:
```powershell
python scripts/scrape.py https://nowsecure.nl --tier2
```

---

## 📜 License
Licensed under the MIT License.



Here is the complete, all-in-one command guide to run your high-concurrency Celery workers on Linux (WSL / Linux Container) and seamless next steps so we can advance straight into **Phase 2 & Phase 5**.

---

### 🚀 Complete Linux Execution Guide (WSL / Linux Container)

#### **Step 1: Install Dependencies & Google Chrome in Linux Terminal**
Copy and paste this single block into your Linux (WSL) terminal:

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv curl wget libglib2.0-0t64 libnss3 libfontconfig1
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb || sudo apt-get install -f -y
```

#### **Step 2: Activate Python 3.12 Virtual Environment & Install Requirements**
```bash
cd /mnt/c/Users/Mubashar\ Ashraf/Scraper
python3 -m venv venv_wsl
source venv_wsl/bin/activate
pip install -r requirements.txt
```

#### **Step 3: Launch High-Concurrency Linux Multi-Core Celery Worker**
```bash
celery -A app.tasks.celery_app worker --concurrency=8 -l info
```
*(Leave this Linux terminal running. It will process 8 subpage scraping tasks in parallel across CPU cores!)*

---

### 🧪 How to Dispatch Jobs & Inspect Results

#### **Terminal 2 (Windows PowerShell or WSL): Dispatch Scraping Jobs**
```powershell
python scripts/scrape.py https://dreamfeed.ai/ -r -d 3
```

#### **Terminal 2: Inspect Saved Leads in PostgreSQL**
```powershell
python scripts/db_status.py
```
purge old commands on wsl 
~/.local/bin/celery -A app.tasks.celery_app purge -f
---
