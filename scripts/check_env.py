"""Environment smoke check for OmniSpider.

Run this before any scrape session or after pulling new code:
    venv\\Scripts\\python.exe scripts\\check_env.py

Exits 0 when every critical dependency and service is reachable, 1 otherwise.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

FAILURES = []


def check_import(module_name: str) -> None:
    try:
        __import__(module_name)
        print(f"  [OK]   import {module_name}")
    except Exception as exc:
        FAILURES.append(module_name)
        print(f"  [FAIL] import {module_name}: {exc}")


def check_app_imports() -> None:
    for module in (
        "app.core.config",
        "app.core.database",
        "app.core.redis",
        "app.models",
        "app.services.scrapers.parser",
        "app.services.scrapers.tier1_http",
        "app.services.scrapers.tier2_cdp",
        "app.services.scrapers.email_verifier",
        "app.tasks.celery_app",
        "app.tasks.scrape_tasks",
    ):
        check_import(module)


def check_database() -> None:
    from sqlalchemy import text
    from app.core.database import engine

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("  [OK]   PostgreSQL connection")
    except Exception as exc:
        FAILURES.append("postgresql")
        print(f"  [FAIL] PostgreSQL connection: {exc}")


def check_redis() -> None:
    from app.core.redis import get_redis_client

    try:
        get_redis_client().ping()
        print("  [OK]   Redis connection")
    except Exception as exc:
        FAILURES.append("redis")
        print(f"  [FAIL] Redis connection: {exc}")


def main() -> int:
    print("=" * 60)
    print(" OmniSpider Environment Smoke Check")
    print("=" * 60)

    print("\nThird-party packages:")
    for package in (
        "bs4", "curl_cffi", "nodriver", "celery", "redis", "sqlalchemy",
        "alembic", "pydantic", "dns", "tldextract", "phonenumbers",
        "nameparser", "aiosmtplib", "email_validator",
    ):
        check_import(package)

    print("\nApplication modules:")
    check_app_imports()

    print("\nServices:")
    check_database()
    check_redis()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f" RESULT: FAIL ({len(FAILURES)} problem(s)): {', '.join(FAILURES)}")
        print(" Fix: venv\\Scripts\\pip.exe install -r requirements.txt")
        return 1
    print(" RESULT: PASS - environment is ready to scrape")
    return 0


if __name__ == "__main__":
    sys.exit(main())
