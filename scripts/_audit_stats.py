import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from sqlalchemy import text
from app.core.database import SessionLocal

db = SessionLocal()
try:
    print("=== LEAD DATA QUALITY STATS ===")
    print("Total leads:", db.execute(text("SELECT COUNT(*) FROM leads")).scalar())

    corrupt = db.execute(text("""
        SELECT COUNT(*) FROM leads
        WHERE work_email ~ '(read|phone|toll|free|more|click|visit|link|info)$'
        OR work_email ~ '^(n|hi|sales|support|contact|info|hello)[a-z]'
    """)).scalar()
    print("Emails with absorbed trailing words (corrupted):", corrupt)

    print("\nLeads whose email domain != company domain:")
    rows = db.execute(text("""
        SELECT l.work_email, c.domain
        FROM leads l JOIN companies c ON c.id = l.company_id
        WHERE LOWER(SPLIT_PART(l.work_email,'@',2)) NOT LIKE '%' || c.domain
    """)).fetchall()
    print("  Count:", len(rows))
    for r in rows[:15]:
        print("   ", r[0], "-> company:", r[1])

    print("\nPersonal/free email domains (gmail, outlook, yahoo, hotmail, etc.):")
    rows = db.execute(text("""
        SELECT COUNT(*) FROM leads
        WHERE SPLIT_PART(work_email,'@',2) IN
        ('gmail.com','outlook.com','yahoo.com','hotmail.com','aol.com','icloud.com','mail.com','protonmail.com','zoho.com')
    """)).scalar()
    print("  Count:", rows)

    print("\nEmail domain frequency (top 15):")
    rows = db.execute(text("""
        SELECT SPLIT_PART(work_email,'@',2) AS dom, COUNT(*) FROM leads
        GROUP BY dom ORDER BY COUNT(*) DESC LIMIT 15
    """)).fetchall()
    for r in rows:
        print("   ", r[0], r[1])

    print("\nLeads with phones:", db.execute(text("SELECT COUNT(*) FROM leads WHERE phones::text != '[]'")).scalar())
    print("Leads with linkedin:", db.execute(text("SELECT COUNT(*) FROM leads WHERE linkedin_url IS NOT NULL")).scalar())
    print("\nLinkedIn URL frequency (top 10):")
    rows = db.execute(text("""
        SELECT linkedin_url, COUNT(*) FROM leads WHERE linkedin_url IS NOT NULL
        GROUP BY linkedin_url ORDER BY COUNT(*) DESC LIMIT 10
    """)).fetchall()
    for r in rows:
        print("   ", r[0], "->", r[1])

    print("\nFirst-name frequency (top 15):")
    rows = db.execute(text("""
        SELECT first_name, COUNT(*) FROM leads WHERE first_name IS NOT NULL
        GROUP BY first_name ORDER BY COUNT(*) DESC LIMIT 15
    """)).fetchall()
    for r in rows:
        print("   ", r[0], "->", r[1])

    print("\nVerification stats:")
    print("   email_verified=True:", db.execute(text("SELECT COUNT(*) FROM leads WHERE email_verified")).scalar())
    print("   mx_valid=True:", db.execute(text("SELECT COUNT(*) FROM leads WHERE mx_valid")).scalar())

    print("\nCompanies:")
    rows = db.execute(text("SELECT domain, name, website_url, industry, company_size FROM companies")).fetchall()
    for r in rows:
        print("   ", r)

    print("\nScrape log stats:")
    print("   total:", db.execute(text("SELECT COUNT(*) FROM scrape_logs")).scalar())
    print("   engines:", db.execute(text("SELECT engine_used, COUNT(*) FROM scrape_logs GROUP BY engine_used")).fetchall())
    print("   non-200:", db.execute(text("SELECT COUNT(*) FROM scrape_logs WHERE status_code != 200")).scalar())
    rows = db.execute(text("""
        SELECT url, COUNT(*) AS c FROM scrape_logs
        GROUP BY url HAVING COUNT(*) > 1 ORDER BY c DESC LIMIT 10
    """)).fetchall()
    print("   Most re-scraped URLs (same URL twice+):")
    for r in rows:
        print("   ", r[1], "x", r[0])
except Exception as e:
    import traceback
    traceback.print_exc()
finally:
    db.close()
