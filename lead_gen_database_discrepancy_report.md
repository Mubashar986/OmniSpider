# lead_gen_db — Database Discrepancy & Data Quality Report

**Scope:** Full audit of all tables in `lead_gen_db` against the current OmniSpider implementation (`app/models`, `app/repositories`, `app/tasks/scrape_tasks.py`, `alembic/versions`).
**Audit date:** 2026-08-02 (data collected 2026-08-01, 16:19–20:44 UTC)
**Database size:** ~9.6 MB · **Server:** localhost:5432 · **User:** postgres
**Report type:** Findings only — no implementation recommendations.

---

## Executive Summary

The database is structurally healthy (no orphan rows, no constraint violations, no duplicate primary keys) but contains **systemic data-quality issues originating from the scraping pipeline**. The core problem: the system scrapes the **GoodFirms directory** (`goodfirms.co`) and stores directory-profile data as if it were company/employee data. This produces:

| Finding | Severity |
|---|---|
| 97.4% of all leads come from a single directory domain (`goodfirms.co`) | 🔴 High |
| 44.5% of "work emails" are free personal providers (671 Gmail) | 🔴 High |
| Only 39/1552 emails (2.5%) match the stored company's domain | 🔴 High |
| "Employee" names are directory usernames (digits/handles), not real names | 🔴 High |
| `industry` field stores raw unparsed "Industry Focus…%" strings | 🔴 High |
| `company_size` field stores scraped page text ("Browse all 60+ services") | 🔴 High |
| 1477/1552 leads (95%) have no job title; 9 distinct titles total | 🟠 Medium |
| 100% of scraped URLs are from a single domain | 🟠 Medium |
| 216 duplicate URL scrapes logged (cooldown off by default) | 🟠 Medium |
| Phone numbers duplicated across 72 leads (same 5 numbers shared) | 🟠 Medium |
| 480 duplicate LinkedIn URLs | 🟡 Low |
| `extra_metadata` is empty JSONB `{}` on all 48 companies | 🟡 Low |
| 8 companies have zero leads | 🟡 Low |

---

## 1. Table-by-Table Audit

### 1.1 `companies` (48 rows)

| Metric | Value |
|---|---|
| Total rows | 48 |
| Distinct domains (case-insensitive) | 48 |
| Mixed-case domains | 0 |
| Missing name | 0 |
| Missing industry | 4 (8.3%) |
| **Industry in raw "Industry Focus…" format** | **44 (91.7%)** |
| Missing company_size | 0 |
| **company_size = scraped page text ("Browse all 60+ services")** | **48 (100%)** |
| Missing website_url | 0 |
| **website_url doesn't match domain** | **22 (45.8%)** |
| `updated_at < created_at` (inverted timestamps) | 0 |
| Domains with URL noise (`http`, `www.`) | 0 |
| `extra_metadata` = `{}` | **48 (100%)** |
| `extra_metadata` populated | 0 |
| Companies with 0 leads | 8 |

**Discrepancy 1.1.1 — `industry` is raw scraped text (HIGH)**
91.7% of companies store the full scraped string as industry, e.g.:
`Industry FocusBusiness Services-50%E-commerce-40%`
The `industry` column (String 255) is meant for a clean category; values exceed 100 chars in some cases (255-char cap risk) and are unusable for grouping/filtering.

**Discrepancy 1.1.2 — `company_size` is scraped page text (HIGH)**
All 48 rows: `company_size = "Browse all 60+ services"` — this is a UI label scraped from the directory page, not a company size. The field (String 100) contains zero usable company-size data.

**Discrepancy 1.1.3 — `website_url` vs `domain` mismatch (HIGH)**
45.8% of companies have a `website_url` whose host does not contain the stored `domain`. Example: `domain=paperboat.webstarts.com` while the real website is different. Root cause: `domain` is derived from the directory page URL (e.g. `goodfirms.co/company/paperboat-marketing`), while `website_url` points to the real company site. The two fields describe different entities.

**Discrepancy 1.1.4 — `extra_metadata` never populated (LOW)**
All 48 companies have `extra_metadata = '{}'`. The JSONB column (introduced by migration `003_add_extra_metadata`) is written but the parsed metadata never lands in it. The task returns `detected_tech` but this data goes to `company_technologies`, leaving `extra_metadata` empty.

