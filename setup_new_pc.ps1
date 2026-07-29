# OmniSpider One-Click Setup Script for New PC
# Usage: .\setup_new_pc.ps1

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " 🛠️ OMNISPIDER ONE-CLICK NEW PC ENVIRONMENT SETUP" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. Create Python 3.12 Virtual Environment
if (-not (Test-Path "venv")) {
    Write-Host "`n1. Creating Python 3.12 Virtual Environment (venv)..." -ForegroundColor Green
    py -3.12 -m venv venv
} else {
    Write-Host "`n1. Virtual Environment 'venv' already exists." -ForegroundColor Yellow
}

# 2. Install Dependencies
Write-Host "`n2. Installing dependencies from requirements.txt..." -ForegroundColor Green
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Create .env if missing
if (-not (Test-Path ".env")) {
    Write-Host "`n3. Creating default .env configuration file..." -ForegroundColor Green
    @"
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=123
POSTGRES_DB=lead_gen_db

REDIS_URL=rediss://default:gQAAAAAAAfIEAAIgcDEyODg0MTAxYzM3OGI0Yzc1YTZlZDBmMDU1OGI3NDFjOQ@neutral-earwig-127492.upstash.io:6379
"@ | Out-File -FilePath ".env" -Encoding utf8
} else {
    Write-Host "`n3. File '.env' already exists." -ForegroundColor Yellow
}

# 4. Start Docker Containers
Write-Host "`n4. Starting Docker Containers (PostgreSQL + Linux Celery Worker)..." -ForegroundColor Green
docker compose up --build -d

# 5. Run Database Migrations
Write-Host "`n5. Running Database Migrations..." -ForegroundColor Green
.\venv\Scripts\python.exe scripts/init_db.py

Write-Host "`n======================================================================" -ForegroundColor Cyan
Write-Host " 🎉 SETUP COMPLETE! OmniSpider is ready on your new PC." -ForegroundColor Green
Write-Host " Run your scraper anytime: .\venv\Scripts\python.exe scripts/scrape.py https://stripe.com --recursive" -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Cyan
