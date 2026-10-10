# Campus Inbox Agent

Reads placement and internship emails, extracts the key facts (company, role, deadline,
eligibility, form link), checks eligibility against your profile **in plain code**, and shows the
exact sentence from the email behind every decision. When it can't be sure, it says
**needs review** instead of guessing. It never submits anything for you.

## Demo and status

**Live demo: https://campus-inbox-agent.vercel.app** (click *Explore the live demo*; read-only, synthetic emails).

**[Watch the 2-minute demo (docs/demo.webm)](docs/demo.webm)**: real Gemini extraction on a made-up
profile and synthetic emails. It shows an "8.5+ out of 10" email marked *Not eligible* with its sentence
highlighted, a digest email split into three companies, a vague criterion marked *Needs review*, and
drafted form answers that say `[NEEDS INPUT]` instead of inventing facts.

| | Status |
|---|---|
| Pipeline (extraction, evidence guard, rule engine, API, dashboard) | Working; 136 backend + 15 frontend tests; CI on SQLite and PostgreSQL |
| Real Gemini run | Working (`gemini-3.8-flash` with retries and a lite fallback) |
| Accuracy (synthetic) | 36 synthetic emails written for testing (38 opportunities, incl. digests, extensions, reminders, 4-point GPA, relaxable cutoffs, M.Tech-only drives, notices): **35/38 verdicts correct, 3 'needs review', 0 confidently wrong**; all 38 opportunities found. **Not a benchmark**: these aren't real emails. |
| Real-email eval (60–100 labeled college emails) | In progress. College Outlook needs admin consent for API access, so emails are collected as `.eml` downloads |
| Deployment | Live on Vercel: frontend + FastAPI backend (Python function) in read-only demo mode |

## How it works

```
email (paste / .eml / read-only IMAP)
  -> [1] parse & clean, de-duplicate             app/parsing.py, app/service.py
  -> [2] LLM extracts fields + quotes            app/extractor.py
  -> [3] Pydantic validation, retry              app/schemas.py
  -> [4] evidence guard                          app/evidence.py
  -> [5] rule engine (no LLM)                    app/rules.py
  -> [6] eligible / not eligible / needs review
  -> [7] dashboard, evidence viewer, drafted answers you approve      frontend/
         every step stored in an audit log        app/models.py
```

**The LLM reads and writes; code decides.** "Is 8.4 ≥ 8.5?" is an `if` statement, not a prompt.

### Evidence guard

Every extracted value must come with a quote from the email. A field is rejected if:

- the quote isn't in the email (whitespace, case, smart quotes and dashes are normalised), or
- the value isn't in its own quote: a CGPA of 8.5 needs "8.5" in the quote, batch 2026 needs 2026
  or a range like 2026-2028, a form link must appear in the email, and a deadline's day must be in
  its quote (or the quote says "today", "tomorrow" or a weekday like "by Friday" and the date matches
  the received date; "next Friday" is ambiguous and rejected), or
- the deadline is before the date the email arrived.

The LLM gets another try with the rejection reasons. If a field still fails, it is blanked, and
if it was an eligibility field, the verdict becomes **needs review**.

### Verdict rules

| Situation | Result |
|---|---|
| Any verified requirement you don't meet | **Not eligible** |
| …but the email hedges ("or equivalent", "may be relaxed", "preferred") | **Needs review** |
| Unrecognised branch names, CGPA scale mismatch, missing profile value | **Needs review** |
| Your branch is a specialisation of a listed one (CSE (AI&ML) vs CSE) | **Needs review**, until you add an alias |
| Conditions code can't check ("strong academic record") | **Needs review** |
| Missing skills (wording varies, often optional) | **Needs review**, never a fail |
| No eligibility criteria found, or the email isn't an opportunity | **Needs review** |
| Every rule passes | **Eligible** |

Changing your profile re-runs the rules on every stored email without calling the LLM.

### Other features

- **Digest emails**: one email listing several companies becomes several opportunities, each with its
  own criteria and verdict.
- **Duplicates**: the same email pasted twice (or the same Message-ID) isn't processed or billed again.
- **Drafted answers**: paste a form's questions; the LLM drafts answers from your profile only. Missing
  facts become `[NEEDS INPUT: …]`, numbers that aren't in your profile or the email are flagged, and
  you can't approve a draft until the placeholders are filled. You copy approved answers into the form
  yourself.
- **Read-only inbox sync**: IMAP with `readonly=True` and `BODY.PEEK`, so mail is never changed or even
  marked as read.
- **Delete**: deleting an email removes its opportunities, drafts and audit events.

## Run it locally

