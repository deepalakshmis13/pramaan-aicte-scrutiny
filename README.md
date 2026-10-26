# PRAMAAN — AICTE Application Scrutiny & Compliance Verification

**PRAMAAN** is a prototype for post-submission scrutiny of institutional applications. It helps scrutiny officers review supporting documents, identify potential compliance issues, issue deficiency notices, verify corrected documents, and maintain an auditable review process.

The goal is to make application scrutiny more **structured, explainable, traceable, and efficient**—while keeping final regulatory decisions under human control.

> **Prototype disclaimer:** PRAMAAN is an independent demonstration project. All institutions, people, applications, and documents are synthetic. It is not affiliated with or connected to AICTE systems. External integrations may be live, simulated, unavailable, or placeholders, as described below. Automated checks provide decision support only; they do not approve or reject applications.

Demo video link : https://drive.google.com/file/d/1ZZZPcfWny5zak-raz_SN01PKe6SlECPe/view?usp=sharing

## Project at a glance

| | |
|---|---|
| Project | PRAMAAN |
| Full name | Post-submission Application Scrutiny Prototype |
| Domain | Regulatory compliance, document verification, workflow automation |
| Application type | Full-stack web application |
| Frontend | React, TypeScript, Vite |
| Backend | FastAPI, Python |
| Database | PostgreSQL |
| Verification approach | Automated checks + human review |
| Deployment status | Local prototype; deployment is not implied |

## The problem

Institutional application scrutiny can involve reviewing large numbers of supporting documents, checking compliance requirements, identifying missing or inconsistent information, communicating deficiencies, and verifying corrections.

When these activities are handled across disconnected workflows, reviewers may find it difficult to trace evidence, track corrections, and maintain consistent records of scrutiny.

## Our approach

PRAMAAN brings the scrutiny workflow into one application:

- **Structured submissions:** Institutions create applications and upload documents against a defined checklist.
- **Document-level scrutiny:** Officers inspect documents, extracted information, and verification results in one review workflow.
- **Evidence-linked findings:** Potential issues can be examined and addressed through human review.
- **Deficiency management:** Officers prepare notices, and institutions submit corrected documents and responses.
- **Correction tracking:** Updated documents can be re-verified before the application proceeds.
- **Auditable workflow:** Review actions and decision records support traceability.
- **Human-controlled decisions:** Officers retain responsibility for the final decision.

## Key features

### 1. Institution portal
- Create and manage applications.
- Upload checklist documents.
- Submit applications for scrutiny.
- View application status and scrutiny notices.
- Respond to deficiencies and upload corrected documents.
- Track the application's review history.

### 2. Scrutiny officer workspace
- View submitted applications and a priority queue.
- Open an application in a consolidated review workspace.
- Inspect document pages, extracted fields, and OCR text.
- Accept documents, reject them with a reason, or flag them for manual verification.
- Prepare and send deficiency notices.
- Review corrected document versions and record review outcomes.
- Move eligible applications to the final-decision stage.

### 3. Document verification support
The prototype combines document-processing techniques and rule-based checks to help identify issues that may need attention.

- PDF text extraction and page rendering.
- OCR for scanned documents.
- Document-quality and image-similarity checks.
- SHA-256 document hashing.
- Checklist and rule-based compliance checks.
- Potential inconsistencies that require human assessment.

These checks do not establish fraud or non-compliance on their own. Findings must be interpreted in context and reviewed by an authorised person.

### 4. External-source verification
- **Crossref:** Live DOI and publication metadata lookup when the external service is reachable.
- **Scopus:** Integration support requiring an appropriate institutional API key.
- **AICTE records:** Placeholder adapter; not connected to official AICTE records.

Unavailable sources must not be interpreted as proof that a claim is false.

### 5. Administration and auditability
- User and role management.
- Configuration for checklists, rules, and external sources.
- System-status visibility.
- Audit-event history with a SHA-256 hash chain.

The hash chain provides tamper evidence, not absolute tamper-proof security.

## Application workflow

```text
Institution creates application
            |
            v
Uploads checklist documents
            |
            v
Submits application
            |
            v
Officer reviews application
            |
            v
Document checks + human scrutiny
            |
            v
Accept / Reject with reason / Manual verification
            |
            v
Deficiency notice, when required
            |
            v
Institution submits corrections
            |
            v
Corrected documents are re-verified
            |
            v
Officer reviews outstanding items
            |
            v
Application moves to final decision
            |
            v
Authorised officer records the decision
```

