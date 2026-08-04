# OmniSpider — Extraction Quality Remediation & LLM Extraction Strategy

**Document Type:** Analysis & Solution Architecture Artifact (no code changes)
**Date:** 2026-08-04
**Inputs:** `data_quality_audit_report.md`, `docs/SRS.md`, full codebase review of `app/services/scrapers/*`, `app/tasks/scrape_tasks.py`, `app/repositories/*`, `app/models/*`, `config/*.json`
**Scope:** (1) consolidated issue register — audit findings + newly discovered issues, (2) five solution options per issue with pros/cons/tradeoffs, (3) core design issues blocking quality table/field extraction, (4) LLM-based extraction integration design, risks, and best-practice patterns.

---

## 1. Executive Summary

The audit report is accurate: 7 fields are breaking, 9 are fragile, and Tier 2 is currently not bypassing Cloudflare Turnstile. However, the audit **understates the severity**. A full code review reveals that most null-rate symptoms share a small number of **root-cause design flaws**, and that the report missed the single most dangerous bug in the system:

> **NEW CRITICAL FINDING — Company identity corruption.** When a directory profile page yields no external website (extraction failure, JS-rendered button, or anti-bot shell HTML), `parser.py:662-664` falls back to using the *directory page itself* as the company website. The resulting `CompanyCreateSchema` is keyed with `domain = goodfirms.co` (or clutch.co, etc.). Because `upsert_company` is keyed on `domain`, **every failed profile on the same directory silently merges into one shared company row**, corrupting names, industries, phones, and socials of unrelated companies into a single record — and simultaneously **kills the second hop** (`target_website = None`), so no leads, no persons, and no technographics are ever produced for that profile.

Three structural conclusions drive everything in this document:

1. **The extraction layer validates while it extracts.** Cleaners like `clean_company_size()` throw away data that doesn't match keyword assumptions. Valid data present in the DOM/JSON-LD is discarded before it ever reaches the database. Validation must move to a separate layer that *flags*, not *deletes*.
2. **There is no fallback chain, provenance, or confidence per field.** Each field gets exactly one extraction attempt from one strategy; when it fails, the field is NULL and the system cannot tell "absent on page" from "extractor failed". Quality cannot be measured, so it cannot be managed.
3. **Rule-based extraction has a hard ceiling** on layout diversity (directory redesigns, SPA shells, obfuscated emails, semantic tables). A **hybrid architecture** — deterministic extraction first, LLM extraction as a constrained, verified fallback — is the industry-standard way past that ceiling, provided LLM output is treated as *untrusted candidate data* and re-verified deterministically.

---

## 2. Consolidated Issue Register

### 2.1 Issues confirmed by the audit report (verified against code — all accurate)

| ID | Issue | Root Cause (verified) | Severity |
|:---|:---|:---|:---|
| A1 | `companies.company_size` 100% NULL | `parser.py:563` — `clean_company_size()` requires the keywords `employees/staff/team/people/personnel`; raw values like `"10-49"` are discarded. **Double bug:** JSON-LD `numberOfEmployees` (int or `QuantitativeValue`) resolves to `"45"` / `"10"` — also keyword-less, also discarded (`parser.py:678-680`). | CRITICAL |
| A2 | `leads.title/seniority/department/linkedin_url` 100% NULL | `parser.py:499-505` — title comes only from `TITLE_PATTERN` over the email's DOM scope; generic emails (`info@`) sit in footer scopes with no title. `seniority`/`department` derive from `title`, so one miss cascades into three. | CRITICAL |
| A3 | `leads.first_name/last_name` 80–90% NULL | `parser.py:429` — `_name_from_email()` returns `(None, None)` for generic local-parts (`info`, `contact`, `sales`...). | HIGH |
| A4 | `companies.linkedin_url` 38%, `twitter_url` 62%, `hq_phone` 54% NULL | Socials extracted only from `<a href>` in a scope; JSON-LD `sameAs` / `ContactPoint` never consulted. Phone regex is US-only (see N6). | HIGH |
| A5 | `leads.email_verified_at` 100% NULL | Set only when `smtp_checked=True` (`scrape_tasks.py:136-137`); SMTP stage systematically fails/skips (see N8). | HIGH |
| A6 | SRS drift: `company_size` vs `employee_count_range`; HQ city/country buried in `extra_metadata`; `account_pool` table missing | Schema/code vs `docs/SRS.md` §3. | MEDIUM |
| A7 | Tier 2 headless cannot solve Turnstile; Windows teardown pipe errors | `tier2_cdp.py:27` (`TIER2_HEADLESS=True` — headless Chrome is trivially fingerprinted); teardown on ProactorEventLoop (`tier2_cdp.py:93-105`). | HIGH |

### 2.2 NEW issues discovered in this analysis (not in the audit report)