Backend (Python 3.11+):

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements-dev.txt
cp .env.example .env            # then set GEMINI_API_KEY
uvicorn app.main:create_app --factory --reload
```

Migrations run automatically on startup. API docs: http://localhost:8000/docs

The default model is `gemini-3.8-flash` (`GEMINI_MODEL` to change it; `GEMINI_THINKING_LEVEL=low`
makes extraction faster and cheaper). Gemini 3 models reject sampling parameters such as
`temperature`, so none are sent.

Frontend (Node 20+):

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

Then fill in your profile and paste an email.

### Inbox sync (optional)

**Outlook / Microsoft 365 (most college accounts).** Microsoft 365 doesn't accept passwords over
IMAP, so the app reads mail through Microsoft Graph with read-only permissions (`Mail.Read`, plus
`User.Read` to know your own name for redaction). One-time setup:

1. Sign in to https://portal.azure.com with your college account › **Microsoft Entra ID** ›
   **App registrations** › **New registration**. Name it "Campus Inbox Agent", choose
   "Accounts in this organizational directory only", leave the redirect URI empty, and register.
2. In the new app: **Authentication** › **Allow public client flows** › **Yes** › Save.
3. **API permissions** should list Microsoft Graph `User.Read`; add **Delegated** `Mail.Read`.
4. From **Overview**, copy the *Application (client) ID* into `MS_CLIENT_ID` and the
   *Directory (tenant) ID* into `MS_TENANT` in `backend/.env`.
5. Run `python -m tools.fetch_outlook --sign-in`, open the link it prints, and enter the code.

After that, `python -m tools.fetch_outlook --days 7` and the dashboard's "Check inbox" button work.
If your college blocks app registration or shows "Need admin approval", use the `.eml` route below.

**Gmail or other IMAP accounts.** Set `IMAP_HOST`, `IMAP_USER` and `IMAP_PASSWORD` (for Gmail:
`imap.gmail.com` and an [app password](https://myaccount.google.com/apppasswords)), then use the
"Check inbox" button or `python -m tools.fetch_imap --days 7`.

`IMAP_SENDER_FILTER` (your placement cell's address) limits either source to that sender.

## API

| Method | Path | |
|---|---|---|
| GET | `/health` | No auth |
| GET | `/config` | What the server has configured (no auth) |
| POST | `/auth/signup` | Create an account: `{"email", "password"}` (when `SIGNUP_ENABLED=true`) |
| POST | `/auth/login` | Sign in; returns a 7-day session token |
| GET / DELETE | `/auth/me` | Your role and today's usage / delete your account and all its data |
| POST | `/preview` | Signed in. Runs the full pipeline on one email and returns the result **without storing it** |
| GET / PUT | `/profile` | Batch, CGPA, branch (+aliases), 10th/12th %, backlogs, skills, about-you text |
| POST | `/emails` | Pasted text: `{"text", "subject?", "received_at?"}`; 201 new, 200 duplicate |
| POST | `/emails/eml` | Upload a `.eml` file |
| DELETE | `/emails/{id}` | Remove an email and everything derived from it |
| POST | `/sync/inbox` | `{"since_days": 7, "limit": 25}`; Outlook or IMAP, whichever is configured |
| GET | `/opportunities` | Sorted by deadline |
| GET | `/opportunities/{id}` | Email text, extraction, per-rule results with evidence spans, drafts |
| GET | `/opportunities/{id}/audit` | Every step, timestamped, including raw LLM output |
| POST | `/opportunities/{id}/drafts` | `{"questions": [...]}` |
| PUT / DELETE | `/drafts/{id}` | Edit (`answer`) or approve (`status: "approved"`) |

### Accounts and access control

- **Sign-up** (`SIGNUP_ENABLED=true`): anyone can create an account with an email and a password of at
  least 10 characters. **Every email, opportunity, draft, profile and audit entry belongs to one
  account, and every query is scoped to it**: users can't see or change each other's data. Users can
  delete their account, which removes everything they stored.
- **Usage limits**, because the server's Gemini key pays for every check: each account gets
  `USER_DAILY_LIMIT` (default 10) LLM-backed actions per day, and all accounts together
  `GLOBAL_DAILY_LIMIT` (default 100). Re-adding an email you've already checked is free.
- **Owner** (`ADMIN_EMAIL`, `ADMIN_PASSWORD_HASH`): a built-in account with no usage limit, the only
  one allowed to sync the server's inbox.
- Passwords are stored only as salted PBKDF2 hashes (`python -m tools.hash_password` makes one for the
  owner), sessions are HMAC-signed tokens (`SESSION_SECRET`) that expire after 7 days, wrong passwords
  lock an IP out for 5 minutes after 5 tries, and sign-ups are limited to 5 per IP per hour.
- With no sign-in configured (local use), everything belongs to a single local account.
- **`APP_TOKEN`**: an alternative static bearer token for scripts.
- With either set, every endpoint except `/health`, `/config` and `/auth/login` needs
  `Authorization: Bearer <token>`. **Set one on any server reachable from the internet**: the database
  holds your profile and emails.
- **`DEMO_MODE=true`** (the public deployment): seeds the 36 synthetic emails into a read-only demo
  account that visitors browse without signing in. Visitors never trigger a Gemini call; signed-in users
  work in their own accounts.
- **Accounts need a persistent database.** In demo mode without `DATABASE_URL` pointing at PostgreSQL,
  the SQLite file in `/tmp` is rebuilt on every cold start, so leave `SIGNUP_ENABLED` off there.

## Tests

```bash
cd backend && pytest -q          # 155 tests (+1 Postgres test); uses a fake LLM, no API key needed
cd frontend && npm test          # 19 tests
```

To also run the PostgreSQL integration test locally, set
`TEST_POSTGRES_URL=postgresql://user:pass@localhost:5432/some_empty_db` (it resets the `public`
schema of that database). CI runs it against a Postgres container on every push.

