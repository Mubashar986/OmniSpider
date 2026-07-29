# OmniSpider One-Click Git Commit & Push PowerShell Script
# Usage: .\push_to_github.ps1 ["Optional commit message"]

param (
    [string]$commitMessage = "Update OmniSpider codebase: Docker setup, Celery workers, and recursive domain crawling"
)

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " 🚀 OMNISPIDER ONE-CLICK GIT PUSH TO GITHUB" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# Ensure script is executed in project root
if (-not (Test-Path ".git")) {
    Write-Host "Initializing Git Repository..." -ForegroundColor Yellow
    git init
}

# Configure remote origin if missing
$remoteUrl = "https://github.com/Mubashar986/OmniSpider.git"
$existingRemote = git remote get-url origin 2>$null
if (-not $existingRemote) {
    Write-Host "Adding Remote Origin: $remoteUrl" -ForegroundColor Yellow
    git remote add origin $remoteUrl
}

# Stage all files (.gitignore automatically excludes .env, venv, .agents, etc.)
Write-Host "`n1. Staging project files..." -ForegroundColor Green
git add .

# Check if there are changes to commit
$status = git status --porcelain
if ($status) {
    Write-Host "2. Committing changes: '$commitMessage'" -ForegroundColor Green
    git commit -m "$commitMessage"
} else {
    Write-Host "2. No new changes to commit." -ForegroundColor Yellow
}

# Rename branch to main
Write-Host "3. Setting branch to main..." -ForegroundColor Green
git branch -M main

# Push to GitHub
Write-Host "4. Pushing to GitHub repository ($remoteUrl)..." -ForegroundColor Green
git push -u origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n======================================================================" -ForegroundColor Cyan
    Write-Host " ✅ SUCCESS: All codebase changes successfully pushed to GitHub!" -ForegroundColor Green
    Write-Host "======================================================================" -ForegroundColor Cyan
} else {
    Write-Host "`n❌ Error encountered during git push. Please check output above." -ForegroundColor Red
}
