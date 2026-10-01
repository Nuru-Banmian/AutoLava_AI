# #203 release flow acceptance

Run `.github/workflows/release-flow.yml` manually on the candidate commit, or add the
`release-candidate` label to its PR. Later commits to that PR rerun the gate. The workflow fails
on any failed check and uploads the run directory plus Playwright diagnostics even on failure.
It does not deploy or merge anything. The normal PR checks in `ci.yml` remain separate.

The runner builds the API and Web images from one clean commit, records both image IDs and the
source revision, checks production packages selected for the target Linux/Python environment
against `backend/uv.lock`, and records the installed list and migration head. It creates a
disposable Compose volume, launches the actual prebuilt Web image and API image, then adds a
real Nginx TLS proxy with a temporary self-signed certificate. The release Playwright config
does not launch Vite or intercept API calls. Its browser logs in over HTTPS, checks the Secure
Cookie through an authenticated request, saves a ledger entry, reloads it, and reads it again
after both containers restart. Public HTTP calls independently check analysis, workbook data,
stale-write conflict, and logout. A separate disposable volume starts at Alembic revision 0015
with an existing account, membership, record, legacy weather, and category snapshot; the same
candidate image upgrades it, then the public API checks the preserved data and rejects a
numeric-user legacy token. No current local or production database is used.

## Evidence matrix

| Ticket | Fast/targeted evidence | Release-flow evidence | Boundary |
| --- | --- | --- | --- |
| #187 identity and sessions | Backend HTTP and migration tests in PR CI | HTTPS login, protected request, logout, old-token rejection after upgrade | Other revocation races remain targeted tests |
| #188 analytics samples | Backend analytics/HTTP tests in PR CI | Real image `/api/charts` with 150 euros and 3 washes | Broader sample matrix remains targeted tests |
| #189 weather values | Backend weather and migration tests in PR CI | Old weather read after image migration | Actual supplier is not called |
| #190 locked images | Existing image workflow | Same candidate image IDs, target lock selection and installed package list | Target platform is the CI runner's Linux architecture |
| #191 request states | Frontend component and simulated browser tests in PR CI | Browser loads ledger through actual Web image | Network failure variants remain simulated |
| #192 ledger revisions | Backend concurrency tests in PR CI | Stale identity write returns 409 | Full interleaving matrix remains targeted tests |
| #193 configuration revisions | Backend and frontend conflict tests in PR CI | Ledger save uses actual configuration revision | Full configuration conflict matrix remains targeted tests |
| #194 draft/account isolation | Frontend component and simulated browser tests in PR CI | Browser login and ledger flow | Delayed response cases remain simulated |
| #195 responsive password work | Backend HTTP concurrency tests in PR CI | Actual image login | Cancellation/race cases remain targeted tests |
| #196 export work | Backend HTTP cancellation tests in PR CI | Real workbook returned and inspected | Cancellation remains targeted tests |
| #197 deferred weather refresh | Backend HTTP/restart tests in PR CI | Browser ledger save and restart readback | Weather provider is controlled/disabled for release data |
| #198 transaction boundaries | Backend HTTP tests in PR CI | Store creation and ledger write | Full command matrix remains targeted tests |
| #199 generated API types | OpenAPI drift/type/build lanes in PR CI | Candidate Web bundle against candidate API | No type-only check substitutes for browser |
| #200 lazy loading | Build and frontend tests in PR CI | Candidate Web entry and ledger route in browser | Bundle size is not a latency claim |
| #201 readiness/diagnostics | Backend tests in PR CI | API health and captured container logs | No production monitoring claim |
| #202 copy/restore | Backend disposable copy/restore tests in PR CI | Separate upgrade volume only | No real offsite destination or other-host restore |
| #203 release flow | This manual workflow | Actual images, Nginx, HTTPS, browser, restart, HTTP, empty and old migrations | Must be run and reviewed for each candidate |

Until an actual workflow run succeeds, the release-flow column describes checks that are
implemented, not checks that have passed. Record the workflow URL, commit SHA, image IDs,
migration revisions, package lists, data counts, and any failures in release notes. Simulated
providers and browser tests against mocked APIs stay in their own evidence category. Real
weather service, production deployment, load, and other-host recovery require separate
authorization and evidence.
