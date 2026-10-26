# Feature-to-implementation checklist

## Simplification (latest revision)

Removed: separate junior/senior officer authorities and two-officer notice approval (one **Scrutiny Officer** role);
officer-side intake and upload (institutions now create and submit applications); the 11-tab application workspace
(replaced by one review page); separate compliance, analytics, finding-detail and document pages; the what-if simulator.

Added: institution application creation with type-specific checklist, upload / replace / remove before submission and
submission validation; per-document **Accept / Reject (reason required) / Manual verification** with officer identity,
timestamp and history; one-step **Create Deficiency Notice → Send Notice** that returns success only after the notice is
committed and linked to the institution; delivery status (delivered / seen) from portal notifications; next-action text
for both portals.

Kept: verification engine, OCR and extraction, rules and versions, external connectors, explainable priority (now listed
factor by factor), evidence map (collapsible), passport, notes, PDFs, audit trail, document versions and downloads.

Notice delivery fix: previously a notice only reached the institution after a second officer approved and issued it, so a
“submitted for approval” confirmation could be mistaken for delivery. Sending is now a single transaction; the response
includes the institution and delivery status, and an end-to-end test checks it appears for that institution only.


Status key: **Done** = implemented and exercised by tests or the seeded scenarios · **Partial** = implemented with a stated limit ·
**Simulated** = clearly labelled demonstration behaviour · **Not available** = interface exists, integration does not.

## Specification features

| # | Feature (master specification) | Status | Where |
|---|---|---|---|
| 1 | Application scrutiny dashboard (all listed counts, filters, automated vs officer split) | Done | `routers/reviewer_apps.py::dashboard`, `pages/reviewer/Dashboard.tsx` |
| 2 | Application & document management (IDs, versions, timestamps, processing status, originals retained) | Done | `models.Document/DocumentVersion`, `services/uploads.py`, `pages/reviewer/Documents.tsx` |
| 3 | OCR & classification; field provenance (page + region); low-confidence values flagged for confirmation | Done | `services/extraction.py`, `services/classification.py`, `processing.py`, viewer “Confirm” |
| 4 | Automatic validation engine (missing docs/fields, formats, unreadable, expired, inconsistent dates, mismatched IDs) | Done | `services/checks/rules.py` |
| 5 | Cross-document evidence graph | Done | `reviewer_findings.py::evidence_graph`, `AppAnalysis.tsx::EvidenceMap` |
| 6 | External source verification (modular connectors, status model, evidence record) | Partial | Crossref live; Scopus requires key; AICTE records placeholder (see below) |
| 7 | Anomaly & duplicate detection (SHA-256, perceptual hash, text shingles, cover-up boxes, rare fonts, metadata gap, cross-application reuse) | Done | `rules.py::duplicates/document_anomaly` — every indicator states its limits |
| 8 | Regulatory rule engine (ID, description, source reference, category, effective dates, params, severity, versions preserved) | Done | `RegulatoryRule/RuleVersion`, `routers/admin.py`, `pages/admin/Admin.tsx` |
| 9 | Infrastructure evidence review (photo count, quality, labels vs floor plan, duplicates) | Done | `rules.py::infrastructure_evidence` (no physical-compliance claims) |
| 10 | Explainable findings (all 12 attributes) | Done | `Finding` model, `FindingDetail.tsx` |
| 11 | Digital verification passport | Done | `reviewer_findings.py::passport` |
| 12 | Explainable review priority queue | Done | `engine.priority` — weighted reasons shown, never used for decisions |
| 13 | Deficiency notice, internal report, final decision report; PDF; review before sending; portal delivery | Done / Partial | `pdf_reports.py`; delivery is portal notification + PDF (no external e-mail integration, stated in UI and PDF) |
| 14 | Institutional correction & reverification (history preserved, officer closes items) | Done | `institution.py`, `engine._upsert` (`latest_result` vs official `status`) |
| 15 | What-if compliance simulator | Removed in simplification | The institution checklist and notice progress bar show what is outstanding |
| 16 | Security, audit & monitoring | Done / Partial | see “Security controls” |

## Master-prompt acceptance checklist

