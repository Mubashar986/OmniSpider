# Lead Generation Scraper — Data Quality & System Audit Report

**Project:** B2B Lead Generation Scraper (Clutch / GoodFirms directories)
**Goal:** Automatically discover companies that buy custom software development services and collect decision-maker contact data for the sales team.
**Scope of this report:** Full analysis of the scraping pipeline + live database inspection (all tables), identification of data-parsing problems, and a prioritized improvement plan.
**Date:** July 31, 2026

---

## 1. Executive Summary

The system **fetches pages exceptionally well** (189 of 190 scrapes succeeded; the one failure was a WAF block caused by our own aggressive re-crawling). The engineering foundation — tiered anti-bot scraping, Celery pipeline, Redis deduplication, atomic PostgreSQL UPSERTs — is production-grade.

However, the **end product is not yet a lead database**. Of 432 saved "leads":

- **~7 are genuinely usable B2B contacts** (emails of outsourcing companies like `sales@openxcell.com`)
- **246 are personal Gmail/Outlook addresses** of random reviewers who commented on directory pages
- **16 are corrupted emails** produced by a regex bug (e.g. `sales@jploft.comphone`)
- **0 phone numbers were ever saved** — a confirmed regex bug discards every match
- **2 companies exist in the database — and both are the directories themselves** (clutch.co, goodfirms.co). The ~400 real target companies were never created; all leads are attached to the wrong company.

**Verdict:** The machine runs. The data pipeline that fills it needs fixing. All issues are localized in the parsing/attribution layer and are fixable without touching the scraping engine.

---

## 2. System Overview (What Was Built)

```
URL → Tier 1 fetch (curl_cffi TLS spoofing)
    → Tier 2 fallback (nodriver real browser) if blocked
    → HTML parse (emails, phones, LinkedIn, tech stack, internal links)
    → Email verification (syntax + disposable list + DNS MX)
    → PostgreSQL UPSERT (companies, leads, company_technologies)
    → Recursive subpage crawl (Celery + Redis session dedup)
    → Every attempt logged to scrape_logs
```

Database tables: `companies`, `leads`, `company_technologies`, `scrape_logs`, `alembic_version`.

---

## 3. Database Findings — Field by Field

### 3.1 `companies` (2 rows) — 3 of 7 fields wrong, 2 never filled

| Field | Status | Finding |
|---|---|---|
| `domain` | ❌ WRONG | Uses the **directory's** domain (`clutch.co`, `goodfirms.co`) instead of the target company's domain (e.g. `openxcell.com`). |
| `name` | ❌ WRONG | Derived from the URL domain → "Clutch", "Goodfirms". Real company names are never extracted from profile pages. |
| `website_url` | ❌ WRONG | Overwritten on every subpage crawl; currently holds profile URLs with query strings (`.../company/openxcell?sort_by=rating_asc`). |
| `industry` | ❌ NEVER POPULATED | NULL in 100% of rows. No code path exists. |
| `company_size` | ❌ NEVER POPULATED | NULL in 100% of rows. No code path exists. |
| `created_at` / `updated_at` | ✅ OK | Correct. |

### 3.2 `leads` (432 rows) — 6 of 9 fields broken

| Field | Status | Finding |
|---|---|---|
| `company_id` | ❌ WRONG | All 432 leads point to the 2 directory companies; real target companies were never created. |
| `first_name` | ❌ GARBAGE | Derived from the email prefix: "Hello" ×15, "Support" ×40, "Sales" ×14, "Info" ×30, plus Gmail usernames like "Harrykeller4334". Not real names. |
| `last_name` | ❌ mostly NULL | 428/432 NULL; the 4 present are garbage (e.g. "Wallace Gdaygroup"). |
| `title` | ❌ NEVER POPULATED | 432/432 NULL. Schema field exists; no extraction code. |
| `work_email` | ⚠️ PARTLY BROKEN | 16 corrupted (regex bug), 246 personal Gmail/Outlook (not B2B), only ~7 usable. |
| `phones` | ❌ BROKEN | 0/432. **Confirmed regex bug — every phone number is discarded.** |
| `linkedin_url` | ❌ WRONG ASSOCIATION | 426/432 are unrelated profiles (140 leads share one reviewer's profile; 18 share clutch.co's own LinkedIn). |
| `email_verified` / `mx_valid` | ⚠️ MISLEADING | 418/432 "True" — but this only proves the email domain has MX records (all Gmail passes). Not proof of a valid B2B contact. |
| `disposable_flag` | ⚠️ ineffective | Always False; the hardcoded list doesn't cover Gmail/Outlook, which are the real junk source for B2B. |