| ID | Issue | Evidence | Severity |
|:---|:---|:---|:---|
| N1 | **Company identity corruption on website-extraction failure** — all failed profiles on one directory merge into a single `companies` row keyed by the directory's own domain; second hop cancelled; directory's own emails (e.g. `support@goodfirms.co`) pass the `_extract_leads` domain guard and are saved as "leads" of that fake company. | `parser.py:662-664`, `parser.py:687-688`, `parser.py:840-843`, `company_repository.py:30` (upsert keyed on `domain`), `parser.py:494-496` | **CRITICAL** |
| N2 | **`_labelled_value()` returns the label block, not the value.** Finds any text node containing the label substring, then returns up to 350 chars of ancestor text ("Company Size 10-49 employees | Located in..."). Substring label matching also false-positives on prose ("Our employees love..."). Pollutes `industry` and `company_size`. | `parser.py:578-592` | HIGH |
| N3 | **Unbounded strings can crash whole-page persistence.** `industry` (VARCHAR 255) and `name` (VARCHAR 255) receive uncapped text (`_labelled_value` up to 350 chars; `h1` unbounded). PostgreSQL raises `value too long`, the broad `except` at `scrape_tasks.py:306` fails the *entire* page — company, leads, everything. One bad field kills a whole page. | `parser.py:590`, `parser.py:673`, `models/company.py:14-15`, `scrape_tasks.py:306-308` | HIGH |
| N4 | **Pagination is structurally unreachable.** `IGNORED_QUERY_PARAMS` includes `page` (`config.py:28`), so `?page=2` canonicalizes to the page-1 URL and is deduped; `extract_profile_links` only harvests profile-path links, never "next" links; JS "Load more" needs interaction Tier 1 can't do and Tier 2 never attempts. Directory coverage is capped at page 1 (~25 profiles per listing). | `config.py:28`, `parser.py:193-198`, `parser.py:231-254` | HIGH |
| N5 | **Obfuscated emails are invisible.** No Cloudflare `data-cfemail` XOR decoding, no `name [at] domain [dot] com` deobfuscation, no entity decoding beyond BeautifulSoup defaults. A large share of B2B sites obfuscate exactly the emails we want. Also `a[href^="mailto:"]` CSS prefix match is case-sensitive (`MAILTO:` missed). | Absent in `parser.py:301-317`, `parser.py:481` | HIGH |
| N6 | **Phone extraction is US-only.** `PHONE_REGEX` hard-codes the 3-3-4 NANP grouping (`parser.py:45`); international formats (+44 20 7946 0958, +92 21 …) fail or partially match into garbage. `PHONE_DEFAULT_REGION="US"` compounds it for a directory of global agencies. | `parser.py:45`, `config.py:45` | MEDIUM |
| N7 | **DOM-scope misattribution.** `_contact_scope` accepts an ancestor containing up to 3 emails; the lead's `title`, `phones`, and `linkedin_url` are then read from that shared scope and can belong to a *different person* in the same card. Phones/socials attach to the wrong lead silently. | `parser.py:409-417`, `parser.py:497-508` | MEDIUM |
| N8 | **SMTP verification is architecturally unreliable and slow.** (a) `HELO omnispider-validator.local` is a non-FQDN — many MX hosts reject at HELO; (b) outbound port 25 is blocked by most ISPs/clouds from a Windows workstation; (c) `verify_emails` awaits each address **sequentially** — up to 40 emails × 10s timeout ≈ 6–7 min of worker blocking per page; (d) per-lead `db.commit()` N+1 pattern adds more latency. | `config.py:37-38`, `email_verifier.py:301-315`, `lead_repository.py:62` | HIGH |
| N9 | **Technographic false positives.** Signatures are raw substring regexes over full HTML (`tailwind`, `tw-`, `gtag`, `hubspot`) — a blog post *mentioning* Tailwind "detects" Tailwind. No evidence weighting, no script/src scoping. | `parser.py:82-94`, `parser.py:395-400`, `config/tech_signatures.json` | MEDIUM |
| N10 | **Tier 2 fabricates status codes; neither tier detects soft-404s.** Tier 2 returns `200`/`403` regardless of real HTTP status (`tier2_cdp.py:74`); a rendered Next.js `__next_error__` page (observed live on GoodFirms) parses as a valid page. Tier 1 has no soft-404 heuristic either. | `tier2_cdp.py:72-80`, `tier1_http.py:60-76` | MEDIUM |
| N11 | **7-day cooldown is bypassable by URL cosmetics.** `was_scraped_recently` matches the raw URL string; the same page with a trailing slash or reordered query is a "new" URL. Canonicalization exists (`canonicalize_url`) but is not used for the cooldown key. | `scrape_log_repository.py:12-16` | LOW |
| N12 | **Name corruption & fabrication.** `.capitalize()` mangles `McDonald→Mcdonald`, `O'Brien→O'brien` (`parser.py:815-816`); single-token local-parts without a doubled letter (`johnsmith@`) are stored as `first_name="Johnsmith"`, `last_name=None` — fabricated data indistinguishable from real. | `parser.py:420-431` | MEDIUM |
| N13 | **Person-card recall gaps.** Decision-maker discovery only scans `h2-h5/strong/b` (`parser.py:782`); names in `span/p/div` or alt-text are missed. `TITLE_PATTERN` lacks modern IC titles ("Software Engineer", "Consultant"), and inferred `PersonRecord` leads never carry phones. | `parser.py:68-73`, `parser.py:778-825` | MEDIUM |
| N14 | **No provenance, no confidence, no quarantine.** Neither `companies` nor `leads` stores `source_url`, extractor version, or per-field confidence. There is no quality monitoring (fill-rate alarms) and no regression corpus — every parser change is deployed blind. The audit itself had to reverse-engineer lineage manually. | `models/company.py`, `models/lead.py` (absent columns) | HIGH (for operability) |

---

## 3. Five Solution Options per Issue (Pros / Cons / Tradeoffs)

> Each table gives 5 candidate solutions. "Recommended" rows are marked with ★. Options are combinable unless stated otherwise.

### Issue A1 — `company_size` 100% NULL (keyword-gated cleaner)

| # | Solution | Pros | Cons | Key Tradeoff |
|:--|:---|:---|:---|:---|
| 1 ★ | **Accept bare numeric ranges** — drop the keyword gate; accept `^\d+\s*[-–+]\s*\d*$` and plain ints; sanity-bound 1–10,000,000 | 2-line fix; instantly fixes bare ranges *and* JSON-LD ints; zero infra | Slight false-positive risk (years, ratings like "4-5") | Precision vs recall — mitigated by value bounds + "label nearby" boost |
| 2 ★ | **Structured-data-first handling** — properly parse `numberOfEmployees` as int or `QuantitativeValue{minValue,maxValue,value}` before any text fallback | Highest precision source; schema.org is stable across redesigns | Only ~half of directory profiles carry JSON-LD | Coverage ceiling; still needs option 1 for the rest |
| 3 | **Label→value pair extraction** — rewrite `_labelled_value` to read the *value sibling* (`dt/dd`, `td` pairs, adjacent `span`) instead of the 350-char ancestor blob | Fixes `industry` and future fields too; kills N2 false positives | More DOM heuristics; per-markup-pattern variants | Engineering effort vs one-field patch |
| 4 | **Canonical bucket normalization** — map any parsed value to SRS ranges (`1-10, 11-50, 51-200, 201-500, 501-1000, 1000+`); keep raw string in `extra_metadata` | Consistent analytics/filtering; matches SRS intent (`employee_count_range`) | Loses exact counts ("247 employees" → bucket) | Exactness vs consistency |
| 5 | **LLM per-field fallback** — when rules yield NULL, ask an LLM for `company_size` from a distilled page snippet, validated by option-1 regex before storage | Layout-agnostic recall; handles prose ("a 250-person team") | Cost/latency per page; needs guardrails (§6) | Cost + determinism vs recall on the hard tail |

**Recommended stack:** 1 + 2 + 4 now (deterministic, one day of work); 5 as the fallback tier later.

---

### Issue A2 — `title / seniority / department / linkedin_url` 100% NULL on leads