**Discrepancy 1.1.5 — 8 companies with zero leads (LOW)**
`paperboat.webstarts.com`, `taazaa.com`, `splitdev.com`, `gearheart.io`, `dvchain.co`, `kronosresearch.com`, `rootstrap.com`, `propertify.ae`. These were upserted (company created) but no leads were parsed/extracted for them. Indicates lead extraction yielded nothing on those pages.

**Schema vs model check:** `idx_companies_domain` UNIQUE on `domain` — present ✓. No FK problems (all companies referenced validly).

---

### 1.2 `leads` (1,552 rows)

| Metric | Value |
|---|---|
| Total rows | 1,552 |
| Unique work_email (exact) | 1,552 |
| Duplicate work_emails | 0 |
| Orphan rows (company_id NULL or dangling) | 0 |
| Mixed-case emails | 0 |
| Emails failing basic regex format | 0 |
| `phones` NULL | 0 |
| `phones` = `[]` | **1,480 (95.4%)** |
| `phones` populated | 72 (4.6%) |
| **first_name containing digits** | **426 (27.5%)** |
| **first_name = role word (info/admin/sales/contact…)** | **532 (34.3%)** |
| `email_verified` true + `mx_valid` false (inconsistent) | 0 |
| `email_verified` false + `mx_valid` true (inconsistent) | 0 |
| `linkedin_url` NULL | 142 |
| Duplicate linkedin_url | **480** |
| non-LinkedIn domain in linkedin_url | 0 |
| title NULL | **1,477 (95.2%)** |
| Distinct titles | 9 |
| `created_at = updated_at` (never updated) | **1,552 (100%)** |
| Activity days (distinct date_trunc day) | 2 |

**Discrepancy 1.2.1 — Email domain ↔ company domain mismatch (HIGH)**
Only **39 of 1,552 (2.5%)** emails share their domain with the company row. The remaining 1,513 leads are directory-profile emails attached to `goodfirms.co` or other directory-listed companies whose real domain differs. Example: company=`goodfirms.co`, email=`tim@fugo.ai`, `sales@procore.com`, `info@eurekos.com`.

**Discrepancy 1.2.2 — 44.5% free personal emails (HIGH)**
| Provider | Leads |
|---|---|
| gmail.com | 671 |
| yahoo.com / outlook.com / hotmail.com / gmx.net / seznam.cz | 21 |
| **Total free** | **691 (44.5%)** |
| Corporate domains | 859 |
| Distinct email domains | 840 |

**Discrepancy 1.2.3 — first_name is a username handle (HIGH)**
27.5% of first names contain digits; 34.3% are role words. Real examples: `057Priyathakur`, `Macstyle27`, `Aalleex992`, `Bogguswowuso63Yahoo`, `Aditya69Choudhary69`, `Bezverkhovbeilfmwsds8`. These are directory account handles mapped to first_name — not employee identities.

**Discrepancy 1.2.4 — Title data missing/inconsistent (MEDIUM)**
1,477/1,552 have NULL title. The 75 non-null titles use only 9 values — and are inconsistent with reality: `support@mooninvoice.com → "Founder"`, `sales@procore.com → "Managing Director"`, `me@memate.com.au → "Director"`. Title/email pairs don't correlate.

**Discrepancy 1.2.5 — Phone numbers duplicated across leads (MEDIUM)**
All 72 phone-populated leads share the same core numbers:
`+1 833-433-1867` (72×), `+1 415-376-9457` (72×), `+1 769-703-1625` (70×), `+1 208-267-5656` (66×), `+1 714-714-6767` (24×), `+44 1562 446262` (14×).
These are company-level (or directory-level) contact numbers repeated onto every lead — not per-person numbers.

**Discrepancy 1.2.6 — Duplicate LinkedIn URLs (LOW)**
480 duplicate `linkedin_url` values across 1,552 leads (e.g. same `linkedin.com/company/…` assigned to many leads). 260 rows use a short company-slug form `linkedin.com/company/<10-15 chars>` — company page, not person profile.

**Discrepancy 1.2.7 — All leads never updated (LOW)**
`created_at = updated_at` for 100% of rows. No upsert re-writes occurred (or `onupdate` never fired) — every lead is a first-insert.