### 3.3 `company_technologies` (5 rows)

- ✅ Detection regexes work (Next.js, Google Analytics, HubSpot correctly detected).
- ❌ But they describe the **directory sites**, not the target companies.
- ❌ Stale technologies are never removed (only inserted, never synced).
- ⚠️ `category` is a hardcoded constant ("Scraped Stack").

### 3.4 `scrape_logs` (190 rows) — the only fully correct table ✅

URLs, domains, status codes, engine used, error messages, timestamps are all accurate. 185 curl_cffi + 5 nodriver; 1 failure (403 WAF on GoodFirms).

### 3.5 Crawling strategy issues (visible in logs)

- **Query-param dedup failure:** the same profile page re-crawled up to 7× with different query strings (`sort_by`, `verified`, `location`, `project_cost`, `filter_by_service`, `page`). ~90 unique pages generated 190 log rows.
- **Pagination explosion:** `?page=2,3,6,16,180` all crawled — not blocked.
- **Low-value pages crawled:** terms, privacy, advertise, get-listed, press-releases, blog posts.
- **Reviewer email pollution:** directory/blog pages contain user review comments — the parser ingests those personal emails as leads (source of the 246 Gmail addresses).
- **WAF block triggered by our own behavior:** repeated variant-crawling of the same profile got GoodFirms to block us (the single 403 in logs).

---

## 4. Root-Cause Analysis — Confirmed Bugs

### Bug 1: Phone numbers can never be saved (critical)
`PHONE_REGEX` uses a capturing group, and `re.findall()` returns only the captured group (the optional country code) instead of the full match:
```python
PHONE_REGEX = re.compile(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
# findall("+1 (415) 555-0123") -> ['+1 ', '', '']   <- only groups, not full numbers
```
Result: `"".join(match)` is never ≥10 characters → **every phone number in every scrape is silently dropped**.
Fix: non-capturing groups `(?:...)` or `re.finditer()` + `match.group(0)`.

### Bug 2: Corrupted emails saved to DB (high)
`EMAIL_REGEX` has no word boundaries and a greedy TLD:
```python
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
```
Verified behavior: `sales@jploft.comphone: +1...` → matches `sales@jploft.comphone` (TLD absorbs "phone"); `...nhello@crafton.euread-more` → matches `nhello@crafton.euread` (leading letter absorbed, TLD absorbs "read"). This produced 16 corrupted rows.
Fix: add `\b` boundaries and validate against a real TLD list.

### Bug 3: Wrong company attribution (critical)
The parser keys the company record on **the URL being scraped** (the directory) rather than **the company described on the page**. Profile pages contain the company's real name, website and domain — none of it is extracted. All leads from Clutch/GoodFirms profiles therefore attach to clutch.co/goodfirms.co.

### Bug 4: No lead-quality filtering (critical for B2B goal)
Every email on the page is ingested — including reviewer comments and the directory's own emails (`hello@clutch.co`, `leah@clutch.co`). There is no check that the email's domain matches the target company, no rejection of personal mail providers (Gmail/Outlook/Yahoo), no confidence scoring.

### Bug 5: LinkedIn assigned blindly (high)
`linkedin_urls[0]` — the first LinkedIn URL found anywhere on the page — is assigned to **every** lead on that page. 426 of 432 stored LinkedIn URLs belong to unrelated people/companies.

### Bug 6: Company fields overwritten on every crawl (medium)
`website_url` is re-set on every subpage upsert, so it churns between profile URLs instead of stabilizing at the company's real website.

### Bug 7: No dedup on query-parameter variants (medium)
URL canonicalization only strips `utm_/fbclid/gclid`, so `?sort_by=...`, `?location=...`, `?page=N` variants bypass the Redis session dedup → duplicate crawling → wasted bandwidth + WAF risk.

