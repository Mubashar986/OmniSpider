# Post-Fix Verification Report — P3.1 Phone & Email Extraction Fix

**Date:** July 31, 2026
**Scope:** Live-run verification of the Pre-P3.1 fix (phone regex + email regex hardening in `app/services/scrapers/parser.py`) against the production pipeline.
**Method:** Celery worker executed on Windows (`--pool=solo`), live log capture via process monitor, database analysis via PostgreSQL MCP server, ~15 minutes of continuous monitoring while the scraper ran from a separate terminal.

---

## 1. Execution Summary

| Item | Value |
|---|---|
| Worker | `celery -A app.tasks.celery_app worker --pool=solo -l info` (Windows, PID 19120) |
| Redis broker | Upstash Cloud (rediss) — connected OK |
| Tasks registered | `tasks.ping_test`, `tasks.scrape_url_task` |
| Monitoring window | 17:14 → 17:29 local (~15 min) |
| Database | `lead_gen_db` @ localhost:5432 (env fix: `POSTGRES_PASSWORD=123 → 1234`) |
| Crawl session observed | Session `5a9ca462...` — clutch.co (depth 2) |

---

## 2. Did the Fix Have an Effect? — YES ✅

### 2.1 Phone numbers: 0 → saved (fix verified live)

| Metric | Before Fix | After Fix |
|---|---|---|
| Leads with phones in DB | **0 / 432 (0%)** | **6 / 438 (1.4%)** |
| Example real phone captured | — | `+1 631-486-7589` (contact@dotlogics.com) |

The `re.findall()` capturing-group bug is confirmed dead — phones now flow into the `phones` JSONB column.

### 2.2 Email corruption: original patterns eliminated ✅

Old corruption patterns (`sales@jploft.comphone`, `contact@controlf5.inread`, `nhello@crafton.euread`, `sales@loungelizard.comtoll`) **no longer occur** — verified both in live logs and by regex unit testing:

```
C comphone: ['sales@jploft.com']   ← fixed (was sales@jploft.comphone)
D inread:   ['contact@controlf5.in'] ← fixed (was contact@controlf5.inread)
```

### 2.3 Pipeline health during monitoring

| Metric | Before | During/After |
|---|---|---|
| Scrape attempts logged | 190 | **243** (+53) |
| Scrape failures (non-200) | 1 | **1** (unchanged — old GoodFirms 403; zero new blocks) |
| Tier-2 fallback usage | 5 | +2 nodriver runs, both 200 OK |
| New leads saved | — | **+6** (432 → 438) |
| New companies | 2 | 2 (same — attribution not yet fixed, expected) |

---

## 3. New Issues Discovered During Live Monitoring ⚠️

### Issue A: Email TLD truncation (introduced by fix)
`EMAIL_REGEX` fallback branch `[a-zA-Z]{2,4}` **truncates TLDs longer than 4 letters**:
- Real: `hi@goodface.agency` → Stored: **`hi@goodface.agen`** (live DB row, unverified)
- Verified by test: `.agency` → `.agen`

### Issue B: Residual dot-absorption
Subdomain-style suffix still matches because `.` + short fallback TLD is accepted:
- Page had `contact@dotlogics.com` → also stored **`contact@dotlogics.com.read`** (unverified)
- Verified by test: `contact@dotlogics.com.read` still matches

### Issue C: Phone noise (new — phonenumbers matcher too greedy)
`PhoneNumberMatcher(html, "US")` matches **any 10+ digit sequence in the page**, including tracking IDs, timestamps and JSON numbers:
- `hi@goodface.agen` got **18 "phones"** — almost all junk (`1005000000000`, `8602023316903`, `1079324124`...)
- `hello@adchitects.co` got 8 phones — only a fraction are real contact numbers
- Only the regex-fallback captures (`+1 631-486-7589`) look genuinely valid
- **Suggestion:** restrict matcher to `mailto:`/`tel:` links + visible text near "call/phone/contact", or validate with `is_possible_number`/length + region heuristics.

### Issue D: Old corrupted rows remain in DB (not cleaned)
Pre-fix rows (`sales@jploft.comphone`, `contact@controlf5.inread`, etc.) still exist; the fix only prevents *new* corruption. Recommend a one-time cleanup + deleting unverified corrupted patterns.

### Issue E: Old leads re-upserted with garbage phone batches
`contact@controlf5.in` (old row) was **updated** during the run and now carries 14 mostly-junk phones. Because upsert overwrites phones wholesale, noisy extraction actively degrades previously clean rows.

### Issue F: Unchanged (pre-existing, not part of this fix)
- Company attribution still wrong (all leads → `clutch.co` / `goodfirms.co`)
- LinkedIn still blind-first-match (`linkedin.com/company/clutch-co` on 4 of 6 new leads; 1 correct: `the-code-district`)
- First names still email-prefix derived (`Hello`, `Sales`, `Info`)
- Query-param variant crawling still exploding (same profile multiple variants → WAF risk)

---

## 4. Metrics Comparison (Target vs Current)

| Metric | Pre-Fix | Post-Fix | Target |
|---|---|---|---|
| Leads with phones | 0% | 1.4% (6/438) | >50% |
| New corrupted emails per run | 16/432 | 2/6 new (33%) — `.agen` + `.com.read` | 0 |
| Original corruption patterns (`comphone`/`inread`) | 16 | 0 (fixed) | 0 |
| Scrape success rate | 99.5% | 99.6% (242/243) | ≥95% |
| New WAF blocks | — | 0 | 0 |
| Real clean emails per new lead | — | 4/6 (67%) | >80% |

---

## 5. Verdict & Next Steps

**The fix worked for its intended scope:** phones are finally extracted end-to-end, and the original email-corruption patterns are gone. The fix did **not** regress fetch success or cause new blocks.

**Remaining work before P3.2/P3.3:**
1. **P0 follow-up:** tighten email TLD handling — use a real TLD set (or `\b` + full-TLD list incl. `agency`, `agency`-type 5-6 letter TLDs) and reject `x@y.tld.word` suffix absorption.
2. **P0 follow-up:** tame `PhoneNumberMatcher` — restrict to `tel:`/`mailto:` contexts or near "phone/call/contact" text; validate possible numbers; cap phones per lead.
3. **P1:** one-time DB cleanup of 16 legacy corrupted emails + junk-phone batches on old rows.
4. **P1:** proceed with Pre-3.2 (URL query-param dedup) — the current session alone generated 53 scrape attempts with heavy variant duplication.
5. **P1:** P3.3 (company attribution) remains the highest-value fix for lead quality.

---
*Monitoring data: worker logs (process monitor) + PostgreSQL MCP queries (leads, phones JSONB, scrape_logs). Baseline audit: docs/LEAD_GEN_AUDIT_REPORT.md.*