| # | Solution | Pros | Cons | Key Tradeoff |
|:--|:---|:---|:---|:---|
| 1 ★ | **Match email-only leads to person cards** — `_extract_persons` already finds `John Doe — CEO`; fuzzy-match local-part tokens (`john.doe@` ↔ card "John Doe") and backfill title/seniority/department/linkedin | Uses evidence already on the page; fixes 4 columns at once; no new requests | Ambiguous matches (two Johns) need a confidence threshold | Matching complexity vs null acceptance |
| 2 ★ | **Schema.org `Person` extraction** — parse `@type: Person` (`name`, `jobTitle`, `worksFor`, `sameAs`) from JSON-LD/microdata on team pages | Zero-guess, standards-based, redesign-proof | Only present on well-SEO'd sites | Coverage vs precision |
| 3 | **Field-driven re-crawl** — if a company page yields emails but no titles, dispatch `/team`, `/about`, `/leadership` (already prioritized keywords) as *targeted* subpage tasks before declaring fields absent | Converts existing recursion into a goal-directed fetch; big recall win for decision-maker data | +1–3 requests per company; needs per-company fetch budget | Crawl cost vs field completeness |
| 4 | **Expand title grammar** — full-line capture (up to ~100 chars, not 60), modern titles (Engineer, Consultant, Analyst, Recruiter), strip prefixes ("Senior", "Global") into a normalized title + raw title | Cheap; improves `seniority`/`department` accuracy downstream | Regex ceiling; language-specific | Maintenance burden of pattern libraries |
| 5 | **LLM person-record extraction** — feed distilled team-page DOM; get `[{name, title, linkedin, email?}]` under JSON schema; names/titles trusted after span-check, emails re-verified | Best recall on arbitrary layouts; handles tables/cards/prose uniformly | Cost, latency, hallucination controls needed (§6.4) | Determinism+cost vs layout independence |

**Recommended stack:** 2 + 1 now; 3 as pipeline upgrade; 5 as the long-term general solution.

---

### Issue A3 — `first_name / last_name` 80–90% NULL (and fabricated single-token names, N12)

| # | Solution | Pros | Cons | Key Tradeoff |
|:--|:---|:---|:---|:---|
| 1 ★ | **Stop fabricating** — single-token local-parts without lexicon support → store `None`, keep the email | Ends silent junk like `Johnsmith`; NULL is honest, fake names poison CRMs | NULL rate rises short-term | Data honesty vs fill-rate optics |
| 2 ★ | **Lexicon-validated name guessing** — accept email-derived tokens only if present in a first/last-name dictionary (census + international lists); preserve case via dictionary (`McDonald`) | Filters garbage; fixes `.capitalize()` corruption (N12); cheap | Lexicon maintenance; cultural coverage bias | Recall on rare names vs precision |
| 3 | **Anchor-text mining** — `mailto:` link text and nearby `alt`/`title` attributes are often the person's name; parse with `nameparser` | Real evidence, not inference; precise | Coverage (many mailtos have icon-only anchors) | Coverage vs evidence quality |
| 4 | **Scope-name backfill** — for `info@`-class emails, attach the nearest person-card name found in `_contact_scope` when exactly one person exists in scope | Converts generic emails into attributed contacts | Wrong-attribution risk when scope has 2+ people (N7) | Attribution confidence vs yield |
| 5 | **LLM association** — "which person, if any, does this email belong to in this DOM block?" with span-grounded answer | Handles messy real-world layouts | Must be span-verified to avoid hallucinated names | Cost/guardrails vs recall |

**Recommended stack:** 1 + 2 immediately (both are small, deterministic); 3 alongside; 5 in the LLM tier.

---

### Issue N1 — Company identity corruption (directory-domain fallback) ★ most urgent

| # | Solution | Pros | Cons | Key Tradeoff |
|:--|:---|:---|:---|:---|
| 1 ★ | **Fail-closed guard** — if `domain` resolves to a known directory domain on a DIRECTORY_PROFILE page, **do not upsert**; log `incomplete_profile` with the profile URL for retry | Zero corruption, ~5 lines, works today | Those profiles yield nothing until website extraction improves | Data loss vs data corruption (corruption is worse) |
| 2 ★ | **Repository-layer invariant** — `upsert_company` rejects `domain ∈ DIRECTORY_DOMAINS` unless explicitly flagged; defense in depth even if parser regresses | Cheap safety net at the trust boundary; protects against future bugs | Doesn't recover the lost company by itself | — (should ship regardless of other options) |
| 3 | **Provisional identity** — key unresolved profiles by directory slug (`goodfirms.co/company/chop-dawg`) in a `provisional_key` column; merge into the real domain once the website is resolved on a later pass | Keeps per-company data separate; recoverable | Schema change + merge logic | Complexity vs immediate cleanliness |
| 4 | **Stronger website detection** — consult JSON-LD `url/sameAs` first, per-directory "Visit Website" selector classes, unwrap redirect wrappers (`_unwrap_redirect` already exists), score external links by button context | Fixes the root cause for most failures | Per-site selector upkeep | Maintenance vs automation |
| 5 | **Engine escalation on extraction failure** — today Tier 2 only triggers on *fetch* failure; also trigger it when Tier 1 HTML parses but yields no website (JS-rendered profile actions) | Recovers JS-shell pages deterministically before any LLM is needed | nodriver is slow (~8s) and currently WAF-fragile | Latency vs recovery rate |

**Recommended stack:** 1 + 2 ship first (stop the bleeding); 4 + 5 next; 3 only if unresolved profiles prove valuable.

---

### Issue A4/N6 — Socials & `hq_phone` fragility (38–62% NULL, US-only phones)

| # | Solution | Pros | Cons | Key Tradeoff |
|:--|:---|:---|:---|:---|
| 1 ★ | **JSON-LD `sameAs` + `ContactPoint` parsing** — company LinkedIn/Twitter and `telephone`/`contactType` from structured data | Precise, redesign-resistant; zero guessing | Coverage bounded by JSON-LD adoption | Coverage vs precision |
| 2 ★ | **libphonenumber matcher** — replace `PHONE_REGEX` with `phonenumbers.PhoneNumberMatcher` (region from page TLD/language, fallback multi-region); keep E.164 output | Global formats, built-in validity & type; kills N6 garbage matches | Slower than regex; region ambiguity for `+`-less numbers | CPU vs correctness |
| 3 | **Contact-page targeted fetch** — if homepage yields no phone/socials, fetch `/contact` (top priority keyword) and merge results into the company row | Big recall win; uses existing recursion | +1 request per company | Crawl budget vs completeness |
| 4 | **Scoped social search with priority** — search header/footer/contact blocks first, then whole page; accept `/company/` for LinkedIn at company level, `/in/` only at lead level; record which scope produced the hit | Reduces both misses and N7-style misattribution | More heuristics to maintain | Complexity vs attribution accuracy |
| 5 | **LLM contact-block extraction** — distilled contact/about section → `{phones[], socials[]}` schema | Layout-agnostic; reads icon-only links via `aria-label` context | Overkill where JSON-LD exists; cost | Cost vs the long tail of weird footers |