**Verification consistency:** positive ✓ — no rows where `email_verified` contradicts `mx_valid`; the 59 unverified all have `mx_valid=false`.

---

### 1.3 `company_technologies` (142 rows)

| Metric | Value |
|---|---|
| Total rows | 142 |
| Distinct tech_names | 13 |
| Companies with ≥1 tech | 48 (100%) |
| Category NULL | 0 |
| **Category = "Scraped Stack" (single bucket)** | **142 (100%)** |
| Duplicate (company_id, tech_name) | 0 (unique constraint enforced ✓) |

| Top technologies | Companies |
|---|---|
| Google Analytics | 48 |
| Next.js | 48 |
| Laravel | 11 |
| Salesforce | 11 |
| Django | 8 |
| HubSpot / Shopify | 4 each |
| Intercom / Tailwind CSS | 2 each |
| Webflow / Marketo / WordPress / Cloudflare | 1 each |

**Discrepancy 1.3.1 — Uniform detection pattern (MEDIUM)**
Google Analytics and Next.js are detected on **100% of companies** (48/48). Combined with identical `category='Scraped Stack'` on all rows, the detection signature is suspicious — either the parser defaults to a fixed tech list, or the detection rules are too broad (e.g. matching boilerplate HTML shared across directory pages).

**Discrepancy 1.3.2 — Category cardinality = 1 (LOW)**
The `category` column (intended taxonomy) contains exactly one value. No categorization occurred despite the column existing.

**Constraint check:** `uq_company_tech (company_id, tech_name)` UNIQUE present ✓. FK → companies ✓ (0 orphans).

---

### 1.4 `scrape_logs` (1,109 rows)

| Metric | Value |
|---|---|
| Total rows | 1,109 |
| Distinct URLs | 893 |
| **Duplicate URL scrapes** | **216 (19.5%)** |
| URLs without protocol | 0 |
| status_code NULL | 0 |
| status_code = 0 (connection/session failure) | 1 |
| engine_used NULL | 0 |
| engine_used unknown value | 0 |
| error_message present | 483 |
| Future scraped_at | 0 |

| Status code | Count |
|---|---|
| 200 | 626 (56.4%) |
| **403 (Cloudflare/WAF blocked)** | **482 (43.5%)** |
| 0 | 1 |

| Engine | Scrapes | Success | Failures |
|---|---|---|---|
| nodriver | 788 | 305 (38.7%) | 482×403 + 1×session error |
| curl_cffi:chrome120 | 163 | 163 (100%) | 0 |
| curl_cffi:chrome124 | 158 | 158 (100%) | 0 |

| Distinct scraped domains | 1 (`goodfirms.co`) |
|---|---|
| URL/domain-column mismatch | 3 (`www.goodfirms.co` vs `goodfirms.co`) |

**Discrepancy 1.4.1 — Single-domain coverage (HIGH)**
100% of scrape_logs are `goodfirms.co` subpages. The entire production dataset comes from one directory site; no other domain was ever scraped through this pipeline.

**Discrepancy 1.4.2 — Duplicate scrapes (MEDIUM)**
216 duplicate URL scrapes (19.5%). The 7-day cooldown is **off by default** (`enable_cooldown=False` in `scrape_url_task`); identical URLs like `goodfirms.co/contact-us` (12×), `/about-us` (10×), `/project-management-software` (10×) were fetched repeatedly in one session.

**Discrepancy 1.4.3 — Tier-2 fallback majority (MEDIUM)**
788/1,109 scrapes (71%) used the nodriver CDP engine, and 61% of those failed with `Cloudflare Turnstile or WAF challenge unresolved`. Meanwhile curl_cffi (both fingerprints) had 100% success but was used only 29% of the time. The engine that succeeds is used less than the engine that fails.

**Discrepancy 1.4.4 — `www.` prefix inconsistency (LOW)**
3 rows log `www.goodfirms.co` in the URL while `domain='goodfirms.co'`; domain extraction strips `www` in most but not all cases.

**Schema check:** index `idx_scrape_logs_domain_scraped_at` present ✓.

---

### 1.5 `alembic_version`

| Metric | Value |
|---|---|
| version_num | `003_add_extra_metadata` |
| Migration files on disk | 001_initial_schema, 002_company_tech_unique, 003_add_extra_metadata |
| **Drift** | **None — schema is at head ✓** |