---

## 5. What Is Working Well (Keep It) ✅

1. **Fetching layer: 99.5% success** — TLS spoofing + browser fallback is the hardest part of scraping and it works.
2. **Block detection** — Cloudflare/Turnstile indicators correctly identified.
3. **Tiered fallback** — nodriver engaged when needed; only 1 true failure.
4. **Email verification logic** — syntax + MX checks are correct (corrupted emails were correctly flagged unverified).
5. **UPSERT deduplication** — no duplicate emails among 432 rows; unique constraints hold.
6. **Technology detection** — signature regexes work on real pages.
7. **Internal-link extraction** — priority ordering for about/team/contact pages works.
8. **Scrape logging** — complete and accurate; invaluable for debugging (it's how we found the WAF issue).
9. **Schema & migrations** — clean and applied.

---

## 6. What the Data Should Look Like (Definition of Done)

For our goal — **selling custom software development** — a lead is:

> A company that plausibly buys custom software (or outsources it), identified by its **own domain**, with a **contact email on that domain** (sales@/info@/hello@ + ideally a decision-maker), **real name** of the company, and ideally **LinkedIn + phone + title**.

- Target company = the one named on the Clutch/GoodFirms profile → must become a `companies` row keyed by its real domain.
- Email must match the target company's domain → otherwise flagged/dropped.
- Personal providers (gmail.com, outlook.com, yahoo.com, hotmail.com...) → rejected or deprioritized.
- Corrupted regex artifacts → impossible (after Bug 2 fix).
- Phones → actually stored (after Bug 1 fix).
- LinkedIn → only the profile-page's own company LinkedIn, or per-person links near contact blocks.

---

## 7. Prioritized Improvement Plan

| # | Priority | Fix | Impact |
|---|---|---|---|
| 1 | P0 | Fix phone regex (non-capturing groups) | Unlocks all phone data immediately |
| 2 | P0 | Company attribution: extract real name/domain/website from profile pages; key companies by real domain | 432 leads re-associate to ~400 real companies |
| 3 | P0 | Email quality filter: domain-match against target company + reject personal providers | Removes ~250 junk leads automatically |
| 4 | P0 | Fix email regex (word boundaries) | Stops corrupted emails |
| 5 | P1 | LinkedIn: associate only links in the page's contact block / company's own LinkedIn | 426 wrong URLs fixed |
| 6 | P1 | Canonicalize URLs by stripping `page/sort_by/location/project_cost/filter_by_service/verified` params | ~2× fewer crawls, avoids WAF bans |
| 7 | P1 | Extract `title` from profile pages (Clutch/GoodFirms profiles carry it in HTML) | Fills the empty field |
| 8 | P2 | Extract `industry` + `company_size` from profile data | Fills empty company fields |
| 9 | P2 | Tech-stack sync (remove stale technologies on re-scrape) | Accurate technographics |
| 10 | P2 | Add robots/domain-blocklist for terms/privacy/junk pages | Cleaner crawl scope |

---

## 8. Success Metrics (How We'll Know It's Fixed)

| Metric | Today | Target |
|---|---|---|
| Leads with email on target company's domain | ~7 / 432 (1.6%) | > 80% |
| Corrupted emails in DB | 16 | 0 |
| Personal-email leads | 246 (57%) | < 5% |
| Leads with phones | 0 | > 50% |
| Leads with correct LinkedIn | ~3 | > 80% |
| Companies rows (real targets) | 2 (wrong) | 1 per target company |
| `leads.title` populated | 0% | > 60% |
| Re-crawls per unique page | up to 7× | ≤ 1.1× |
| Scrape success rate | 99.5% | keep ≥ 95% |

---

## 9. Bottom Line

The system is an **excellent scraper foundation and a premature lead engine**. 80% of the engineering (fetching, fallback, orchestration, storage, logging) is done and done well; the missing 20% — **parsing, attribution, and quality filtering** — determines the value of 100% of the output. All required fixes are localized and well-understood; none require redesigning the scraping engine.

Priority order when resuming work: **P0 fixes 1–4 first**, then measure against the success metrics above before moving on to new tasks.
