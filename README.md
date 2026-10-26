# PRAMAAN — Post-submission Application Scrutiny Prototype (AICTE)

A working prototype of an AI-assisted **post-submission verification and regulatory-compliance** platform for AICTE
application scrutiny. Institutions submit applications with their checklist documents; scrutiny officers verify them on one page,
accept or reject documents with reasons, send deficiency notices, re-verify corrections and record the final decision.

> **Prototype.** All institutions, people, certificates and documents are synthetic. The system is **not** connected to any
> AICTE system. It is decision support only: it never approves or rejects an application.

| Layer | Technology |
|---|---|
| Frontend | React 18 + TypeScript, Vite, Tailwind CSS (custom token system; hand-built Radix-based components), React Router, TanStack Query, React Hook Form + Zod, Recharts, Lucide |
| Backend | Python 3.11+ (tested 3.13), FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 14+ (tested 16) |
| Documents | PyMuPDF (native text, page rendering, font/drawing analysis), Tesseract OCR via pytesseract, OpenCV (quality, perceptual hash), SHA-256 |
| Sources | Crossref REST API (live), Elsevier Scopus Search API (needs institutional key), AICTE records adapter (placeholder) |
| Reports | ReportLab (server-side PDF) |
| Tests | Pytest, Vitest + Testing Library, Playwright |

Further documentation: [`docs/ROUTES.md`](docs/ROUTES.md) (route inventory) · [`docs/FEATURES.md`](docs/FEATURES.md)
(feature-to-implementation checklist, simulated/unavailable integrations, limitations) · [`docs/TESTING.md`](docs/TESTING.md) (tests executed and results).

---

## 1. Prerequisites

- Python 3.11+ and `pip`
- Node.js 20+ and `npm`
- PostgreSQL 14+
- Tesseract OCR 5 with English data (`apt install tesseract-ocr` / `brew install tesseract` / Windows installer — then set `TESSERACT_CMD`)

## 2. Database

```bash
# as a PostgreSQL superuser
psql -c "CREATE USER aicte WITH PASSWORD 'aicte_dev' CREATEDB;"
createdb -O aicte aicte_verify
createdb -O aicte aicte_verify_test      # used by pytest and Playwright; never touches your demo data
```

## 3. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # set SECRET_KEY; adjust DATABASE_URL if needed
alembic upgrade head                                   # create the schema
python -m seed.seed --reset                            # synthetic demo data (drops and recreates the schema; ~30 s)
uvicorn app.main:app --reload --port 8000
```

API docs (development only): http://localhost:8000/api/docs

## 4. Frontend

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173 (proxies /api to :8000)
```

Single-server mode: `npm run build`, then the backend serves `frontend/dist` at http://localhost:8000 with history-API
fallback, so deep links and refresh work on every route.

## 5. Roles and workflow

| Role | Portal sections |
|---|---|
| **Institution** | Overview · My Applications (create, upload checklist documents, submit, history) · Notices (respond, upload corrections) |
| **Scrutiny officer** | Dashboard (stage counts + priority queue) · Applications · Notices — each application is reviewed on **one page** |
| **Administrator** | Users · Configuration (system status, checklists, rules, sources) · Audit log |

Workflow: institution creates an application → uploads the documents on its type's checklist → submits → it appears in the
officer's priority queue → officer clicks **Verify Application** → accepts, rejects (with reason) or flags documents for
manual verification → **Create Deficiency Notice** → **Send Notice** → institution sees it on Overview and Notices, uploads
corrections and submits a response → corrections are re-verified automatically → officer accepts them → **Move to decision**
→ an officer records the final decision. Automated checks never approve or reject an application.

## 6. Demo accounts (synthetic)

| Role | Email | Password |
|---|---|---|
| Scrutiny officer | anitha.raman@scrutiny.test | Reviewer@2026 |
| Scrutiny officer | vikram.sethi@scrutiny.test | Reviewer@2026 |
| Administrator | admin@scrutiny.test | Admin@2026 |
| Institutions A–H | principal@kaveri-valley.test, director@northfield.test, principal@aranya.test, principal@coromandel.test, principal@deccanridge.test, principal@lotusbay.test, director@himgiri.test, principal@saffronhills.test | Institution@2026 |

These passwords exist only in the seed script for local demonstration.

