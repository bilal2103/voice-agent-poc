# Healthcare Voice Agent — Backend

A phone line a patient can call to register with a clinic or update their own
details. A caller is answered by a conversational voice agent, verified against
their phone number and date of birth, and their record is written to PostgreSQL
through a REST API. Every call is transcribed and summarised.

## Live demo

| | |
| --- | --- |
| **Phone number** | **+1 (662) 670-1017** — call this to talk to the agent |
| **API base URL** | <https://b70e-2407-aa80-14-24d4-5d04-394b-da33-130e.ngrok-free.app> |
| **Dashboard** | <https://b70e-2407-aa80-14-24d4-5d04-394b-da33-130e.ngrok-free.app/> — read-only list of registered patients |
| **API docs** | <https://b70e-2407-aa80-14-24d4-5d04-394b-da33-130e.ngrok-free.app/docs> |

```bash
curl https://b70e-2407-aa80-14-24d4-5d04-394b-da33-130e.ngrok-free.app/api/v1/patients
```

> The host is an **ngrok tunnel**, so it is reachable only while the tunnel and
> the containers are running. If the link is dead at review time, the project
> runs locally with `docker compose up --build` — see [Setup](#setup) — and the
> phone number will still work once `PUBLIC_BASE_URL` and the Vapi Server URL
> are pointed at a fresh tunnel. Deployment is covered under
> [Next steps](#next-steps).

---

Built as a take-home technical assessment against a roughly three-hour budget.
That constraint drove most of the stack choices below, and the
[Known limitations and trade-offs](#known-limitations-and-trade-offs) section is
deliberately detailed — it is the honest account of what was and was not done.

---

## Contents

- [Live demo](#live-demo)
- [Tech stack and why](#tech-stack-and-why)
- [Setup](#setup)
- [Environment variables](#environment-variables)
- [Architecture](#architecture)
- [API reference](#api-reference)
- [Data model and field rules](#data-model-and-field-rules)
- [The voice agent](#the-voice-agent)
- [Frontend](#frontend)
- [Testing](#testing)
- [Known limitations and trade-offs](#known-limitations-and-trade-offs)
- [Next steps](#next-steps)

---

## Tech stack and why

| Choice | Why |
| ------ | --- |
| **Vapi** (telephony + voice) | The single biggest time saver. Vapi provisions a real dialable US number and handles speech-to-text, text-to-speech, turn-taking, barge-in and endpointing. Assembling the equivalent from Twilio + a transcriber + a TTS provider + my own orchestration is days of work, not hours, and none of it is the interesting part of this problem. Vapi also drives the assistant from a webhook, so the prompt and tools stay in this repository under version control rather than in a dashboard. |
| **FastAPI** | Async by default, which suits a workload that is almost entirely network I/O. The decisive reason is Pydantic: the same models validate REST request bodies *and* the arguments the voice agent passes to its tools, so the field rules are defined once. A caller saying "M4ria" and a `curl` sending `"M4ria"` fail identically. Free OpenAPI docs at `/docs` are a bonus for a reviewer. |
| **PostgreSQL 16** | Native enums, `CHECK` constraints, `gen_random_uuid()` and real foreign keys let the schema enforce the rules rather than trusting the application. One line in Compose to run. |
| **SQLAlchemy 2.0 (async) + asyncpg** | Phone calls are latency-sensitive: a tool call happens while someone is holding the line. Async keeps the webhook responsive. SQLAlchemy 2's typed `Mapped[...]` style also keeps the models readable. |
| **Alembic** | The schema changed five times during the build as requirements arrived. Migrations made each change reviewable and reversible instead of a `DROP TABLE`. |
| **OpenAI** | `gpt-4o` for the conversation — it follows a long, branch-heavy system prompt more reliably than smaller models. `gpt-4o-mini` for summaries, where the task is 2–4 sentences and cost/latency matter more than capability. Both are swappable via env vars, and the LLM layer is provider-agnostic. |
| **Plain HTML/CSS/JS for the frontend** | The page only reads and displays a list. React plus a bundler would add a `node_modules`, a build step and a second dev server for no benefit at this size. One static file has no install, no build and no dependency to keep current, and FastAPI serves it directly — so there is no separate web container and no cross-origin request to configure. |
| **Docker Compose** | A reviewer runs one command and gets the API plus a database with migrations already applied. No local PostgreSQL install. |

**What I deliberately did not build:** authentication on the REST API, a job
queue, or CI. Each is called out below.

---

## Setup

### Prerequisites

- Docker Desktop
- A [Vapi](https://vapi.ai) account with a provisioned US phone number
- An OpenAI API key
- [ngrok](https://ngrok.com) (or any tunnel) — Vapi must reach your machine over HTTPS

### 1. Start the stack

```bash
cp .env.example .env
docker compose up --build
```

This starts three containers:

| Service | URL | What it is |
| ------- | --- | ---------- |
| `db` | `localhost:5432` | PostgreSQL 16 |
| `api` | <http://localhost:8000> | The patients page, the API under `/api/v1`, and docs at `/docs` |

The api container waits for the database healthcheck, runs `alembic upgrade head`
via `entrypoint.sh`, then serves.

Verify:

```bash
curl http://localhost:8000/api/v1/health/ready
```

### 2. Expose it publicly

```bash
ngrok http 8000
```

### 3. Configure `.env`

```bash
PUBLIC_BASE_URL=https://<your-subdomain>.ngrok-free.app
VAPI_SECRET=<any long random string you invent>
OPENAI_API_KEY=sk-...
```

`PUBLIC_BASE_URL` is what the assistant's tool URLs are built from. If it is
left as `localhost`, calls will connect and the agent will talk, but every tool
call fails silently.

Then **recreate** the container — `docker compose restart` does not re-read
`.env`:

```bash
docker compose up -d api
```

### 4. Point the Vapi number at your server

In the Vapi dashboard, open **Phone numbers → your number**:

| Setting | Value |
| ------- | ----- |
| **Server URL** | `https://<your-subdomain>.ngrok-free.app/api/v1/vapi/webhook` |
| **Timeout** | 20s |
| **Authorization → HTTP Headers → Add Header** | name `x-vapi-secret`, value = your `VAPI_SECRET` |
| **Inbound assistant** | leave **unset** |

The full path matters. Saving just the origin means Vapi posts to `/`, which
returns 405 and drops the call.

Leaving the inbound assistant unset is what makes Vapi ask this server for an
assistant on every call (`assistant-request`), so the prompt and tools come from
code.

### 5. Call the number

```bash
docker compose logs -f api
```

### Running locally without Docker

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

On macOS or Linux, activate with `source .venv/bin/activate`, and point
`DATABASE_URL` at your own PostgreSQL instance.

### Useful commands

```bash
docker compose logs -f api
docker compose exec api alembic current
docker compose exec db psql -U postgres -d healthcare_voice_agent -c "\d patients"
docker compose down -v
```

`down -v` also drops the `pgdata` volume, discarding all data.

---

## Environment variables

Everything is read by `app/config.py` through pydantic-settings, from the
environment first and `.env` second. Only the ones marked **required** must be
set for a real call to work.

### Required for a working phone call

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | **Required.** Public HTTPS URL Vapi can reach. Tool URLs are built from it. |
| `VAPI_SECRET` | *(empty)* | **Required outside development.** Shared secret checked against the header Vapi sends. Empty in `development` skips the check; in any other environment the webhook returns 503 rather than running unauthenticated. |
| `OPENAI_API_KEY` | *(empty)* | Needed for call summaries. Without it transcripts are still stored and summaries are marked `skipped`. |

### Database

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/healthcare_voice_agent` | Async driver URL. Compose overrides the host to `db`. Alembic reuses this same value. |
| `DB_ECHO` | `false` | Log every SQL statement. |
| `DB_POOL_SIZE` | `5` | Connection pool size. |
| `DB_MAX_OVERFLOW` | `10` | Connections allowed beyond the pool. |

### Voice agent

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `CLINIC_NAME` | `Bilal's Clinic` | Spoken in the greeting and used in the agent's self-description. |
| `VAPI_SECRET_HEADER` | `x-vapi-secret` | Header **name** carrying the secret — not the secret itself. A value here is rejected at startup. |
| `VAPI_MODEL_PROVIDER` | `openai` | Provider for the conversation model. |
| `VAPI_MODEL` | `gpt-4o` | Conversation model. |
| `VAPI_VOICE_PROVIDER` | `vapi` | TTS provider. |
| `VAPI_VOICE_ID` | `Elliot` | Voice. |

### LLM (summaries)

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `LLM_MODEL` | `gpt-4o-mini` | Model used to summarise transcripts. |
| `LLM_TIMEOUT_SECONDS` | `30.0` | Request timeout. |
| `LLM_MAX_OUTPUT_TOKENS` | `400` | Cap on summary length. |
| `LLM_MAX_TRANSCRIPT_CHARS` | `24000` | Longer transcripts are truncated, keeping the end. |

### Application

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `ENVIRONMENT` | `development` | Anything other than `development` enforces the webhook secret. |
| `DEBUG` | `true` | FastAPI debug mode. |
| `LOG_LEVEL` | `INFO` | Root log level. |
| `LOG_PAYLOADS` | `false` | Logs full webhook bodies. **These contain PHI** — see limitations. |
| `CORS_ORIGINS` | `["http://localhost:3000", ...]` | Browser origins allowed to call the API. |
| `APP_NAME`, `VERSION`, `HOST`, `PORT` | — | Cosmetic / local serving. |

### Compose only

`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` and
`API_PORT` configure the containers. `TZ`/`PGTZ` are pinned to `UTC` in
`docker-compose.yml`.

---

## Architecture

### Layers

A Controller → Service → Repository split, with the LLM isolated behind its own
contract.

```
app/
  main.py              create_app(), middleware, error handlers
  config.py            Settings from env / .env
  dependencies.py      the DI wiring for every layer
  router.py            aggregates controllers under /api/v1
  logging_config.py    logging setup (uvicorn only configures its own loggers)
  error_handlers.py    maps every failure onto the response envelope

  Controllers/         HTTP only: parse, delegate, map errors to status codes
    PatientController.py  AddressController.py
    CallController.py     HealthController.py
    VapiController.py     <- the single webhook Vapi posts to

  Services/            business rules; own the transaction (commit lives here)
    PatientService.py     AddressService.py
    CallService.py        VapiService.py      <- dispatches voice tool calls
    VapiAssistant.py      <- the system prompt and tool schemas

  Repository/          everything that talks to the database
    database.py           engine, session factory, Base, get_db
    PatientRepository.py  AddressRepository.py  CallRepository.py
    migrations/           Alembic

  Models/              SQLAlchemy ORM models (Patient, Address, Call)
  Schemas/             Pydantic contracts + all field validation
  LLM/                 the only place that knows a model provider exists
```

**Layer rules.** Controllers never touch a session. Repositories never raise
HTTP errors. Services translate between the two and own `commit()`; `get_db`
only guarantees rollback-on-error and close.

### Why validation lives in `Schemas/`

The voice agent and the REST API are two front doors onto the same data. Both go
through the same Pydantic models, so a rule is written once. `PatientCreate`
validates a JSON body from `curl` and the arguments the LLM passes to
`create_patient` — there is no second, drifting copy of "what a valid phone
number is".

### Inbound call flow

```
caller
  |
  v
Vapi number --POST--> /api/v1/vapi/webhook   {"type":"assistant-request"}
            <--------  {"assistant": {...}}   prompt + 5 tools, built from code
  |
  |  ... conversation ...
  |
  |--POST--> webhook  {"type":"tool-calls"}   lookup_patient / create_patient /
  |                                           update_patient / save_address
  <--------  {"results":[{"toolCallId":"...","result":"..."}]}
  |
  '--POST--> webhook  {"type":"end-of-call-report"}
                        |
                        |- 1. store transcript, commit, respond 200
                        '- 2. background task -> OpenAI -> summary
```

Everything lands on one endpoint,
[`VapiController`](app/Controllers/VapiController.py), which authenticates the
shared secret, logs the message, and hands off to `VapiService`.

### The two-step write

Registration deliberately writes in two steps: `create_patient` returns a
`patient_id`, then `save_address` attaches the address by foreign key. The
ordering is enforced twice — `AddressService` resolves the patient before
writing, and the FK backs it at the database level — so a stray foreign key
cannot be created even if the agent calls the tools out of order.

### The LLM layer

```
app/LLM/
  base.py           LLMClient contract, LLMError, NullLLMClient
  OpenAIClient.py   the only file that imports the OpenAI SDK
  CallSummarizer.py owns the summary prompt and transcript handling
  factory.py        picks a client from settings
```

Everything above depends on `LLMClient`, never on a vendor SDK, so another
provider is one subclass plus a line in `factory.py`. Without an API key the
factory returns `NullLLMClient` and the application runs unchanged.

**The transcript is committed before the model is ever called**, and
summarisation runs as a background task after the webhook has responded. An
OpenAI round trip inside Vapi's webhook timeout would risk losing the call
report entirely. A provider outage therefore costs a summary, never a transcript.

### Response envelope

Every REST response is `{"data": ..., "error": ...}` — on success `error` is
`null`, on failure `data` is `null`. `error_handlers.py` applies this to
validation failures, HTTP errors and unhandled exceptions alike, so the contract
holds on failure paths too. The Vapi webhook is exempt: it speaks Vapi's
protocol.

---

## API reference

| Method | Route | Purpose |
| ------ | ----- | ------- |
| `GET` | `/api/v1/patients` | List. Filters: `last_name`, `date_of_birth`, `phone_number`, `limit`, `offset` |
| `GET` | `/api/v1/patients/{patient_id}` | Retrieve one by UUID |
| `POST` | `/api/v1/patients` | Create; returns the record with `patient_id` |
| `PUT` | `/api/v1/patients/{patient_id}` | Update; partial bodies allowed |
| `DELETE` | `/api/v1/patients/{patient_id}` | Soft-delete (stamps `deleted_at`; the row is never removed) |
| `POST` | `/api/v1/patients/{patient_id}/address` | Save the address (patient must exist) |
| `GET` | `/api/v1/patients/{patient_id}/address` | Retrieve it |
| `PUT` | `/api/v1/patients/{patient_id}/address` | Update it; partial bodies allowed |
| `DELETE` | `/api/v1/patients/{patient_id}/address` | Remove it |
| `GET` | `/api/v1/calls` | List calls, newest first; filter by `patient_id` |
| `GET` | `/api/v1/calls/{call_id}` | One call with its full transcript |
| `POST` | `/api/v1/vapi/webhook` | Vapi server messages (secret-protected) |
| `GET` | `/api/v1/health` | Liveness |
| `GET` | `/api/v1/health/ready` | Readiness (pings the database) |
| `GET` | `/docs` | Swagger UI |

**Status codes:** `200` read/update/delete, `201` create, `400` malformed query
param, `404` unknown or soft-deleted patient, `409` duplicate, `422` field
validation failure, `500` unhandled error.

Soft-deleted patients are invisible everywhere: excluded from lists, `404` on
fetch, and they no longer block a duplicate check or match a voice lookup.

```bash
curl -X POST http://localhost:8000/api/v1/patients \
  -H "Content-Type: application/json" \
  -d '{"first_name":"Maria","last_name":"OBrien","date_of_birth":"03/15/1985",
       "sex":"Female","phone_number":"(662) 670-1017","email":"maria@example.com"}'
```

---

## Data model and field rules

### `patients`

| Field | Type | Rules | Required |
| ----- | ---- | ----- | -------- |
| `first_name` | String | 1–50 chars, letters + hyphens/apostrophes | Yes |
| `last_name` | String | 1–50 chars, letters + hyphens/apostrophes | Yes |
| `date_of_birth` | Date | Valid date, not in the future, `MM/DD/YYYY` | Yes |
| `sex` | Enum | `Male`, `Female`, `Other`, `Decline to Answer` | Yes |
| `phone_number` | String | Valid US 10-digit number | Yes |
| `email` | String | Valid email format | No |
| `insurance_provider` | String | Company name, 1–100 chars | No |
| `insurance_member_id` | String | Alphanumeric only, 1–50 chars | No |
| `emergency_contact_name` | String | Full name; spaces allowed, 1–100 chars | No |
| `emergency_contact_phone` | String | Valid US 10-digit number | No |
| `preferred_language` | String | Language name, 1–50 chars | No |

`patient_id` (UUID), `created_at`, `updated_at` and `deleted_at` are set by the
server and ignored if sent.

Hyphens and apostrophes are allowed only *between* letters, so `O'Brien` and
`Anne-Marie` pass while `-Ann` and `Mary--Jane` do not. Phone numbers are
normalised on input — `(662) 670-1017`, `+1 662 670 1017` and `662.670.1017` all
store as `6626701017` — and NANP rules apply, so the area code and exchange code
cannot begin with 0 or 1. Optional fields sent as `""` are stored as `NULL`,
because a voice agent sends an empty string rather than omitting a key.

### `addresses`

One per patient, foreign key to `patients`, `ON DELETE CASCADE`.

| Field | Type | Rules | Required |
| ----- | ---- | ----- | -------- |
| `address_line_1` | String | Street address, 1–200 chars | Yes |
| `address_line_2` | String | Apt/Suite/Unit, 1–200 chars | No |
| `city` | String | 1–100 characters | Yes |
| `state` | String | Valid 2-letter US state abbreviation | Yes |
| `zip_code` | String | 5-digit or ZIP+4 | Yes |

State codes cover the 50 states, DC, territories and military posts, normalised
to uppercase. ZIP codes accept `02116`, `02116-1234`, and nine bare digits
(formatted as ZIP+4).

### `calls`

| Column | Meaning |
| ------ | ------- |
| `vapi_call_id` | Unique; repeated webhooks update one row rather than duplicating |
| `transcript` | Verbatim, from the `end-of-call-report` artifact |
| `summary` / `summary_status` | `pending`, `ready`, `failed` or `skipped` |
| `summary_error` | Why it is not `ready` |
| `patient_id` | Set when the call created or updated a patient |
| `caller_number`, `ended_reason`, `duration_seconds`, `started_at`, `ended_at` | Call metadata |

`summary_status` exists so a `NULL` summary is never ambiguous: no transcript or
no API key is `skipped`, a provider error is `failed` with the reason kept.

### Timestamps

All timestamps are `timestamptz`, stored as absolute instants and always emitted
as UTC with a trailing `Z`. Both containers pin `TZ=UTC` so a host timezone
cannot shift them.

### Migrations

```bash
alembic upgrade head
alembic downgrade -1
alembic revision --autogenerate -m "add something"   # needs a reachable database
alembic upgrade head --sql                           # render DDL without connecting
```

Migration scripts live under `app/Repository/migrations/`; `alembic.ini` stays
at the project root so the CLI works with no `-c` flag. Import new models in
`app/Repository/migrations/env.py` so autogenerate sees them.

---

## The voice agent

The prompt, first message and tool schemas all live in
[`app/Services/VapiAssistant.py`](app/Services/VapiAssistant.py). Changes take
effect on the next call — nothing to re-publish in the dashboard.

### Scope

The agent opens with `"Hi there! Welcome to {CLINIC_NAME}. How can I help you
today?"` and does exactly two things: register a patient, and update an existing
patient's details. It refuses everything else in one sentence — appointments,
test results, symptoms, diagnoses, medicines, billing, referrals, prescriptions,
messages, transfers — never gives medical advice, and on anything that sounds
urgent says *"If this is an emergency, please hang up and dial 911."* and ends
the call.

### Identity verification

**A caller must match both a phone number and a date of birth before any stored
information is disclosed.** This is enforced in code, not only in the prompt:
`lookup_patient` requires both arguments and the repository filters on both
columns. There is no lookup-by-phone path.

| Caller supplies | Result |
| --------------- | ------ |
| Phone + matching DOB | Verified; name disclosed, update offered |
| Phone + wrong DOB | "No match" — nothing disclosed, treated as new |
| Phone with no DOB | Refused; the tool will not run |

A failed match is deliberately indistinguishable from an unrecognised number,
and the agent is told never to invite a second guess — otherwise the flow
becomes an oracle for probing whose record exists. When several people share a
number and date of birth, only first names are read out.

Phone alone is not identity: caller ID is spoofable, US carriers recycle
disconnected numbers after roughly 45 days, and households share lines.

### Conversation behaviour

| Requirement | How it is met |
| ----------- | ------------- |
| Natural, not IVR | Forbids "press or say" and numbered options; takes several values volunteered at once; accepts varied date phrasing and mid-sentence self-corrections |
| Confirmation | Reads every collected field back as spoken values, invites correction, and only then saves |
| Error handling | Tool failures return the offending **field names**; the agent re-prompts for only those, keeping everything else. Three failures on one field ends with a staff callback rather than looping |
| Call completion | A personalised sign-off then the built-in `endCall` tool. After an *update* it asks whether there is anything else and keeps going until the caller says no |

`endCallMessage` is deliberately unset: it is a fixed string, so it cannot
contain the caller's name and would play on top of the agent's own sign-off.

### Tools

| Tool | Purpose |
| ---- | ------- |
| `lookup_patient` | Verify a caller by phone **and** date of birth |
| `create_patient` | Register; returns `patient_id` |
| `save_address` | Attach an address to an existing patient |
| `update_patient` | Partial update of an existing record |
| `endCall` | Vapi built-in; lets the agent hang up after its own sign-off |

### Server URL precedence

Vapi picks the most specific URL configured: **custom tool → assistant → phone
number → account**. The assistant returned by `assistant-request` sets each
tool's `server.url` explicitly, so tool calls always come back here even if the
dashboard changes.

### Exercising it without placing a call

```bash
curl -X POST http://localhost:8000/api/v1/vapi/webhook \
  -H "Content-Type: application/json" -H "x-vapi-secret: $VAPI_SECRET" \
  -d '{"message":{"type":"assistant-request","call":{"id":"test"}}}'
```

---

## Frontend

A single static page at <http://localhost:8000/> — the API's own base URL — for
viewing registered patients. Read-only by design: there is no form, no write path
and no way to change anything from the browser.

```
frontend/
  index.html     the whole thing - markup, styles and script
```

No build step, no `package.json`, no `node_modules`.

FastAPI serves the folder itself:

```python
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
```

The mount is added **after** the routers, so `/api/v1/*`, `/docs` and
`/openapi.json` still match first and an unknown path is a 404 rather than the
page. If the `frontend/` directory is missing the mount is skipped and the API
runs on its own.

Serving the page from the same origin as the API means the browser makes no
cross-origin requests at all, so `CORS_ORIGINS` is irrelevant to the UI — it only
matters if you point a separately hosted frontend at this API.

**What it does**

- Lists live patients — name, date of birth, sex, phone, email, registration date
- Search by last name, which calls the API's own `?last_name=` filter rather than
  filtering in the browser
- Click a row to expand insurance, emergency contact, preferred language and the
  address, which is fetched from `/patients/{id}/address` on demand and cached
- Loading skeletons, an empty state, and an error state that shows the API URL it
  tried — the usual cause of a blank page is a mismatched port or origin

Phone numbers are formatted for reading, missing values show an em dash, and
soft-deleted patients never appear because the API already excludes them.

Dark and light themes follow the operating system, and the table drops its less
important columns below 720px.

**Pointing it at a different API.** The page uses its own origin by default.
Override with a query parameter:

```
http://localhost:8000/?api=https://your-api.example.com
```

**Serving it separately.** Any static server works, but then it *is* cross-origin
and the port must be in `CORS_ORIGINS`. Port 3000 is allowed by default, and the
page falls back to `:8000` for the API when it is served from `:3000`:

```bash
cd frontend && python -m http.server 3000
```

---

## Testing

```bash
pytest
```

268 tests, no database or network required — repositories and LLM clients are
faked, so the suite runs in about two seconds.

| File | Covers |
| ---- | ------ |
| `test_patient_schema.py` | Name, DOB, sex, phone, email rules |
| `test_patient_optional_fields.py` | Opt-in extras, UTC timestamp handling |
| `test_address.py` | Address rules, state/ZIP normalisation, save ordering |
| `test_vapi_webhook.py` | Webhook auth, every tool-call payload shape Vapi uses |
| `test_vapi_lookup_update.py` | Verification, disclosure-on-failure, update flow |
| `test_call_recording.py` | Transcript storage, summary status transitions |
| `test_llm_layer.py` | Provider contract, prompt, truncation, failure modes |
| `test_functional_requirements.py` | The assessment's functional requirements |
| `test_health.py` | Liveness, readiness, OpenAPI |

`tests/conftest.py` pins settings so the suite does not depend on a developer's
local `.env`.

---

## Known limitations and trade-offs

Grouped by how much they would matter in production. Most are conscious
decisions taken to fit the time budget, not oversights.

### Security

- **The REST API has no authentication at all.** `POST /api/v1/patients` and
  every other endpoint are open to anyone who can reach the port. Only the Vapi
  webhook is protected, by a shared-secret header. This is the single largest
  gap: in production the API needs auth in front of it before it is exposed.
- **Identity verification is a weak shared secret.** A date of birth is not hard
  to obtain. It is a reasonable bar for a phone intake line that only confirms
  the caller's own contact details, and it is *not* sufficient for disclosing
  clinical information. Revisit it before widening what the agent can read out.
- **Duplicate detection uses name + date of birth**, so two genuinely different
  people who share both collide on registration. Real systems disambiguate with
  more than this.
- **No rate limiting.** Nothing stops a caller — or a script hitting the open
  API — from hammering either surface.
- **`.env` holds secrets in plaintext.** Fine for an assessment; production
  wants a secrets manager.

### PHI and compliance

- **No BAA, and Vapi's HIPAA mode is not enabled.** Patient names, dates of
  birth, phone numbers and addresses flow through Vapi, and call recordings and
  transcripts are retained there by default.
- **Transcripts are sent to OpenAI** for summarisation. The summary prompt
  forbids inferring anything clinical and forbids repeating contact details, but
  the raw transcript still leaves the system.
- **`LOG_PAYLOADS=true` writes PHI to container logs** — full webhook bodies
  including names and dates of birth. It defaults to `false` and is intended for
  debugging only.
- Summaries are stored in the same database as the records, with no separate
  retention policy and no audit trail of who read what.

### Correctness and data

- **Name validation is ASCII-only and rejects spaces.** `José`, `Müller` and
  `Van Der Berg` all fail. This is a literal reading of the supplied spec
  ("alphabetic + hyphens/apostrophes"); for real patient names it is wrong and
  would need widening to Unicode letters.
- **Dates are `MM/DD/YYYY` only** — ISO `1985-03-15` is rejected on input. Again
  per spec, but surprising for an API consumer.
- **"Not in the future" is enforced only in the application.** PostgreSQL
  rejects `CURRENT_DATE` in a `CHECK` constraint because it is not immutable, so
  a direct SQL insert could bypass it.
- **`sex` is a native PostgreSQL enum**, so adding a value later needs an
  `ALTER TYPE` migration. A `varchar` + `CHECK` would be more flexible; the enum
  gives stronger database-level guarantees. Worth revisiting if the value set is
  not stable.
- **Migration `0002` backfilled existing rows with placeholders** —
  `phone_number = '0000000000'` and `sex = 'Decline to Answer'` — because the
  columns were added as `NOT NULL` to a table that already held data. Any row
  created before that migration needs a real backfill.
- **One address per patient**, enforced by a unique constraint. Separate mailing
  and home addresses would need that dropped.
- **Soft delete applies to patients only.** Addresses cascade away with their
  patient; calls keep the row but null the `patient_id`.
- **List endpoints return a bare array** with no total count, so a client cannot
  tell how many pages remain.

### Operations

- **Summarisation is an in-process background task.** If the container restarts
  between the webhook response and the task running, that summary is lost and
  the row stays `pending` forever. There is no retry and no worker — a real
  deployment wants a queue, plus a periodic job to re-run `failed` and `pending`
  rows.
- **Migrations run in the container entrypoint.** Convenient for one container;
  two replicas starting together would race.
- **The tunnel is a bottleneck for webhook volume.** Vapi sends every server
  message type by default, including `conversation-update` and `speech-update`
  on each utterance — around 170 webhooks in a four-minute call, nearly all of
  them discarded. That was enough traffic for tool calls to be rejected before
  reaching the server (Vapi reported 503 for calls that never appeared in either
  the application log or the tunnel's). The assistant now sets `serverMessages`
  to the four types the service actually handles. Worth re-checking if webhook
  traffic grows again.
- **ngrok's free tier changes the URL on every restart.** `PUBLIC_BASE_URL`, the
  container, and the Vapi dashboard Server URL all have to be updated together,
  and a stale value fails silently at tool-call time.
- **`docker compose restart` does not re-read `.env`** — it reuses the existing
  container config. Use `docker compose up -d api`.
- **Anything outside `app/` needs a rebuild.** `alembic.ini`,
  `requirements.txt`, `entrypoint.sh` and the Dockerfile are baked into the
  image; only `./app` is mounted for hot reload.
- **No CI.** Tests are run manually.
- **The frontend is unauthenticated and unpaginated.** It inherits the open API,
  so anyone who can reach port 8000 can read every patient record. It also
  requests up to 200 patients in one call with no paging, and beyond the routing
  tests it has no automated coverage — the UI itself was verified by hand.
- **The API also serves static files.** Convenient for one deployable; in
  production a CDN or reverse proxy in front would serve the page instead, so
  the application server is not spending workers on static content.

### The agent itself

- **Prompt instructions are not guarantees.** The tests assert that an
  instruction is present and that tools return field-scoped errors; they cannot
  prove the model obeys on a live call. The behaviours most likely to be skipped
  are the full read-back before saving and the offer of optional fields.
- **The prompt promises follow-ups nothing delivers.** After three failed
  attempts on a field it says a staff member will follow up. Nothing queues that
  request — it would need somewhere to write it.
- **A call ending by silence timeout has no spoken farewell**, because
  `endCallMessage` is unset so the agent can personalise its own sign-off.
- **Summaries are best-effort** with no evaluation harness. Nothing checks that
  a summary is faithful to its transcript.

---

## Next steps

### Deployment

**Not deployed — this submission runs locally behind an ngrok tunnel**, and the
link is included with the submission. It is live only while the tunnel and the
containers are up, and the URL changes whenever ngrok restarts.

Given more time I would host it on **Railway**. It deploys straight from the
existing `Dockerfile` and provisions a managed PostgreSQL instance, so there is
almost nothing new to build: `entrypoint.sh` already runs `alembic upgrade head`
on boot, so migrations apply on each deploy, and the rest is setting the same
environment variables documented above through Railway's dashboard.

The main benefit beyond permanence is that the app gets a stable HTTPS domain.
That becomes `PUBLIC_BASE_URL` and the Vapi **Server URL**, which removes the
ngrok URL churn described in the limitations — today those two have to be
updated together every time the tunnel restarts.

One thing to watch: Railway exposes its database as `postgresql://...`, while
this app needs the async driver, so `DATABASE_URL` has to be set with the
`postgresql+asyncpg://` prefix rather than used verbatim.

### Handling dropped calls

**Nothing recovers a call that drops mid-conversation.** A phone line failing
part-way through is normal, not exceptional, and this is the largest functional
gap left.

What already works: the `end-of-call-report` still arrives, so the transcript is
stored and summarised whatever the outcome, and `ended_reason` records how the
call finished. That value is only stored and logged — nothing acts on it.

What is lost:

- **Everything collected before the drop.** Values live in the conversation
  until a tool is called, so a line that fails before `create_patient` leaves
  only a transcript. The caller starts over on their next call.
- **The two-step write is not atomic.** `create_patient` and `save_address` are
  separate calls, so dropping between them leaves a patient with no address even
  though the address fields are required. This is not hypothetical — one patient
  in the current database is in exactly that state, registered with no address
  saved, and nothing detected it.
- **No resumption.** A caller ringing back is verified again and begins from the
  start. If `create_patient` did succeed, `lookup_patient` at least finds them
  and offers an update rather than creating a duplicate.
- **No follow-up.** Nothing flags an abandoned registration for staff, so an
  incomplete record simply sits there.

The fix I would reach for first is a reconciliation job: treat "a patient with no
address" and "a call that ended without producing one" as incomplete, surface
them in a queue, and have the agent offer to finish the record on a callback.
Persisting partial answers as the call progresses, rather than only at the end,
would shrink the window further.

### Not implemented

Two of the optional bonus challenges were left out for time. Neither is started
— there is no partial implementation behind a flag.

**Multi-language support.** The agent runs in English only. A caller saying
*"Hablo español"* gets an English reply; it does not detect the switch or change
voice. Vapi supports this through its transcriber and voice settings, so the work
is real but contained: detect the language, swap the transcriber locale and the
TTS voice mid-call, and translate the system prompt. The data model already
carries `preferred_language`, but today that is only a stored field — **it does
not change how the agent speaks**. Nothing here has been tested in any language
other than English.

**Appointment scheduling.** Offering a first appointment after registration is
not built, and the agent deliberately refuses scheduling requests as out of scope
(see [Scope](#scope)). Adding it would mean a slots table, an availability
lookup, and a booking tool alongside the existing four — the existing tool
dispatch makes that additive rather than structural.

### Beyond deployment

In priority order: authentication on the REST API; a Vapi BAA plus HIPAA mode
and a retention policy; a real job queue for summaries with retries; widening
name validation to Unicode; an audit log of record access; and CI running the
test suite on every push.