## Eval

`backend/eval/data/synthetic.jsonl` has 36 **made-up** emails (38 opportunities: digests, deadline
extensions, reminders, relaxable cutoffs, 4-point GPA, M.Tech-only drives, notices) to exercise the
harness. Latest run with `gemini-3.8-flash`: 35/38 verdicts correct, 3 "needs review", 0 confidently
wrong. They are not a benchmark. For real numbers:

1. Collect 60–100 real emails into `eval/data/private/candidates.jsonl` (gitignored). With Outlook or
   IMAP set up:
   ```bash
   cd backend
   python -m tools.collect_eval_emails senders --since 2025-07-01        # headers only
   python -m tools.collect_eval_emails download --from <placement-cell-address> --since 2025-07-01
   ```
   Without mailbox access, download the emails as `.eml` (Outlook on the web: open the email ›
   ⋯ › Download) into one folder and run
   `python -m tools.collect_eval_emails import-files --dir <folder>`.
   Both redact email addresses, phone numbers and your own name; read the output anyway.
2. Label each one: true deadline, batches, CGPA, link, and the expected verdict for your profile
   (`expected_opportunities`, same format as `eval/data/synthetic.jsonl`).
3. Split the set: tune the prompt on one part and report numbers only from the part you never
   looked at.

```bash
cd backend
python -m eval.run_eval --data eval/data/private/test.jsonl              # calls Gemini, 8 in parallel
python -m eval.run_eval --data ... --retry-failed --workers 2           # re-run only quota failures
python -m eval.run_eval --data ... --replay eval/out/predictions.jsonl  # re-score for free
```

The report separates **missed** fields (safe: they show up as needs review) from **wrong** and
**spurious** ones (dangerous), confident wrong verdicts from abstentions, and missed or invented
opportunities in digest emails. CI runs the eval when a `GEMINI_API_KEY` repository secret exists.

## Demo video

`demo/record-demo.mjs` drives the real app in Microsoft Edge with Playwright and records a narrated
walkthrough (made-up profile, synthetic emails, real Gemini extraction):

```bash
cd demo
npm install
npx playwright install ffmpeg
npm run record                  # needs GEMINI_API_KEY in backend/.env; writes demo/out/*.webm
```

It starts a fresh backend and frontend, so stop any running dev servers first (or pass
`-- --no-start` to use them). `DEMO_SNAPSHOTS=1` also saves a screenshot per step for review.

## Deploy

The live site runs on **Vercel** as two projects from this repo:

| Project | Root | Settings |
|---|---|---|
| `campus-inbox-agent` (React) | `frontend/` | `VITE_API_URL=https://<api-project>.vercel.app` |
| `campus-inbox-agent-api` (FastAPI, Python function) | `backend/` | `DEMO_MODE=true`, `DATABASE_URL=sqlite:////tmp/campus_inbox.db`, `CORS_ORIGINS=https://<frontend>.vercel.app`, `ADMIN_EMAIL`, `ADMIN_PASSWORD_HASH`, `SESSION_SECRET`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`, `GEMINI_THINKING_LEVEL=low` |

```bash
cd backend  && npx vercel link --project campus-inbox-agent-api && npx vercel deploy --prod
cd frontend && npx vercel link --project campus-inbox-agent     && npx vercel deploy --prod
```

`backend/index.py` is the entry point, `backend/vercel.json` allows 60 s per request (live checks
call Gemini), and `.vercelignore` keeps `.env` and local data out of uploads. In demo mode the
SQLite file in `/tmp` is rebuilt from `demo_data/seed.json` on each cold start, so nothing persists
and no database service is needed.

**For your own private, persistent instance**, use PostgreSQL (`DATABASE_URL=postgresql://...`)
with `DEMO_MODE` unset and owner sign-in configured. `render.yaml` is a ready-made Render blueprint
for that (API + managed Postgres).

## Schema changes

Edit `backend/app/models.py`, then:

```bash
cd backend && alembic revision --autogenerate -m "describe the change"
```

Review the generated file in `migrations/versions/`. CI fails if models and migrations drift apart.

## Known limitations

- Branch aliases cover common Indian B.Tech names. Anything else becomes needs review until you add
  your own aliases on the profile page.
- Deadlines without a time default to 23:59 IST. Ambiguous relative dates ("next Friday", or
  "Friday" in an email sent on a Friday) are shown as unclear rather than guessed.
- The form itself is never fetched, so drafting needs you to paste the questions.
- The eval numbers depend entirely on your labeled set; one college's email style won't generalise.

## Principles

- Read-only access. No auto-submission, ever.
- Redact personal data in demos and test files.
- Report only measured results, with the dataset size and its limits.
- Anything uncertain is marked **needs review**.