| App | Institution | Demonstrates | State after seeding |
|---|---|---|---|
| EOA-2027-00001 | Kaveri Valley | Complete application; all documents accepted; real DOI for Crossref | Ready for decision |
| INC-2027-00009 | Kaveri Valley | Institution's own draft (3 documents uploaded) | Draft — finish and submit as the institution |
| EOA-2027-00002 | Northfield | Missing fire certificate; scanned (OCR) fee receipt | Submitted — run Verify Application |
| EOA-2027-00003 | Aranya | Expired NOC rejected with reason; notice sent | Waiting for institution response |
| EOA-2027-00004 | Coromandel | Name mismatch (NOC rejected), faculty qualification conflict | Under scrutiny — send a notice |
| INC-2027-00005 | Deccan Ridge | Scopus indexing unverifiable; conflicting publication; external sources unavailable | Under scrutiny |
| EOA-2027-00006 | Lotus Bay | Duplicate photos; altered fire certificate indicators | Under scrutiny |
| EOA-2027-00007 | Himgiri | Replacement documents submitted and re-verified | Response to review |
| EOA-2027-00008 | Saffron Hills | Poor scan, unlabelled photo, floor plan copied from another institution | Manual verification in progress |

### Five-minute walkthrough
1. Sign in as **principal@kaveri-valley.test** → *My Applications* → INC-2027-00009 → upload the remaining checklist documents → *Submit application*
   (or start a fresh one with **+ New Application**).
2. Sign in as **Anitha** → *Applications* → open the application → **Verify Application**. Open any document to see the page, extracted fields
   and OCR text; **Accept**, **Reject** (reason required) or mark for **Manual check**.
3. **Create Deficiency Notice** → review → **Send Notice**. The confirmation names the institution and the delivery status.
4. Sign in as the institution → the notice is on *Overview* and *Notices* → answer each item, attach corrected files → *Submit response*.
5. As the officer, open the application: corrected documents show as new versions, already re-verified → **Accept** → **Move to decision** → record the decision.

To see *External verification unavailable* deliberately: *Admin → Configuration → External sources → Crossref → Disabled*, then verify again.

## 7. Tests

```bash
cd backend && python -m pytest -q                      # 27 API, security, engine and connector tests (uses aicte_verify_test)
cd frontend && npm run typecheck && npm test           # TypeScript + Vitest
cd frontend && npm run build && npx playwright install chromium && npm run e2e
                                                       # reseeds aicte_verify_test and runs on :8001
```

See [`docs/TESTING.md`](docs/TESTING.md) for what each suite covers and the results of the last run.

## 8. Configuration and security notes

- All secrets come from environment variables (`backend/.env`, never committed). `SECRET_KEY` is required when `APP_ENV=production`.
- Sessions: signed JWT in an `HttpOnly`, `SameSite=Lax` cookie; state-changing requests also require the `X-Requested-With: pramaan` header (CSRF mitigation). Set `COOKIE_SECURE=true` behind HTTPS.
- Passwords: bcrypt (cost 12). Login attempts are rate-limited per IP.
- Authorisation is enforced on the server for every endpoint: officers see all submitted applications (never drafts); institutions see only their own records (others return 404); administrators cannot open application documents.
- Uploads: magic-byte type check (PDF/PNG/JPEG only), size limit, encrypted/oversized PDFs rejected, server-generated storage keys (no user-supplied paths), downloads with `nosniff`.
- Audit: append-only events with a SHA-256 hash chain, verified on *Admin → System*. This is tamper-*evident*, not tamper-proof.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `OCR engine` red on Admin → System | Install Tesseract and/or set `TESSERACT_CMD` to the binary path |
| All Crossref checks show *Source unavailable* | The server has no outbound access to api.crossref.org (proxy/firewall). This is the honest result; allow the host or use Simulated mode for demos |
| Indexing claims always *Manual review required* | Expected without `SCOPUS_API_KEY`. Add an institutional key to check indexing |
| Login says *Too many login attempts* | Wait one minute, or raise `LOGIN_RATE_LIMIT_PER_MINUTE` for local testing |
| `relation … does not exist` | Run `alembic upgrade head` (or `python -m seed.seed --reset`) |
| Blank page after refresh in single-server mode | Run `npm run build` so `frontend/dist` exists |
| Playwright cannot find a browser | `npx playwright install chromium`, or set `PW_CHROMIUM_PATH` to an existing Chromium binary |