| Condition | Status |
|---|---|
| Every major page exists | Done — see `docs/ROUTES.md` |
| All internal navigation links work | Done — Playwright crawls every route per role and fails on `#`/empty links |
| Buttons and forms perform real actions | Done — all actions call the API; toasts only confirm |
| Direct routes and refresh work | Done — SPA fallback in `main.py`; tested |
| Backend role-based permissions | Done — tested (`tests/test_security.py`) |
| Records persist in PostgreSQL | Done |
| Document upload and processing | Done |
| OCR and validation produce traceable results | Done |
| Cross-document inconsistencies reviewable | Done |
| External verification distinguishes confirmed / unavailable / inconclusive | Done |
| Findings include explanations and evidence | Done |
| Rules applied with versions recorded | Done (`verification_runs.rule_versions`, `findings.rule_version_id`) |
| Passport preserves workflow history | Done |
| Notices reviewed before sending, sent in one step, PDF generated | Done |
| Institutions submit corrections | Done |
| Reverification preserves previous versions and findings | Done |
| PDFs generated from actual records | Done |
| Audit events for important actions | Done |
| Demo scenarios reproducible | Done — `python -m seed.seed --reset` |
| Distinctive, responsive, consistent UI | Done — token system; phone-width overflow test |
| No critical console/server errors in tested workflows | Done — asserted in Playwright |
| Setup, env vars, migrations, demo credentials documented | Done — README, `.env.example` |
| Limitations documented | Done — below |

## Live, local, simulated and unavailable

| Capability | Kind | Notes |
|---|---|---|
| PDF text extraction, OCR, classification, field extraction | Local analysis | Runs on the server; no external calls |
| Validity, completeness, consistency, duplicates, anomalies, infrastructure | Local analysis | Deterministic rules |
| Crossref publication metadata | **Live** | `CROSSREF_MODE=live`. In a network-restricted environment results are *Source unavailable* (this is what the sandbox used for development produced). Matching logic is tested with recorded HTTP responses |
| Crossref demo fixture | **Simulated** | `CROSSREF_MODE=simulated` or Admin → Sources. Always shows *Simulated — not verified*; never counted as verified |
| Scopus indexing | **Not configured** by default | Requires `SCOPUS_API_KEY` (+ insttoken). Without it every indexing claim is *Manual review required* |
| AICTE approval records | **Not available** | Placeholder adapter returns *not configured*; no AICTE integration exists |
| Certificate QR / digital-signature verification, DigiLocker | **Not available** | Future connector; anomaly indicators are used instead |
| External e-mail / portal dispatch of notices | **Not available** | Internal notification + PDF download, stated in the notice |

## Security controls

Implemented: bcrypt hashing; signed JWT in HttpOnly SameSite cookie; CSRF header; per-IP login rate limiting; server-side RBAC and
object-level authorisation (institution isolation returns 404; drafts hidden from officers); administrators denied document access; upload type sniffing, size and page limits, encrypted-PDF rejection; server-generated storage keys with
path-traversal guard; `nosniff`/`X-Frame-Options`/`no-store` headers; validation of all inputs (Pydantic/Zod); parameterised ORM
queries; consistent error envelope without stack traces; sensitive keys scrubbed from audit details; hash-chained audit log;
optimistic concurrency on applications and notices; transactions for multi-step operations.

Remaining before production:
- Single-process in-memory rate limiter and thread-pool job runner → use Redis + a worker (Celery/RQ/Arq) behind multiple instances.
- Local disk storage → encrypted object storage with signed URLs and retention policies; malware scanning of uploads.
- No MFA, password-change flow, account lockout, or SSO; session revocation list not implemented.
- Audit chain is tamper-evident only; ship events to WORM storage for tamper resistance.
- Access logging of every read (currently downloads, exports and actions are logged, not every page view).
- Regulatory rules ship with `source_verified = false` and placeholder references; each must be confirmed against the current
  AICTE Approval Process Handbook before operational use. The system shows a warning for unconfirmed rules.

## Known limitations

- Field extraction is label-based (e.g. “Valid Until:”). Real documents with other layouts will need new patterns or a trained
  layout model; unrecognised layouts produce *missing field / manual review*, never a false pass.
- Classification is keyword-based and reported as such.
- OCR is English only (Tesseract `eng`). Hindi and regional scripts need additional language packs.
- Faculty–certificate linkage uses normalised names; namesakes need officer review.
- Perceptual hashing can match genuinely similar rooms; each such finding says so.
- Synthetic documents were generated for the demo; no accuracy figures are claimed. Spec §12 metrics require a labelled test set.
- The Crossref sample publications cite real public DOIs only to exercise the connector; the claimed faculty authorship is synthetic.