**Recommended stack:** 1 + 2 now; 3 as part of field-driven re-crawl (A2 option 3); 5 in LLM tier.

---

### Issue A7 — Tier 2: Turnstile failure, headless detection, Windows teardown noise

| # | Solution | Pros | Cons | Key Tradeoff |
|:--|:---|:---|:---|:---|
| 1 | **Headed-mode execution** — `headless=False` on Windows (already supported); on Linux containers run under `xvfb-run`; keep patched nodriver (`scripts/patch_nodriver.py`) | Turnstile pass-rate jumps substantially in headed mode; no new dependencies | No true headless scale; display/Xvfb ops burden; still an arms race | Ops complexity vs bypass rate |
| 2 ★ | **CAPTCHA-solver fallback (SRS WBS 2.3)** — CapSolver/2Captcha Turnstile token injection when challenge detected | Reliable, measurable, offloads the arms race to a vendor | $ per solve (~$1–3/1000); +10–30s latency; ToS considerations | Cost+latency vs reliability |
| 3 | **Residential-proxy rotation (SRS WBS 2.1/2.2)** — fixes the `status 0` connection resets seen live (IP reputation), not just JS challenges | Addresses root network cause; benefits Tier 1 too | Proxy subscription cost; compliance/ToS; pool management | Cost vs network-level unblockability |
| 4 ★ | **Teardown hardening** — dedicated event-loop policy per task (fresh `ProactorEventLoop` in a worker thread), `loop.set_exception_handler` to swallow pipe noise, upgrade nodriver, gate `browser.stop()` behind state checks | Ends log corruption and flaky worker deaths; pure engineering | Cosmetic relative to bypass problem | Effort vs log/ops hygiene (cheap, do it) |
| 5 | **Session/profile reuse (SRS WBS 4.x, `account_pool`)** — warm Chrome profiles with cookies/history pass Turnstile far more often; persist `profile_dir_path` per domain | Durable bypass improvement; enables authenticated flows later | Profile/account lifecycle management; ban risk concentration | Complexity vs durable access |

**Recommended stack:** 4 immediately (stability), then 2 (solver) as the reliability floor, 1 as environment fix; 3/5 when scaling beyond current volume.

---

### Issue A5/N8 — Email verification: unreliable verdicts, 100% NULL `email_verified_at`, sequential bottleneck

| # | Solution | Pros | Cons | Key Tradeoff |
|:--|:---|:---|:---|:---|
| 1 ★ | **Concurrent batch verification** — `asyncio.gather` + per-domain semaphore (e.g. 10 global, 2 per MX); per-domain grouping reuses one SMTP session for many RCPT probes | 10–40× throughput; single biggest latency win in the pipeline; small diff | Must respect per-MX concurrency to avoid tripping rate limits | Aggressiveness vs SMTP politeness |
| 2 ★ | **Fix SMTP identity** — real FQDN `HELO` (e.g. `verify.yourdomain.com`), matching PTR/SPF, run the SMTP stage from a VPS with port 25 open (not a workstation) | Turns garbage verdicts into real signal; unblocks `email_verified_at` | Infra/ops burden; IP warmup; still imperfect (greylisting) | Ops cost vs verdict truth |
| 3 | **Two-phase verification** — MX+syntax inline at scrape time (fast); SMTP RCPT as a background Celery beat job over unverified rows | Crawl path becomes fast and predictable; verification becomes retryable | `verified_at` lags; needs a status for "pending" | Immediacy vs pipeline speed |
| 4 | **Third-party verifier fallback** — ZeroBounce/NeverBounce/Hunter API for emails still `unverified` after N retries | Vendor-grade accuracy incl. catch-all handling; zero maintenance | ~$0.003–0.01 per email; sending lead data to a vendor (privacy review) | Money+privacy vs accuracy |
| 5 | **Attempt-aware statuses** — store `verification_attempts`, last SMTP response code, next-retry timestamp; 4xx/greylist → `unknown_retry` queue with exponential backoff | Fewer false `unverified`; auditable deliverability over time | Schema + scheduler complexity | Complexity vs verdict honesty |

**Recommended stack:** 1 + 3 now (architecture), 2 when a VPS is available, 4 selectively for high-value leads, 5 as the maturity layer.

---

### Issue A6 — SRS schema drift + missing robustness guards (A6, N3, N14)

| # | Solution | Pros | Cons | Key Tradeoff |
|:--|:---|:---|:---|:---|
| 1 ★ | **Alembic alignment migration** — either rename `company_size→employee_count_range` (SRS truth) or amend SRS §3 (code truth); add `headquarters_city/country` columns promoted from `extra_metadata`; create `account_pool` (SRS-014) | Ends drift; enables indexed HQ queries; unblocks Phase 4 WBS | Migration + backfill work | Doc-vs-code authority decision |
| 2 ★ | **Pydantic field guards** — schema-level `field_validator` capping lengths (`name[:250]`, `industry[:250]`), coercing empty→None, validating enums | Kills N3 whole-page crashes at the trust boundary; ~30 lines | Silent truncation must be logged | Truncation vs crash (truncation wins, with logs) |
| 3 | **Provenance columns** — `source_url`, `extractor_version`, `first_seen_at/last_seen_at`, `field_confidence JSONB` on `companies`/`leads` | Makes every future audit trivial; enables confidence-filtered exports | Schema churn; write-path changes | Storage cost vs operability |
| 4 | **Quality gate + quarantine** — post-parse validation (pandera-style): rows failing hard checks go to `quarantine` table with reasons, never into main tables | Prevents bad data at the boundary; measurable rejection rates | Pipeline complexity; needs replay tooling | Rigidity vs throughput |
| 5 | **DB-level constraints** — CHECK constraints (valid status enums, `domain <> directory domains`, email format), `NOT NULL` where SRS demands | Last-line defense; database enforces invariants app bugs can't bypass | Migrations; legacy rows need cleanup first | Strictness vs migration pain |