All constraints/indexes from migrations verified present in the live DB:
- `companies`: UNIQUE idx on `domain` ✓
- `leads`: UNIQUE idx on `work_email` ✓
- `company_technologies`: UNIQUE (company_id, tech_name) ✓, FK ✓
- `leads.company_id` FK ✓
- No missing CHECK/NOT NULL constraints observed.

---

## 2. Cross-Table Integrity

| Check | Result |
|---|---|
| Orphan leads (dangling company_id) | 0 ✓ |
| Orphan technologies | 0 ✓ |
| Companies referenced by leads | 40/48 |
| Leads per company distribution | 1 company with 1,511 · 2 companies with 2 · 37 companies with 1 · 8 companies with 0 |
| Email domain ↔ company domain match | 39/1,552 (2.5%) |
| scrape_logs domain ↔ companies.domain join coverage | only `goodfirms.co` exists in both |

**Discrepancy 2.1 — Company entity confusion (HIGH)**
The pipeline treats each directory profile page as a "company" and each profile's registered contact as a "lead". Evidence: 37 companies with exactly 1 lead, and those leads' emails belong to third-party domains (`tim@fugo.ai` under company `goodfirms.co`). The company↔lead relationship does not represent employer↔employee.

---

## 3. Implementation-Behavior Observations (what the code does vs. what's stored)

These describe how the current implementation produces the stored state (no recommendations):

1. `scrape_url_task` dispatches recursive subpage tasks with `crawl_depth` decrementing — leading to the same directory URL being enqueued from multiple parents; combined with `enable_cooldown=False` default, duplicates are logged (216).
2. Cooldown check (`was_scraped_recently`) exists but is opt-in; the audit data shows it was never active during collection.
3. Task logs every scrape attempt — including the 482 blocked pages (status logged, pipeline returns early, but still counted).
4. Tier selection: Tier 1 (curl_cffi) first, fallback to Tier 2 (nodriver) only when Tier 1 fails/blocked. In the data, nodriver dominates — consistent with Tier 1 failing or being skipped for this target.
5. `upsert_company`/`upsert_lead` (ON CONFLICT) — verified no duplicate keys in DB; the UNIQUE indexes made this safe.
6. Email verification writes `email_verified`/`mx_valid`/`disposable_flag` together — DB shows zero contradictory rows ✓.
7. `company_size`, `industry`, `extra_metadata` are written from the parsed schema — the raw "Industry Focus…"/"Browse all 60+ services" strings indicate the parser passed unparsed page text into structured columns.
8. Recursive crawling stays within the source domain (internal link extraction) — hence 100% `goodfirms.co` coverage.
9. `paperboat.webstarts.com` as a stored domain shows the parser captured a profile-page host, not the canonical company domain.
10. Every lead is a first insert (`created_at = updated_at`) — no re-scrape ever updated an existing lead during the observed window.

---

## 4. Severity Rollup

| Severity | Count | Findings |
|---|---|---|
| 🔴 High | 7 | 1.1.1, 1.1.2, 1.1.3, 1.2.1, 1.2.2, 1.2.3, 1.4.1, 2.1 |
| 🟠 Medium | 6 | 1.2.4, 1.2.5, 1.3.1, 1.4.2, 1.4.3 |
| 🟡 Low | 6 | 1.1.4, 1.1.5, 1.2.6, 1.2.7, 1.3.2, 1.4.4 |

---

## 5. Data Provenance Summary

- All 1,109 scrape attempts target `goodfirms.co` subpages (directory, category, software, and profile URLs).
- All 1,552 leads were created in a single ~4.5h window (16:19–20:44 UTC, 2026-08-01), in 4 hour-buckets (21:00, 00:00, 23:00, 01:00 UTC) — a single batch run, not continuous collection.
- 48 companies were created in the same run; 8 never yielded leads.
- Email verification: 1,493 verified / 59 unverified, all consistent with MX results.
- Backup of this database (pre-audit): `backups/pg_backup_2026-08-01/` (JSON per table) + `corporate_email_leads.csv` (859 rows).

---

*Report generated from live queries against `lead_gen_db` using the postgres MCP server. Findings-only; no remediation proposed.*