The workflow supports scrutiny and correction tracking. Automated verification results do not make the final regulatory decision.

## Technology stack

| Layer | Technologies |
|---|---|
| Frontend | React 18, TypeScript, Vite |
| UI and styling | Tailwind CSS, custom design tokens, Radix-based components, Lucide |
| Routing and data | React Router, TanStack Query |
| Forms and validation | React Hook Form, Zod |
| Backend API | Python 3.11+, FastAPI, Pydantic v2 |
| Database and migrations | PostgreSQL 14+, SQLAlchemy 2, Alembic |
| Document processing | PyMuPDF, Tesseract OCR, pytesseract, OpenCV |
| Integrity and reporting | SHA-256, ReportLab |
| External data | Crossref REST API; Scopus connector requiring an API key |
| Testing | Pytest, Vitest, Testing Library, Playwright |

## System architecture

```text
Institution / Scrutiny Officer / Administrator
                     |
                     v
       React + TypeScript Frontend
                     |
              REST API (/api)
                     |
                     v
             FastAPI Backend
                     |
        +------------+------------+
        |            |            |
        v            v            v
   PostgreSQL   Document       Verification
   + Alembic    Processing     & Rule Engine
                     |            |
                     v            v
               OCR / PDF     External Sources
               / Image       (Crossref / Scopus*)
                     |
                     v
              Review Findings
                     |
                     v
           Human Review + Audit Trail
```

\* Scopus requires appropriate credentials. AICTE records integration remains a placeholder.

## Getting started

### Prerequisites

Install the following before running the application:

- Python 3.11 or newer
- Node.js 20 or newer and npm
- PostgreSQL 14 or newer
- Tesseract OCR 5 with English language data

Install Tesseract using the installer appropriate for your operating system. On Windows, configure `TESSERACT_CMD` with the path to `tesseract.exe` if it is not automatically detected.

### 1. Clone the repository

```bash
git clone https://github.com/deepalakshmis13/pramaan-aicte-scrutiny.git
cd pramaan-aicte-scrutiny
```

### 2. Configure PostgreSQL

Create a database user and two databases: one for the demo and one for automated tests.

Run these commands using a PostgreSQL superuser, adapting credentials to your local environment:

```sql
CREATE USER aicte WITH PASSWORD 'CHANGE_THIS_LOCAL_PASSWORD' CREATEDB;
CREATE DATABASE aicte_verify OWNER aicte;
CREATE DATABASE aicte_verify_test OWNER aicte;
```

Do not reuse example passwords in a production environment.

### 3. Configure and run the backend

Open a terminal in the repository root:

```bash
cd backend
python -m venv .venv
```

Activate the environment.

**Windows PowerShell:**

```powershell
.\.venv\Scripts\Activate.ps1
```

**macOS/Linux:**

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create your local environment file:

**Windows PowerShell:**

```powershell
Copy-Item .env.example .env
```

**macOS/Linux:**

```bash
cp .env.example .env
```

Edit `backend/.env` to configure your local `DATABASE_URL`, a strong random `SECRET_KEY`, and any required OCR settings. Keep this private file out of Git.

Run database migrations:

```bash
alembic upgrade head
```

To populate the synthetic demonstration data, run:

```bash
python -m seed.seed --reset
```

**Warning:** The reset option drops and recreates the schema. Use it only when you intentionally want to reset the local demo database. Never run it against a database containing data you need to preserve.

Start the backend:

```bash
uvicorn app.main:app --reload --port 8000
```

API documentation is available locally at:

http://localhost:8000/api/docs

### 4. Run the frontend

Open a second terminal at the repository root:

```bash
cd frontend
npm install
npm run dev
```

Open:

http://localhost:5173

The development server is configured to proxy `/api` requests to the backend on port `8000`.

### Optional: single-server mode

Build the frontend:

```bash
cd frontend
npm run build
```

The backend can serve `frontend/dist` in single-server mode, including history-based route fallback, when the frontend build is available.

## Synthetic demo scenarios

After seeding the demo database, the application includes scenarios intended to demonstrate different scrutiny situations.