**Recommended stack:** 1 + 2 immediately; 3 with the next migration; 4–5 with the quality-monitoring rollout (§5).

---

### Issue N4/N5/N10 — Coverage gaps: pagination, obfuscated emails, soft-404s

| # | Solution | Pros | Cons | Key Tradeoff |
|:--|:---|:---|:---|:---|
| 1 ★ | **Pagination discovery** — extract `rel=next`, `aria-label="Next"`, and `/page/N` patterns *before* query stripping; whitelist `page` in `IGNORED_QUERY_PARAMS` for listing pages only; cap pages per listing | Unlocks full directory coverage (page 1 → all pages) | Crawl-budget explosion needs per-listing caps | Volume vs cost control |
| 2 ★ | **Email deobfuscation layer** — Cloudflare `data-cfemail` XOR decode (one-liner), `[at]/[dot]/(at)` patterns, HTML-entity and `mailto:` case-insensitive matching | Large, cheap email-recall win; purely deterministic | Some sites use custom JS obfuscation | Small effort, big recall |
| 3 | **Tier 2 interaction loop** — scroll-to-bottom + "Load more" clicking for infinite-scroll listings; network-idle wait | Covers SPA directories (GoodFirms observed live) | Slow (seconds per scroll); WAF exposure time grows | Speed vs SPA coverage |
| 4 ★ | **Soft-404 detection** — heuristics on both tiers: `__next_error__`, "page not found" titles, HTTP 200 + error DOM markers; store `soft_404` in scrape_logs | Stops garbage pages from polluting parse results (live GoodFirms case) | Occasional false positives on legit "not found"-mentioning pages | Precision of block heuristics |
| 5 | **Sitemap ingestion** — fetch `sitemap.xml` on company sites to enumerate about/team/contact URLs directly | Cheap, complete discovery for cooperative sites | Many SPAs have stale/absent sitemaps | Coverage vs simplicity |

**Recommended stack:** 1 + 2 + 4 are quick deterministic wins; 3 when Tier 2 stabilizes; 5 opportunistically.

---

### Issue N7/N13 — Person/lead attribution & recall gaps (shared scopes, name corruption, missed cards)

| # | Solution | Pros | Cons | Key Tradeoff |
|:--|:---|:---|:---|:---|
| 1 ★ | **Single-email scopes for lead fields** — tighten `_contact_scope` to prefer ancestors with exactly 1 email when extracting title/phone/linkedin (fall back to multi-email scope only for the email itself) | Directly kills cross-person misattribution | Some fields become NULL instead of wrong | NULL vs wrong (wrong is worse) |
| 2 ★ | **Case-preserving name handling** — replace `.capitalize()` with lexicon/smart-case (`McDonald`, `O'Brien`, `van der Berg`); keep raw display-name string in provenance | Ends N12 corruption; professional-grade CRM data | Name-casing is a rabbit hole (i18n particles) | Perfectionism vs good-enough casing |
| 3 | **Wider name-element net** — add `span/p/div` candidates gated by `_looks_like_person_name` + proximity to a title element; keep stopword guard | Recall win on modern div-based team grids | More false positives to filter | Recall vs precision tuning |
| 4 | **Card-model abstraction** — introduce a `PersonCard` extraction pass (name node + title node + contact links within one visual card) shared by leads/persons; tables handled as row-cards (§5) | One coherent model replaces scattered heuristics; testable | Refactor effort | Refactor cost vs heuristic sprawl |
| 5 | **LLM card segmentation** — "list the people on this page with their role and contact links" from distilled DOM | Handles any visual layout; merges A2/A3/N7 in one mechanism | Cost/guardrails; span verification required | Determinism vs generality |

**Recommended stack:** 1 + 2 now; 4 as the structural refactor; 5 as LLM-tier generalization.

---

### Issue N9 — Technographic false positives

| # | Solution | Pros | Cons | Key Tradeoff |
|:--|:---|:---|:---|:---|
| 1 ★ | **Scope patterns to evidence** — match script `src`/link `href`/cookie names instead of raw HTML text; require asset-URL evidence for CDN/framework claims | Kills mention-based false positives | Misses inlined/obfuscated builds | Recall vs precision |
| 2 | **Weighted confidence** — each pattern carries a weight; store `confidence` + matched evidence in `company_technologies`/metadata | Auditable detections; threshold tuning without code | More bookkeeping | Complexity vs trust |
| 3 | **Header-based detection** — `Server`, `X-Powered-By`, `Set-Cookie` prefixes from Tier 1 response headers (already captured, unused) | Free high-precision signals | Sparse coverage | — |
| 4 | **Library adoption** — Wappalyzer/community signature DB instead of hand-rolled patterns | 1000s of maintained signatures | Dependency/licensing; needs adapter | Build vs buy |
| 5 | **LLM stack inference from asset list** — feed script/link inventory (not prose) for categorization of unknown assets | Categorizes the long tail | Cost; must not invent tech without asset evidence | Cost vs coverage of unknowns |

**Recommended stack:** 1 + 3 now; 2 when provenance columns land; 4 if technographics become a selling point.

---

## 4. Core Design Issues Hindering Quality Extraction (Root-Cause Layer)

These are the **architectural** defects beneath the symptoms. Fixing individual regexes without fixing these guarantees the same class of bug returns.

