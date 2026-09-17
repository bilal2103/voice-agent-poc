# Healthcare Voice Agent — Backend

A phone line a patient can call to register with a clinic or update their details.
A conversational voice agent answers, verifies the caller against their phone
number and date of birth, and writes the record to PostgreSQL through a REST API.
Every call is transcribed and summarised.

Built as a take-home technical assessment against a roughly three-hour budget.

## Live demo

| | |
| --- | --- |
| **Phone number** | **+1 (662) 670-1017** |
| **API base URL** | <https://b70e-2407-aa80-14-24d4-5d04-394b-da33-130e.ngrok-free.app> |
| **Dashboard** | same URL — read-only list of registered patients |
| **API docs** | `/docs` |

```bash
curl https://b70e-2407-aa80-14-24d4-5d04-394b-da33-130e.ngrok-free.app/api/v1/patients
```

> The host is an ngrok tunnel, reachable only while it and the containers are
> running. If the link is dead, the project runs locally with
> `docker compose up --build` (see [Setup](#setup)).

---

## Contents

- [Tech stack and why](#tech-stack-and-why)
- [Setup](#setup)
- [Environment variables](#environment-variables)
- [Architecture](#architecture)
- [API reference](#api-reference)
- [Data model](#data-model)
- [The voice agent](#the-voice-agent)
- [Frontend](#frontend)
- [Testing](#testing)
- [Known limitations and trade-offs](#known-limitations-and-trade-offs)
- [Next steps](#next-steps)

---

## Tech stack and why

| Choice | Why |
| ------ | --- |
| **Vapi** (telephony + voice) | The biggest time saver. Provisions a real dialable US number and handles STT, TTS, turn-taking and barge-in. Building the equivalent from Twilio + a transcriber + a TTS provider is days, not hours, and none of it is the interesting part. Vapi also drives the assistant from a webhook, so the prompt and tools live in this repo rather than a dashboard. |
| **FastAPI** | Async suits a workload that is almost entirely network I/O. The decisive reason is Pydantic: the same models validate REST bodies *and* the arguments the voice agent passes to its tools, so field rules are defined once. A caller saying "M4ria" and a `curl` sending `"M4ria"` fail identically. |
| **PostgreSQL 16** | Native enums, `CHECK` constraints and real foreign keys let the schema enforce rules rather than trusting the application. One line in Compose. |
| **SQLAlchemy 2.0 async + asyncpg** | Tool calls happen while someone is holding the line, so the webhook has to stay responsive. |
| **Alembic** | The schema changed five times as requirements arrived; migrations kept each change reviewable. |
| **OpenAI** | `gpt-4o` for conversation — it follows a long, branch-heavy prompt more reliably. `gpt-4o-mini` for summaries, where cost and latency matter more. Both swappable via env vars. |
| **Plain HTML/CSS/JS frontend** | The page only reads a list. React plus a bundler would add an install and a build step for no benefit. FastAPI serves the single file directly, so there is no second container and no cross-origin request. |
| **Docker Compose** | One command gives a reviewer the API, the dashboard and a migrated database. |

**Deliberately not built:** authentication on the REST API, a job queue, CI.

---

## Setup

### Prerequisites

Docker Desktop · a [Vapi](https://vapi.ai) account with a US number · an OpenAI
API key · [ngrok](https://ngrok.com) or any tunnel.

### 1. Start the stack

```bash
cp .env.example .env
docker compose up --build
```

Two containers: `db` (PostgreSQL 16) and `api`, which waits for the database
healthcheck, runs `alembic upgrade head`, then serves the dashboard, the API
under `/api/v1` and docs at `/docs` on <http://localhost:8000>.

```bash
curl http://localhost:8000/api/v1/health/ready
```

### 2. Expose it and configure

```bash
ngrok http 8000
```

Set these in `.env`, then run `docker compose up -d api` to recreate the
container (`restart` does not re-read `.env`):

```bash
PUBLIC_BASE_URL=https://<your-subdomain>.ngrok-free.app
VAPI_SECRET=<any long random string>
OPENAI_API_KEY=sk-...
```

`PUBLIC_BASE_URL` is what the assistant's tool URLs are built from. Left as
`localhost`, calls connect and the agent talks, but every tool call fails.

### 3. Point the Vapi number at the server

In **Phone numbers → your number**:

| Setting | Value |
| ------- | ----- |
| **Server URL** | `https://<your-subdomain>.ngrok-free.app/api/v1/vapi/webhook` |
| **Authorization → HTTP Headers** | name `x-vapi-secret`, value = your `VAPI_SECRET` |
| **Inbound assistant** | leave **unset** |

The full path matters — saving just the origin makes Vapi post to `/`, which
fails. Leaving the assistant unset is what makes Vapi ask this server for one on
every call, so the prompt and tools come from code.

Then call the number and watch `docker compose logs -f api`.

### Without Docker

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env          # point DATABASE_URL at your own PostgreSQL
alembic upgrade head
uvicorn app.main:app --reload
```

---

## Environment variables

Read by `app/config.py` via pydantic-settings — environment first, `.env` second.

**Required for a working call**

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Public HTTPS URL Vapi can reach; tool URLs are built from it |
| `VAPI_SECRET` | *(empty)* | Shared secret checked against the header Vapi sends. Empty in `development` skips the check; in any other environment the webhook returns 503 rather than running unauthenticated |
| `OPENAI_API_KEY` | *(empty)* | Call summaries. Without it, transcripts are still stored and summaries marked `skipped` |

**Everything else**

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/healthcare_voice_agent` | Async driver URL; Compose overrides the host to `db`, and Alembic reuses it |
| `DB_ECHO` · `DB_POOL_SIZE` · `DB_MAX_OVERFLOW` | `false` · `5` · `10` | SQL logging and pool sizing |
| `CLINIC_NAME` | `Bilal's Clinic` | Spoken in the greeting |
| `VAPI_SECRET_HEADER` | `x-vapi-secret` | Header **name**, not the secret. A value here is rejected at startup |
| `VAPI_MODEL_PROVIDER` · `VAPI_MODEL` | `openai` · `gpt-4o` | Conversation model |
| `VAPI_VOICE_PROVIDER` · `VAPI_VOICE_ID` | `vapi` · `Elliot` | Voice |
| `LLM_MODEL` | `gpt-4o-mini` | Summarisation model |
| `LLM_TIMEOUT_SECONDS` · `LLM_MAX_OUTPUT_TOKENS` · `LLM_MAX_TRANSCRIPT_CHARS` | `30` · `400` · `24000` | Summarisation limits |
| `ENVIRONMENT` | `development` | Anything else enforces the webhook secret |
| `DEBUG` · `LOG_LEVEL` | `true` · `INFO` | |
| `LOG_PAYLOADS` | `false` | Logs full webhook bodies. **Contains PHI** — debugging only |
| `CORS_ORIGINS` | `["http://localhost:3000", ...]` | Only relevant if the frontend is hosted separately |
| `APP_NAME` · `VERSION` · `HOST` · `PORT` | — | Cosmetic / local serving |

Compose also uses `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`,
`POSTGRES_PORT` and `API_PORT`. `TZ`/`PGTZ` are pinned to `UTC`.

---

## Architecture

Controller → Service → Repository, with the LLM behind its own contract.

```
app/
  main.py              create_app(), middleware, error handlers, static mount
  config.py            Settings from env / .env
  dependencies.py      DI wiring
  router.py            aggregates controllers under /api/v1
  logging_config.py    logging setup
  error_handlers.py    maps every failure onto the response envelope

  Controllers/         HTTP only: parse, delegate, map errors to status codes
    PatientController.py  AddressController.py  CallController.py
    HealthController.py   VapiController.py   <- the single Vapi webhook

  Services/            business rules; own the transaction
    PatientService.py     AddressService.py     CallService.py
    VapiService.py        <- dispatches voice tool calls
    VapiAssistant.py      <- system prompt and tool schemas

  Repository/          everything that talks to the database
    database.py  PatientRepository.py  AddressRepository.py
    CallRepository.py  migrations/

  Models/              SQLAlchemy models (Patient, Address, Call)
  Schemas/             Pydantic contracts + all field validation
  LLM/                 the only place that knows a provider exists
```

**Layer rules.** Controllers never touch a session, with one deliberate
exception: the readiness probe runs `SELECT 1`, because checking the database
*is* its job. Repositories never raise HTTP errors. Services translate between
them and own `commit()`.

**Why validation lives in `Schemas/`.** The voice agent and the REST API are two
front doors onto the same data, and both go through the same Pydantic models, so
a rule is written once.

### Inbound call flow

```
caller -> Vapi number --POST--> /api/v1/vapi/webhook  {"type":"assistant-request"}
                      <--------  {"assistant": {...}}  prompt + 5 tools, from code
       ... conversation ...
                      --POST--> webhook  {"type":"tool-calls"}
                      <--------  {"results":[{"toolCallId":"...","result":"..."}]}
                      --POST--> webhook  {"type":"end-of-call-report"}
                                  1. store transcript, commit, respond 200
                                  2. background task -> OpenAI -> summary
```

**The two-step write.** `create_patient` returns a `patient_id`, then
`save_address` attaches the address by foreign key. The ordering is enforced
twice — `AddressService` resolves the patient before writing, and the FK backs it
at the database level — so a stray foreign key cannot be created.

**The LLM layer.** `app/LLM/` holds the `LLMClient` contract, the OpenAI
implementation (the only file importing the SDK), the summariser that owns the
prompt, and a factory. Another provider is one subclass plus a line in the
factory. Without an API key the factory returns `NullLLMClient` and the app runs
unchanged.

The transcript is committed **before** the model is called, and summarising runs
as a background task after the webhook responds — an OpenAI round trip inside
Vapi's webhook timeout would risk the call report. An outage costs a summary,
never a transcript.

**Response envelope.** Every REST response is `{"data": ..., "error": ...}`.
`error_handlers.py` applies it to validation failures, HTTP errors and unhandled
exceptions too, so the contract holds on failure paths. The Vapi webhook is
exempt — it speaks Vapi's protocol.

---

## API reference

| Method | Route | Purpose |
| ------ | ----- | ------- |
| `GET` | `/api/v1/patients` | List. Filters: `last_name`, `date_of_birth`, `phone_number`, `limit`, `offset` |
| `GET` | `/api/v1/patients/{patient_id}` | Retrieve one |
| `POST` | `/api/v1/patients` | Create; returns the record with `patient_id` |
| `PUT` | `/api/v1/patients/{patient_id}` | Update; partial bodies allowed |
| `DELETE` | `/api/v1/patients/{patient_id}` | Soft-delete (stamps `deleted_at`) |
| `POST` `GET` `PUT` `DELETE` | `/api/v1/patients/{patient_id}/address` | The patient's address |
| `GET` | `/api/v1/calls` | Calls, newest first; filter by `patient_id` |
| `GET` | `/api/v1/calls/{call_id}` | One call with its transcript |
| `POST` | `/api/v1/vapi/webhook` | Vapi server messages (secret-protected) |
| `GET` | `/api/v1/health` · `/api/v1/health/ready` | Liveness · readiness |

**Status codes:** `200` read/update/delete, `201` create, `400` malformed query
param, `404` unknown or soft-deleted, `409` duplicate, `422` validation failure,
`500` unhandled.

Soft-deleted patients are invisible everywhere: excluded from lists, `404` on
fetch, and they no longer block a duplicate check or match a voice lookup.

```bash
curl -X POST http://localhost:8000/api/v1/patients \
  -H "Content-Type: application/json" \
  -d '{"first_name":"Maria","last_name":"OBrien","date_of_birth":"03/15/1985",
       "sex":"Female","phone_number":"(662) 670-1017"}'
```

---

## Data model

### `patients`

| Field | Type | Rules | Required |
| ----- | ---- | ----- | -------- |
| `first_name` · `last_name` | String | 1–50 chars, letters + hyphens/apostrophes | Yes |
| `date_of_birth` | Date | Valid, not future, `MM/DD/YYYY` | Yes |
| `sex` | Enum | `Male`, `Female`, `Other`, `Decline to Answer` | Yes |
| `phone_number` | String | Valid US 10-digit | Yes |
| `email` | String | Valid email | No |
| `insurance_provider` | String | 1–100 chars | No |
| `insurance_member_id` | String | Alphanumeric, 1–50 chars | No |
| `emergency_contact_name` | String | Full name, spaces allowed, 1–100 chars | No |
| `emergency_contact_phone` | String | Valid US 10-digit | No |
| `preferred_language` | String | 1–50 chars | No |

`patient_id` (UUID), `created_at`, `updated_at` and `deleted_at` are server-set
and ignored if sent.

Hyphens and apostrophes are allowed only *between* letters, so `O'Brien` passes
and `Mary--Jane` does not. Phone numbers normalise on input — `(662) 670-1017`,
`+1 662 670 1017` and `662.670.1017` all store as `6626701017` — under NANP
rules. Optional fields sent as `""` store as `NULL`, because a voice agent sends
an empty string rather than omitting a key.

### `addresses`

One per patient, FK to `patients`, `ON DELETE CASCADE`.

| Field | Rules | Required |
| ----- | ----- | -------- |
| `address_line_1` | Street address, 1–200 chars | Yes |
| `address_line_2` | Apt/Suite/Unit, 1–200 chars | No |
| `city` | 1–100 chars | Yes |
| `state` | Valid 2-letter US abbreviation (50 states, DC, territories) | Yes |
| `zip_code` | 5-digit or ZIP+4 | Yes |

State codes normalise to uppercase; ZIPs accept `02116`, `02116-1234` and nine
bare digits.

### `calls`

One row per call: `vapi_call_id` (unique, so repeated webhooks update rather than
duplicate), `transcript`, `summary`, `summary_status`, `summary_error`,
`patient_id` when the call created or updated one, plus `caller_number`,
`ended_reason`, `duration_seconds`, `started_at` and `ended_at`.

`summary_status` (`pending` · `ready` · `failed` · `skipped`) means a `NULL`
summary is never ambiguous — no transcript or no API key is `skipped`, a provider
error is `failed` with the reason kept.

All timestamps are `timestamptz`, stored as absolute instants and emitted as UTC
with a trailing `Z`.

### Migrations

```bash
alembic upgrade head          # applied automatically on container start
alembic upgrade head --sql    # render DDL without connecting
```

Scripts live in `app/Repository/migrations/`; `alembic.ini` stays at the root so
the CLI needs no `-c`.

---

## The voice agent

Prompt, first message and tool schemas live in
[`app/Services/VapiAssistant.py`](app/Services/VapiAssistant.py). Changes take
effect on the next call.

**Scope.** Opens with *"Hi there! Welcome to {CLINIC_NAME}. How can I help you
today?"* and does exactly two things: register a patient, update an existing one.
It refuses everything else in one sentence — appointments, test results,
symptoms, billing, prescriptions, transfers — never gives medical advice, and on
anything urgent says *"If this is an emergency, please hang up and dial 911."*
and ends the call.

**Identity verification.** A caller must match **both** a phone number and a date
of birth before anything stored is disclosed. Enforced in code, not just the
prompt: `lookup_patient` requires both arguments and the repository filters on
both columns — there is no lookup-by-phone path.

| Caller supplies | Result |
| --------------- | ------ |
| Phone + matching DOB | Verified; name disclosed, update offered |
| Phone + wrong DOB | "No match" — nothing disclosed, treated as new |
| Phone with no DOB | Refused; the tool will not run |

A failed match is deliberately indistinguishable from an unrecognised number, and
the agent never invites a second guess — otherwise the flow becomes an oracle for
probing whose record exists. Phone alone is not identity: caller ID is spoofable
and disconnected numbers get recycled.

**Conversation behaviour.**

| Requirement | How it is met |
| ----------- | ------------- |
| Natural, not IVR | Forbids "press or say" and numbered options; takes several values volunteered at once; accepts varied date phrasing and mid-sentence self-corrections |
| Confirmation | Reads every collected field back as spoken values, invites correction, and only then saves |
| Error handling | Tool failures return the offending **field names**; the agent re-prompts for only those, keeping everything else. Three failures on one field ends with a staff callback rather than looping |
| Call completion | A personalised sign-off, then the built-in `endCall` tool. After an *update* it asks whether there is anything else and continues until the caller says no |

**Tools.** `lookup_patient` (phone + DOB), `create_patient`, `save_address`,
`update_patient`, and Vapi's built-in `endCall`. The assistant sets
`serverMessages` to the three types the service acts on, so Vapi does not also
send a per-utterance firehose.

---

## Frontend

A single static page at the API's base URL for viewing registered patients.
Read-only: no form, no write path. `frontend/index.html` is the whole thing — no
build step, no `package.json`. FastAPI mounts it after the routers, so
`/api/v1/*` and `/docs` still match first and an unknown path 404s.

Lists live patients with search by last name (using the API's own `?last_name=`
filter), and expands a row to show insurance, emergency contact, preferred
language and the address as separate fields, fetched on demand. Dark and light
themes follow the OS.

---

## Testing

```bash
pytest
```

273 tests, no database or network required — repositories and LLM clients are
faked, so the suite runs in about two seconds.

| File | Covers |
| ---- | ------ |
| `test_patient_schema.py` · `test_patient_optional_fields.py` | Field rules, opt-in extras, UTC timestamps |
| `test_address.py` | Address rules, state/ZIP normalisation, save ordering |
| `test_vapi_webhook.py` · `test_vapi_lookup_update.py` | Webhook auth, every tool-call payload shape Vapi uses, verification and update flow |
| `test_call_recording.py` · `test_llm_layer.py` | Transcript storage, summary status transitions, provider contract and failure modes |
| `test_functional_requirements.py` | The assessment's functional requirements |
| `test_health.py` | Liveness, readiness, routing |

---

## Known limitations and trade-offs

Most are conscious decisions to fit the time budget, not oversights.

### Security and PHI

- **The REST API has no authentication.** Every endpoint is open to anyone who
  can reach the port; only the Vapi webhook is protected, by a shared-secret
  header. This is the largest gap — production needs auth in front of it.
- **Identity verification is a weak shared secret.** A date of birth is not hard
  to obtain. Reasonable for a line that only confirms a caller's own contact
  details; *not* sufficient for disclosing clinical information.
- **No BAA, and Vapi's HIPAA mode is off.** Names, dates of birth, phone numbers
  and addresses flow through Vapi, and recordings and transcripts are retained
  there by default. Transcripts are also sent to OpenAI for summarising.
- **`LOG_PAYLOADS=true` writes PHI to logs.** Defaults to `false`.
- **No rate limiting**, and `.env` holds secrets in plaintext.

### Data and correctness

- **Name validation is ASCII-only and rejects spaces.** `José`, `Müller` and
  `Van Der Berg` all fail. A literal reading of the supplied spec; for real
  patient names it would need widening to Unicode.
- **Dates are `MM/DD/YYYY` only** — ISO input is rejected.
- **"Not in the future" is enforced only in the application**, since PostgreSQL
  rejects `CURRENT_DATE` in a `CHECK` constraint.
- **Duplicate detection uses name + date of birth**, so two genuinely different
  people sharing both would collide.
- **`sex` is a native PostgreSQL enum**, so adding a value needs `ALTER TYPE`.
- **Migration `0002` backfilled existing rows with placeholders**
  (`phone_number = '0000000000'`, `sex = 'Decline to Answer'`) because the
  columns were added `NOT NULL` to a populated table. Rows predating it need a
  real backfill.
- **One address per patient**, enforced by a unique constraint.

### Resilience

- **A dropped call loses everything not yet written.** Values live in the
  conversation until a tool fires, and the two-step write is not atomic, so
  dropping between `create_patient` and `save_address` leaves a patient with no
  address. Nothing detects or repairs that — see [Next steps](#next-steps).
- **"Start over" is not handled.** A caller asking to restart mid-conversation
  has no explicit path; the agent will improvise.
- **Summarisation is an in-process background task.** A restart between the
  webhook response and the task loses that summary and leaves the row `pending`.
  There is no retry and no worker.
- A failed database write *is* handled — the caller hears a spoken apology
  rather than silence.

### Operations

- The tunnel URL changes whenever ngrok restarts; `PUBLIC_BASE_URL`, the
  container and the Vapi Server URL must be updated together.
- Migrations run in the container entrypoint, which would race across replicas.
- Changes outside `app/` and `frontend/` need a rebuild.
- No CI.
- The frontend inherits the open API and requests up to 200 patients with no
  paging.

### The agent

- **Prompt instructions are not guarantees.** Tests assert an instruction is
  present and that tools return field-scoped errors; they cannot prove the model
  obeys on a live call.
- The prompt promises a staff follow-up after repeated failures, but nothing
  queues that request.
- Summaries have no evaluation harness — nothing checks a summary against its
  transcript.

---

## Next steps

### Deployment

**Not deployed — this submission runs locally behind an ngrok tunnel.** Given
more time I would host it on **Railway**: it deploys from the existing
`Dockerfile` and provisions managed PostgreSQL, and `entrypoint.sh` already runs
migrations on boot, so the rest is setting the documented environment variables.
A stable HTTPS domain would also remove the tunnel churn above.

One gotcha: Railway exposes its database as `postgresql://…`, so `DATABASE_URL`
needs the `postgresql+asyncpg://` prefix rather than the value verbatim.

### Handling dropped calls

A line failing part-way through is normal, not exceptional, and is the largest
functional gap. The transcript is still stored and `ended_reason` recorded, but
nothing acts on it: partial answers are lost, an incomplete registration is never
flagged, and a caller ringing back starts over.

The fix I would reach for first is a reconciliation job — treat "a patient with
no address" and "a call that ended without producing one" as incomplete, surface
them in a queue, and have the agent offer to finish the record on a callback.
Persisting partial answers during the call would shrink the window further.

### Not implemented

Two optional bonus challenges were left out, neither started.

**Multi-language support.** The agent runs in English only; *"Hablo español"*
gets an English reply. Vapi supports this through its transcriber and voice
settings, so the work is contained — detect the language, swap the transcriber
locale and TTS voice, translate the prompt. `preferred_language` is stored but
**does not change how the agent speaks**, and nothing has been tested in any
language other than English.

**Appointment scheduling.** Not built; the agent refuses scheduling as out of
scope. Adding it means a slots table, an availability lookup and a booking tool
alongside the existing four — additive rather than structural.

### Beyond that

In priority order: authentication on the REST API; a Vapi BAA plus HIPAA mode and
a retention policy; a job queue for summaries with retries; widening name
validation to Unicode; an audit log of record access; and CI.
