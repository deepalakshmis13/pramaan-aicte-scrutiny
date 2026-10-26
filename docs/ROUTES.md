# Route inventory

Routes are defined in `frontend/src/App.tsx`; path builders in `frontend/src/lib/routes.ts`. Every route works on direct
navigation and refresh. A page for another role shows *You don’t have access to this page* (the API also returns 403/404);
unknown paths show *Page not found*; unknown IDs show a *Not found* state.

## Shared
| Path | Page |
|---|---|
| `/login` | Sign in |
| `/` | Redirects to the signed-in role’s home |
| `/profile` | Profile and session |
| `/notifications` | All notifications; each opens its exact record |

## Institution
| Path | Page |
|---|---|
| `/institution` | Overview: action required (notices with deadlines, drafts to finish), applications with stage and next step |
| `/institution/applications` | My Applications, with **New Application** |
| `/institution/applications/new` | Step 1: type, academic year and details |
| `/institution/applications/:id` | Draft: details, document checklist (upload / replace / remove), validation, submit. Submitted: stage, next step, documents with status and download, notices, decision, submission history |
| `/institution/notices` | Notices issued to the institution |
| `/institution/notices/:noticeId` | Notice items, responses, corrected uploads, submit response, notice PDF |

## Scrutiny officer
| Path | Page |
|---|---|
| `/reviewer` | Dashboard: applications per stage and the priority queue with its weighted reasons |
| `/reviewer/applications` | Applications table (`?q=&status=&has=&page=`), CSV export |
| `/reviewer/applications/:id` | The single review page — sections `#documents`, `#verification`, `#notices`, `#decision`, `#history` |
| `/reviewer/notices` | Notices sent, delivery status, institution responses |
| `/reviewer/audit` | Audit trail (from the account menu) |

## Administrator
| Path | Page |
|---|---|
| `/admin` | Users |
| `/admin/configuration` | `?section=system` · `checklists` · `rules` · `sources` |
| `/admin/audit` | Audit log |