| # | Design Issue | How it Manifests Today | Design Correction |
|:--|:---|:---|:---|
| D1 | **Validation fused into extraction** — cleaners decide what data is allowed to exist | `clean_company_size` deletes valid `"10-49"`; `clean_industry` mangles blobs; fields NULL despite data on page | Extract *raw* values with provenance → separate validation/normalization layer that *flags* (`raw`, `normalized`, `valid`, `reason`) instead of deleting |
| D2 | **No per-field fallback chain** — one strategy per field, one attempt | JSON-LD miss → text-label miss → NULL. Nobody distinguishes "absent" from "extractor failed" | Field-level strategy chain: structured data → per-site selectors → generic heuristics → LLM fallback, each recording which tier produced the value |
| D3 | **No provenance or confidence metadata** | Audit had to reverse-engineer lineage by hand; bad rows can't be filtered or re-processed | `source_url`, `extractor_version`, `field_confidence`, `extraction_tier` columns; every value answerable to "where did you come from?" |
| D4 | **Entity identity not guarded** — upsert key can be hijacked by a fallback | N1: directory domain becomes a "company"; many companies merge into one row | Identity is a first-class decision: unresolved website ⇒ provisional identity or rejection, never a borrowed key; repository invariant as backstop |
| D5 | **DOM-string heuristics instead of structural models** — scopes, labels, and regexes over flattened text | Tables/cards/grids are treated as text soup; `_labelled_value` returns label blobs; scope leaks misattribute fields (N2/N7) | Structural extraction models: **Table model** (header→columns, row→record), **Card model** (one entity per visual card), **Definition-list model** (label→value pairs) — selected per page region |
| D6 | **Brittle per-site config with no self-healing** — `directory_profiles.json` selectors rot silently when sites redesign | GoodFirms selector misses produce NULL name/industry with no alarm | Selector health monitoring (fill-rate per selector per domain), auto-fallback to generic/LLM extraction when a selector's hit-rate collapses |
| D7 | **No quality feedback loop** — nothing measures extraction success per field/domain/day | 100% NULL `company_size` reached production and stayed until a manual audit | Fill-rate dashboards + alarms (e.g. "company_size fill < 30% on goodfirms.co ⇒ page-rule regression"), golden-page regression tests in CI for every parser change |
| D8 | **Page-level all-or-nothing failure** — one field's crash kills the page | N3: 300-char industry → VARCHAR overflow → whole task `error`, zero rows saved | Field-level isolation: parse errors quarantine the field, never the page; persistence guards cap/validate at the schema boundary |
| D9 | **Throughput architecture hides quality problems** — solo pool + sequential SMTP + per-lead commits | Sample sizes stay small; teams extrapolate quality from dozens of rows | Concurrency (async verification, batched commits, worker autoscale) so quality metrics are computed over thousands of rows, not tens |
| D10 | **Extraction failure does not trigger escalation** — only *fetch* failure escalates tiers | Tier 1 gets a JS shell with no data → parsed as empty success; no Tier 2 retry (live GoodFirms case) | Content-sufficiency check post-parse (expected fields present?) → escalate engine or strategy, exactly like a 403 escalates today |

---

## 5. Ensuring Table Extraction Quality in the Current (Deterministic) Scraper

"Tables" here means **any repeated record structure**: literal `<table>` grids, card grids, definition lists, and team directories. Today the parser has **no table model at all** — `<tr>` is merely one of the `CONTACT_SCOPE_TAGS`, so row/column semantics (which cell is the name, which is the role, which row they belong to) are lost.

### 5.1 What must be built (deterministic layer)

| Capability | Design | Quality Effect |
|:---|:---|:---|
| **Header→column mapping** | Parse `<th>` (or first-row `<td>`/ARIA `role="columnheader"`) into semantic columns via a header dictionary (`name, role/title, email, phone, website, location, size`); unknown headers preserved by position | Every cell lands on the *right field*, not a text blob |
| **Row→record extraction** | Each `<tr>` becomes one record; handle `rowspan/colspan`; cards (`li`, `div` grids) treated as row-equivalents via the Card model (D5) | Per-person/per-company attribution replaces scope guessing (kills N7) |
| **Definition-list model** | `dt/dd`, `th/td` two-col tables, and "Label: value" line pairs parsed as key→value | Fixes `_labelled_value` (N2) at its root; directory profile pages are mostly definition lists |
| **Per-field strategy chain** (D2) | JSON-LD/microdata → table/card model → per-site selectors → generic heuristics → (later) LLM; record the winning tier | Measurable, debuggable extraction; NULLs become explainable |
| **Golden regression corpus** | 20–50 saved HTML pages per directory + expected JSON outputs; parser changes must keep per-field precision/recall ≥ baseline in CI | No more blind deploys; regressions caught pre-production |
| **Fill-rate monitors + alarms** | Nightly job: per-domain per-field fill rates vs thresholds; emit report (extend `scripts/quality_report.py`) | 100%-NULL fields become page-one alerts, not audit surprises |
| **Quarantine lane** (D8) | Rows failing hard validation go to `quarantine` with reasons + raw payload; replayable after parser fixes | Bad data never reaches main tables; nothing is lost |
| **Provenance + confidence** (D3) | Columns on every row; confidence from extraction tier (JSON-LD 0.95 → selector 0.85 → heuristic 0.6 → LLM 0.5→verified 0.9) | Downstream can filter `confidence ≥ 0.8`; audits become queries |

### 5.2 Acceptance criteria for "quality extraction" (suggested SLOs)

* `company_size` fill ≥ 70% on directory profiles, 100% of values matching `\d+(-\d+)?\+?`
* `leads.title` fill ≥ 60% on leads whose company has a team page; zero titles failing `TITLE_PATTERN`+lexicon validation
* Zero `companies` rows keyed by a directory domain (N1 regression test)
* Per-page persistence success ≥ 99.5% (no VARCHAR-overflow crashes — N3 test)
* Every stored row has `source_url` + `extractor_version`
* Email precision (deliverable ∩ stored) measurable weekly via the re-verification sample

---

## 6. LLM-Based Extraction — Design, Integration & Tradeoffs

### 6.1 Where LLM extraction fits (and where it must never go)

The pipeline splits naturally into **perception** (what is on the page?) and **verification** (is it true, normalized, deliverable?). LLMs are strong at perception over messy layouts and weak — by nature — at verification. The deterministic layer keeps all truth functions.

| Pipeline Stage | Owner | Reason |
|:---|:---|:---|
| Fetch, WAF bypass, rendering (Tier 1/2) | Deterministic | Network/engineering problem; LLM adds nothing |
| DOM distillation (strip scripts/styles, keep tables/cards/text, cap tokens) | Deterministic | Cost & injection control before anything reaches a model |
| **Semantic field extraction** (name, industry, size, HQ, person records, table rows) | **LLM fallback / co-extractor** | Layout-agnostic understanding; the long tail of designs |
| Value normalization (size buckets, E.164 phones, seniority enums, industry taxonomy) | Deterministic | Must be reproducible and testable |
| Email/phone/URL **verification** (regex, MX, SMTP, deobfuscation) | Deterministic | Truth is checkable — never trust model output for checkable facts |
| Identity resolution & upsert keys | Deterministic | N1-class corruption must be impossible by construction |
| Confidence scoring, quarantine, provenance | Deterministic | Auditability |