| Application | Scenario |
|---|---|
| `EOA-2027-00001` | Complete application with accepted documents and a DOI for Crossref |
| `INC-2027-00009` | Institution draft with uploaded documents |
| `EOA-2027-00002` | Missing fire certificate and scanned fee receipt |
| `EOA-2027-00003` | Rejected expired NOC and a sent deficiency notice |
| `EOA-2027-00004` | Name mismatch and faculty qualification conflict |
| `INC-2027-00005` | Publication-indexing verification limitations and conflicting information |
| `EOA-2027-00006` | Duplicate photographs and possible document-alteration indicators |
| `EOA-2027-00007` | Replacement documents submitted for re-verification |
| `EOA-2027-00008` | Poor scan quality and other issues requiring manual scrutiny |

All records and organisations listed here are synthetic demonstration data, not actual institutional records.

## Five-minute walkthrough

1. **Institution:** Sign in with the seeded Kaveri Valley institution account. Open `INC-2027-00009`, upload the remaining checklist documents, and submit the application—or create a fresh application.
2. **Officer:** Open the Applications section and select an application. Run **Verify Application**.
3. **Inspect evidence:** Open a document to examine its page, extracted fields, and OCR text. Accept it, reject it with a reason, or mark it for manual verification.
4. **Issue a notice:** Create and send a deficiency notice when required.
5. **Submit corrections:** Sign in as the institution, open the notice, attach corrected documents, and submit a response.
6. **Complete scrutiny:** Return to the officer workspace, review corrected documents, and move the application to the final-decision stage when eligible.

## Demo accounts

The seed script creates synthetic demonstration users. Consult the seed configuration for the current accounts and credentials.

For safety, this README does not reproduce reusable demo passwords. Never use seeded demo accounts or development credentials in a deployed environment.

## Testing

### Backend tests

Run from the repository root:

```bash
cd backend
python -m pytest -q
```

The backend tests use the separate `aicte_verify_test` database. Configure it before running the tests.

### Frontend type checking and unit tests

```bash
cd frontend
npm run typecheck
npm test
```

### Production build and end-to-end tests

```bash
npm run build
npx playwright install chromium
npm run e2e
```

End-to-end tests use test fixtures and a separate test environment. Review `docs/TESTING.md` for the test setup and recorded results. Do not assume a test has passed unless you have run it in your current environment.

## Security considerations

The prototype includes several security-oriented controls:

- Environment-based configuration for secrets.
- Signed JWT sessions using an `HttpOnly`, `SameSite=Lax` cookie.
- A required `X-Requested-With: pramaan` header for state-changing requests as a CSRF mitigation.
- Bcrypt password hashing.
- Login-attempt rate limiting.
- Server-side role and resource authorisation.
- File-type validation, upload-size limits, and server-generated storage keys.
- Append-only audit events with a SHA-256 hash chain.

These controls are not a substitute for a full security assessment. Before any real deployment, review authentication, authorisation, session configuration, file handling, logging, dependency vulnerabilities, secret management, and production infrastructure.

## Known limitations

- This is a prototype, not an official AICTE application or integration.
- Institutional records and sample documents are synthetic.
- The AICTE records connector is a placeholder.
- Scopus verification depends on suitable institutional API access.
- External-source failures may prevent verification and require manual review.
- Document-quality or similarity indicators are signals for investigation, not proof of tampering or fraud.
- Automated checks support scrutiny; authorised human officers retain decision-making responsibility.
- Production hosting, monitoring, backups, and deployment hardening are outside the scope of this local setup guide.

## Project documentation

- [`docs/FEATURES.md`](docs/FEATURES.md) — feature-to-implementation checklist, integrations, and limitations.
- [`docs/ROUTES.md`](docs/ROUTES.md) — route inventory.
- [`docs/TESTING.md`](docs/TESTING.md) — test coverage, setup, and recorded results.

## Future improvements

Potential next steps include stronger evidence-linked explanations, expanded validation rules, improved document comparison, more robust integration handling, and enhanced review analytics. These should be implemented and validated before being presented as completed features.

---

**PRAMAAN — Making application scrutiny more structured, traceable, and explainable.**

Built as an independent prototype for exploring document verification and regulatory-compliance workflows.