### 6.2 Target hybrid architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         HYBRID EXTRACTION PIPELINE                        │
├──────────────────────────────────────────────────────────────────────────┤
│ Tier1/Tier2 Fetch ──► Parse Gate (soft-404 / WAF / content sufficiency)  │
│                                │                                         │
│              ┌─────────────────▼──────────────────┐                      │
│              │  Deterministic extraction (today + │                      │
│              │  table/card/def-list models, §5)   │                      │
│              └─────────────────┬──────────────────┘                      │
│                                │ per field: value + confidence + tier    │
│              ┌─────────────────▼──────────────────┐                      │
│              │  Field-gap detector: which fields  │  e.g. size NULL,     │
│              │  are NULL / low-confidence?        │  titles missing      │
│              └─────────────────┬──────────────────┘                      │
│                     gaps found │ (only then — cost control)              │
│              ┌─────────────────▼──────────────────┐                      │
│              │  DOM distiller: relevant regions   │  tables, cards,      │
│              │  only; token-capped; scripts out   │  JSON-LD, microdata  │
│              └─────────────────┬──────────────────┘                      │
│              ┌─────────────────▼──────────────────┐                      │
│              │  LLM extractor: JSON-schema output,│  temp=0, evidence    │
│              │  evidence-anchored (span required) │  spans per field     │
│              └─────────────────┬──────────────────┘                      │
│              ┌─────────────────▼──────────────────┐                      │
│              │  Deterministic validation wall:    │  regex/format check, │
│              │  every LLM value re-checked;       │  emails→MX/SMTP,     │
│              │  span must exist in source HTML    │  phones→libphone     │
│              └─────────────────┬──────────────────┘                      │
│              ┌─────────────────▼──────────────────┐                      │
│              │  Merge: higher-confidence wins;    │                      │
│              │  provenance + confidence persisted │                      │
│              └─────────────────┬──────────────────┘                      │
│                         ┌──────▼───────┐                                 │
│                         │ PostgreSQL + │  quarantine lane for rejects    │
│                         │ quarantine   │                                 │
│                         └──────────────┘                                 │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key integration decision — LLM as per-field fallback, not page replacement.** Rules handle the ~70% of pages where they work; the LLM is invoked only for fields that came back NULL/low-confidence (field-gap detector). This caps cost and keeps the deterministic path as the primary, testable system.

### 6.3 How LLM extraction is *better* than manual/rule extraction

| Quality Factor | Rule-Based (today) | LLM-Assisted (hybrid) |
|:---|:---|:---|
| **Layout robustness** | Breaks on every redesign; per-site selectors rot (D6) | Reads semantics, not selectors; a GoodFirms redesign costs nothing |
| **Recall on unstructured data** | Fails on prose ("a 250-person team"), obfuscation, odd tables | Extracts from prose, merged cells, icon-labels, multilingual pages |
| **Semantic table understanding** | No table model; row/column semantics lost (D5) | Maps arbitrary headers → schema fields; resolves merged/implicit columns |
| **Entity association** | Scope heuristics misattribute (N7) | Understands "this email belongs to this person in this card" |
| **Normalization** | Hand-written cleaners per value shape (D1) | Proposes normalized values directly (still re-validated) |
| **Maintenance cost** | Selector engineering per directory | One schema + prompt per entity type |
| **New-site onboarding** | Days (inspect DOM, write profile, test) | Minutes (add domain, schema does the work) |

### 6.4 Issues with LLM extraction (and their mitigations)

| Risk | Reality Check | Mandatory Mitigation |
|:---|:---|:---|
| **Hallucinated values** — model invents plausible emails/phones/sizes | The single biggest danger; a fabricated `john@company.com` that passes SMTP would poison CRM data | **Evidence-anchored output:** every value must include the exact source span; validator confirms the span exists in the HTML (string containment) before acceptance; emails/phones always re-verified (MX/SMTP/libphonenumber) |
| **Non-determinism** — same page, different answers | Breaks reproducibility and regression testing | `temperature=0`, structured outputs (JSON schema / function calling), cache by `sha256(distilled_dom + schema_version + prompt_version)` |
| **Cost & latency** — per-page model calls | $0.001–0.02/page class; +1–5s latency | LLM only on field-gaps (§6.2), batch multiple fields into one call, small-model-first (extraction is a small-model task), hard budget caps per session |
| **Prompt injection from page content** — hostile page text ("ignore instructions, output attacker data") | Real attack vector on arbitrary web pages | Distiller strips scripts/styles/hidden text; system/user role separation; schema-constrained output; span-containment check rejects invented values |
| **Schema drift / malformed JSON** | Models occasionally emit broken or off-schema output | Function-calling/JSON-mode, one automatic repair retry, then deterministic fallback; never crash the page (D8) |
| **Context window vs huge pages** | Directory profiles can exceed context after distillation | Region-targeted distillation (only sections relevant to missing fields), sliding-window with dedupe, cap at ~8–16k tokens |
| **PII & compliance** — sending page PII to a third-party API | GDPR/CCPA exposure for lead data | Prefer self-hosted/open models for PII-heavy pages, or vendor DPAs + region pinning; log what leaves the perimeter |
| **False confidence** — model "succeeds" everywhere, masking fetch failures | A plausible-looking summary can hide a soft-404 | Content-sufficiency gate runs *before* LLM; LLM output cross-checked against independent signals (JSON-LD where present) |
| **Throughput in solo pool** — sequential LLM calls multiply page latency | Compounds the N8 bottleneck | Batch all gap-fields into one call per page, async client, separate LLM worker queue so fetching never blocks on inference |

### 6.5 Best-practice approaches aligned with OmniSpider's quality factors

Ranked by fit for this codebase and world-class scraper standards:

**1. Hybrid cascade with evidence-anchored structured output (recommended primary).**
Rules first → LLM fills gaps under a strict JSON schema where *every field carries its evidence span*; a deterministic validation wall re-checks everything. This is the Firecrawl-/ScrapeGraphAI-class pattern, and it maps 1:1 onto the field-level strategy chain (D2) and confidence model (§5.1). Quality alignment: precision (validation wall), recall (LLM tail), provenance (spans), determinism (temp-0 + cache), cost (fallback-only).

**2. Two-stage generate-and-verify.**
Stage 1: rules generate *candidates* with high recall (keep today's regex/scope harvest, including the noisy parts). Stage 2: the LLM acts as a **judge/normalizer** — "which of these candidate phones is the HQ line?", "is '10-49' a company size or a price range?". Cheaper and safer than open-ended extraction: the model selects and labels rather than invents, so the hallucination surface shrinks to near zero. Excellent first LLM integration because it fixes A1/A2/N6/N9-class problems without trusting model-generated facts.

**3. Schema-first page extraction (full-page LLM mode).**
One call per page type (`DirectoryProfile`, `CompanySite`, `TeamPage`) returning the complete entity under a versioned schema. Best for rapid onboarding of new directories and for pages where rules score ~0 (SPA shells). Use selectively — it is the costliest per page and the least deterministic; always behind the validation wall and content-sufficiency gate.

**4. Self-healing selectors (LLM-assisted rule repair).**
When a per-site selector's fill rate collapses (D6 alarm), an offline (not hot-path) LLM job inspects the new DOM and *proposes a new deterministic selector*, which is then tested against the golden corpus before activation. Keeps the fast path deterministic while automating the worst maintenance burden — the "self-healing scraper" pattern used by mature scraping platforms.

**5. LLM-as-extraction-engineer for golden tests (offline).**
Use the LLM to *author* expected-output fixtures and label the golden corpus, then run pure-deterministic CI against it. Accelerates §5.1's regression harness and keeps humans reviewing rather than labeling.

**Anti-patterns to avoid:**
* LLM on every page, hot path, no rules (cost/latency blowout, needless non-determinism).
* Trusting LLM emails/phones without MX/SMTP/libphonenumber re-verification (fabrication risk).
* Free-text prompts without schema/evidence constraints (unparseable, unvalidatable output).
* Sending raw HTML (cost, injection surface, context waste) — always distill first.

### 6.6 Extraction contract (illustrative schema for the LLM tier)

```json
{
  "schema_version": "company_profile.v1",
  "fields": {
    "name":         {"value": "string|null", "evidence": "exact substring from page", "confidence": "0-1"},
    "industry":     {"value": "string|null", "evidence": "...", "confidence": "0-1"},
    "company_size": {"value": "string|null (e.g. '10-49', '250+')", "evidence": "...", "confidence": "0-1"},
    "headquarters": {"city": "string|null", "country": "string|null", "evidence": "..."},
    "website_url":  {"value": "url|null", "evidence": "href value"},
    "persons": [
      {"name": "string", "title": "string|null", "linkedin_url": "url|null",
       "email": "string|null", "evidence": "exact substring", "confidence": "0-1"}
    ]
  },
  "rules": [
    "Use ONLY information present in the provided page content; null when absent.",
    "evidence MUST be a verbatim substring of the page content.",
    "Never construct or guess email addresses."
  ]
}
```

Validation wall checks (deterministic, in order): JSON parses → schema validates → every `evidence` is a substring of the source HTML → formats re-checked (size regex from A1-option-1, email syntax, phone parse) → emails enter the existing MX/SMTP verifier → survivors merge with rule-extracted values by confidence.

---

## 7. Recommended Phased Roadmap

| Phase | Contents | Why First / Expected Effect |
|:---|:---|:---|
| **P0 — Stop the bleeding (days)** | N1 guards (fail-closed + repository invariant); A1 options 1+2 (size fix); Pydantic length guards (N3); stop fabricating names (A3 opt 1); `data-cfemail` + `[at]` decoding (N5); cooldown canonicalization (N11) | Eliminates active data corruption and the worst NULLs with small, safe diffs |
| **P1 — Deterministic quality core (1–2 weeks)** | Table/card/def-list models (D5); field strategy chain + provenance/confidence columns (D2/D3); pagination discovery (N4); JSON-LD socials/ContactPoint + libphonenumber matcher (A4/N6); soft-404 detection (N10); concurrent email verification + two-phase SMTP (N8) | Lifts fill rates to SLO (§5.2) on rules alone; makes quality measurable |
| **P2 — Observability & hardening (parallel)** | Golden corpus + CI regression; fill-rate monitors/alarms; quarantine lane; Tier 2 teardown fix + solver integration (A7); schema/SRS alignment migration incl. `account_pool` (A6) | Prevents silent regressions; stabilizes the WAF path |
| **P3 — LLM tier (2–4 weeks)** | Start with approach 6.5-#2 (generate-and-verify — cheapest, safest); add evidence-anchored fallback for gap fields (#1); DOM distiller + injection defenses; offline self-healing selectors (#4) and golden-fixture authoring (#5) | Layout-agnostic recall on the hard tail; new-directory onboarding drops from days to minutes |
| **P4 — Scale-out** | Worker autoscaling, residential proxies / account pool (SRS Phase 2/4), third-party verifier fallback for high-value leads | Volume growth without quality dilution |

**Decision rule throughout:** every extracted value must be able to answer three questions — *where did it come from* (provenance), *how sure are we* (confidence), and *what checked it* (validation tier). Any solution — deterministic or LLM — that cannot answer all three does not meet OmniSpider's quality bar.

---

## 8. Appendix — Evidence Index for New Findings

| Finding | Primary Evidence |
|:---|:---|
| N1 identity corruption | `app/services/scrapers/parser.py:662-664`, `:687-688`, `:840-843`; `app/repositories/company_repository.py:17-30` |
| N2 label-blob extraction | `app/services/scrapers/parser.py:578-592` |
| N3 overflow crash path | `app/services/scrapers/parser.py:590,673`; `app/models/company.py:14-16`; `app/tasks/scrape_tasks.py:306-308` |
| N4 pagination unreachable | `app/core/config.py:28`; `app/services/scrapers/parser.py:193-198,231-254` |
| N5 obfuscated emails | absent in `app/services/scrapers/parser.py:301-317,481` |
| N6 US-only phones | `app/services/scrapers/parser.py:45`; `app/core/config.py:45` |
| N7 scope misattribution | `app/services/scrapers/parser.py:409-417,497-508` |
| N8 SMTP reliability/throughput | `app/core/config.py:37-38`; `app/services/scrapers/email_verifier.py:163-176,301-315`; `app/repositories/lead_repository.py:62` |
| N9 tech false positives | `app/services/scrapers/parser.py:82-94,395-400` |
| N10 status fabrication / soft-404 | `app/services/scrapers/tier2_cdp.py:72-80`; `app/services/scrapers/tier1_http.py:60-76` |
| N11 cooldown bypass | `app/repositories/scrape_log_repository.py:12-16` |
| N12 name corruption/fabrication | `app/services/scrapers/parser.py:420-431,815-816` |
| N13 person recall gaps | `app/services/scrapers/parser.py:68-73,778-825` |
| N14 no provenance | `app/models/company.py`, `app/models/lead.py` (columns absent) |

*This artifact is analysis-only; no codebase files were modified.*
