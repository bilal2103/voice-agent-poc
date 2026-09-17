# Healthcare Voice Agent — Backend

FastAPI backend with a Controller → Service → Repository layering, PostgreSQL,
and Alembic migrations.

## Requirements

- Docker Desktop (recommended), or Python 3.11+ and a local PostgreSQL 13+

## Run with Docker

```bash
cp .env.example .env
docker compose up --build
```

This starts PostgreSQL 16 and the API. The api container waits for the database
healthcheck, applies migrations (`alembic upgrade head`) via `entrypoint.sh`,
then serves on http://localhost:8000.

Useful commands:

```bash
docker compose logs -f api
docker compose exec api alembic current
docker compose exec db psql -U postgres -d healthcare_voice_agent -c "\d patients"
docker compose down -v          # also drops the pgdata volume
```

## Run locally (without Docker)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements-dev.txt
cp .env.example .env            # point DATABASE_URL at your PostgreSQL
alembic upgrade head
uvicorn app.main:app --reload
```

## Endpoints

All REST responses use the envelope `{"data": ..., "error": ...}` — on success
`error` is `null`, on failure `data` is `null`. The Vapi webhook is exempt: it
speaks Vapi's protocol.

| Method   | Route                              | Purpose                                                        |
| -------- | ---------------------------------- | -------------------------------------------------------------- |
| `GET`    | `/api/v1/patients`                 | List. Filters: `last_name`, `date_of_birth`, `phone_number`, plus `limit`/`offset` |
| `GET`    | `/api/v1/patients/{patient_id}`    | Retrieve one by UUID                                            |
| `POST`   | `/api/v1/patients`                 | Create; returns the record with `patient_id`                    |
| `PUT`    | `/api/v1/patients/{patient_id}`    | Update; partial bodies allowed                                  |
| `DELETE` | `/api/v1/patients/{patient_id}`    | Soft-delete (stamps `deleted_at`; the row is never removed)     |
| `POST`   | `/api/v1/patients/{patient_id}/address` | Save the patient's address (patient must exist)             |
| `GET`    | `/api/v1/patients/{patient_id}/address` | Retrieve it                                                 |
| `PUT`    | `/api/v1/patients/{patient_id}/address` | Update it; partial bodies allowed                           |
| `DELETE` | `/api/v1/patients/{patient_id}/address` | Remove it                                                   |
| `GET`    | `/api/v1/calls`                    | List calls, newest first; filter by `patient_id`                |
| `GET`    | `/api/v1/calls/{call_id}`          | One call with its full transcript                               |
| `GET`    | `/api/v1/health`                   | Liveness                                                        |
| `GET`    | `/api/v1/health/ready`             | Readiness (pings the database)                                  |
| `GET`    | `/docs`                            | Swagger UI                                                      |

Status codes: `200` read/update/delete, `201` create, `400` malformed query
param, `404` unknown or already-deleted patient, `409` duplicate name + DOB,
`422` field validation failure, `500` unhandled error.

Soft-deleted patients are invisible everywhere: excluded from lists, `404` on
fetch, and they no longer block a duplicate check.

```bash
curl -X POST http://localhost:8000/api/v1/patients \
  -H "Content-Type: application/json" \
  -d '{"first_name":"Maria","last_name":"O'\''Brien","date_of_birth":"03/15/1985",
       "sex":"Female","phone_number":"(662) 670-1017","email":"maria@example.com"}'

curl "http://localhost:8000/api/v1/patients?last_name=O'Brien&date_of_birth=03/15/1985"
curl -X PUT http://localhost:8000/api/v1/patients/<uuid> \
  -H "Content-Type: application/json" -d '{"email":"new@example.com"}'
```

## Test

```bash
pytest
```

## Layout

```
app/
  main.py                 # create_app(), middleware, router mounting
  config.py               # Settings from env / .env
  dependencies.py         # Controller -> Service -> Repository wiring
  router.py               # aggregates controllers under /api/v1
  Controllers/            # HTTP only: parse request, map errors to status codes
    HealthController.py
    PatientController.py
  Services/               # business rules, owns the transaction (commit)
    PatientService.py
  Repository/             # everything that talks to the database
    database.py             # async engine, session factory, Base, get_db
    PatientRepository.py    # ORM queries only
    migrations/             # Alembic; env.py reads DATABASE_URL from Settings
      versions/
  Models/                 # SQLAlchemy ORM models
    Patient.py
  Schemas/                # Pydantic request/response contracts + validation
    Patient.py
tests/
alembic.ini               # stays at root so `alembic ...` works without -c
```

Layer rules: controllers never touch the session, repositories never raise HTTP
errors, and services translate between them. Services call `commit()`;
`get_db` only guarantees rollback-on-error and close.

## Patient field rules

| Field           | Type   | Rules                                             | Required |
| --------------- | ------ | ------------------------------------------------- | -------- |
| `first_name`    | String | 1–50 chars, letters + hyphens/apostrophes          | Yes      |
| `last_name`     | String | 1–50 chars, letters + hyphens/apostrophes          | Yes      |
| `date_of_birth` | Date   | Valid date, not in the future, `MM/DD/YYYY`        | Yes      |
| `sex`           | Enum   | `Male`, `Female`, `Other`, `Decline to Answer`     | Yes      |
| `phone_number`  | String | Valid US 10-digit number                           | Yes      |
| `email`         | String | Valid email format                                 | No       |
| `insurance_provider` | String | Company name, 1–100 chars                     | No       |
| `insurance_member_id` | String | Alphanumeric only, 1–50 chars                | No       |
| `emergency_contact_name` | String | Full name; spaces allowed, 1–100 chars    | No       |
| `emergency_contact_phone` | String | Valid US 10-digit number                 | No       |
| `preferred_language` | String | Language name, 1–50 chars                     | No       |

`patient_id` (UUID), `created_at`, `updated_at` and `deleted_at` are set by the
server and ignored if sent. Timestamps are `timestamptz`, stored as absolute
instants and always emitted as UTC with a trailing `Z`; both containers pin
`TZ=UTC` so a host timezone cannot shift them.

Optional fields are opt-in, never demanded. An empty string is treated as "not
provided" and stored as `NULL`, because a voice agent sends `""` rather than
omitting a key.

Phone numbers are normalised on the way in: `(662) 670-1017`, `+1 662 670 1017`
and `662.670.1017` all store as `6626701017`. NANP rules apply, so the area code
and exchange code cannot begin with 0 or 1. The `?phone_number=` filter accepts
the same formats.

Hyphens and apostrophes are allowed only between letters, so `O'Brien` and
`Anne-Marie` pass while `-Ann` and `Mary--Jane` do not. Dates are accepted and
returned as `MM/DD/YYYY`.

## Address

One address per patient, in its own table with a foreign key. The patient is
saved first; the address is attached afterwards. `AddressService` resolves the
patient before writing, so a stray foreign key cannot be created, and the
`ON DELETE CASCADE` means removing a patient row takes its address with it.

| Field            | Type   | Rules                                     | Required |
| ---------------- | ------ | ----------------------------------------- | -------- |
| `address_line_1` | String | Street address, 1–200 chars               | Yes      |
| `address_line_2` | String | Apt/Suite/Unit, 1–200 chars               | No       |
| `city`           | String | 1–100 characters                          | Yes      |
| `state`          | String | Valid 2-letter US state abbreviation      | Yes      |
| `zip_code`       | String | 5-digit or ZIP+4                          | Yes      |

State codes cover the 50 states, DC, territories and military posts, and are
normalised to uppercase (`ma` becomes `MA`). ZIP codes accept `02116`,
`02116-1234`, and nine bare digits, which are formatted as ZIP+4.

`POST` returns `409` if an address already exists; the voice agent instead uses
an upsert, so a caller correcting a misheard street does not hit a conflict.

## Call records

Every call is stored in `calls` with its transcript, and summarised by the LLM
layer. See **LLM layer** below.

| Column                          | Meaning                                              |
| ------------------------------- | ---------------------------------------------------- |
| `vapi_call_id`                  | Unique; repeated webhooks update one row             |
| `transcript`                    | Verbatim, from the `end-of-call-report` artifact     |
| `summary` / `summary_status`    | `pending`, `ready`, `failed` or `skipped`            |
| `summary_error`                 | Why it is not `ready`                                |
| `patient_id`                    | Set when the call created or updated a patient       |
| `caller_number`, `ended_reason`, `duration_seconds`, `started_at`, `ended_at` | Call metadata |

`summary_status` exists so a `NULL` summary is never ambiguous: no transcript
and no API key are `skipped`, a provider error is `failed` with the reason kept.

## LLM layer

`app/LLM/` is the only place that knows about a model provider.

```
app/LLM/
  base.py           # LLMClient contract, LLMError, NullLLMClient
  OpenAIClient.py   # the only file that imports the OpenAI SDK
  CallSummarizer.py # owns the summary prompt and transcript handling
  factory.py        # picks a client from settings
```

Everything above depends on `LLMClient`, never on a vendor SDK, so another
provider is one new subclass plus a line in `factory.py`.

The transcript is committed **before** the model is called, and summarising runs
as a background task after the webhook has already responded — an OpenAI round
trip inside Vapi's webhook timeout would risk the call report. A provider
outage therefore costs a summary, never the transcript.

Without `OPENAI_API_KEY` the factory returns `NullLLMClient`: transcripts are
still stored and summaries are marked `skipped`.

The summary prompt forbids inferring anything clinical and forbids repeating the
caller's contact details, so summaries stay safe to read at a glance.

## Migrations

```bash
alembic revision --autogenerate -m "add something"   # needs a reachable database
alembic upgrade head
alembic downgrade -1
alembic upgrade head --sql                           # render DDL without connecting
```

Import new models in `app/Repository/migrations/env.py` so autogenerate sees them.

The migration scripts live under `app/Repository/`; `alembic.ini` stays at the
project root and points at them via `script_location`, so the CLI works from
the root with no `-c` flag.

## Vapi voice agent

Inbound calls are driven from this server: the phone number's Server URL points
here, so Vapi asks for the assistant at call time rather than using one saved in
the dashboard.

```
caller -> Vapi number -> POST /api/v1/vapi/webhook  {"type":"assistant-request"}
                      <- {"assistant": {...}}          prompt + 3 tools:
                                                       lookup_patient (phone + DOB)
                                                       create_patient
                                                       update_patient
       ... conversation ...
                      -> POST /api/v1/vapi/webhook  {"type":"tool-calls"}
                      <- {"results":[{"toolCallId":"...","result":"..."}]}
                      -> status-update / end-of-call-report   (logged, no reply)
```

All of it lands on one endpoint, [app/Controllers/VapiController.py](app/Controllers/VapiController.py).

### Local setup

1. Expose the API publicly — Vapi cannot reach `localhost`:

   ```bash
   ngrok http 8000
   ```

2. Put the forwarding URL and a secret you invent in `.env`:

   ```
   PUBLIC_BASE_URL=https://<subdomain>.ngrok-free.app
   VAPI_SECRET=<any long random string>
   ```

   `PUBLIC_BASE_URL` is what the assistant's tool `server.url` is built from, so
   it must be the public URL, not `localhost`. Restart the API after changing it.

3. In the Vapi dashboard, open **Phone numbers → your number**:
   - **Server URL**: `https://<subdomain>.ngrok-free.app/api/v1/vapi/webhook`
   - **Timeout**: 20s is fine (`assistant-request` must answer within 7.5s).
   - **Authorization → HTTP Headers → Add Header**: name `x-vapi-secret`,
     value the same string as `VAPI_SECRET`.
   - Leave the inbound assistant unset so Vapi falls back to `assistant-request`.

4. Call the number.

### Server URL precedence

Vapi picks the most specific URL configured: **custom tool → assistant → phone
number → account**. The assistant returned by `assistant-request` sets the tool's
`server.url` explicitly, so tool calls always come back here even if the
dashboard changes.

### Checking it without calling

```bash
curl -X POST http://localhost:8000/api/v1/vapi/webhook \
  -H "Content-Type: application/json" -H "x-vapi-secret: $VAPI_SECRET" \
  -d '{"message":{"type":"assistant-request","call":{"id":"test"}}}'

curl -X POST http://localhost:8000/api/v1/vapi/webhook \
  -H "Content-Type: application/json" -H "x-vapi-secret: $VAPI_SECRET" \
  -d '{"message":{"type":"tool-calls","toolCallList":[{"id":"t1","name":"create_patient","arguments":{"first_name":"Maria","last_name":"OBrien","date_of_birth":"03/15/1985"}}]}}'
```

### Identity verification

**A caller must match both a phone number and a date of birth before any stored
information is disclosed.** This is enforced in code, not only in the prompt:
`lookup_patient` requires both arguments, and
`PatientRepository.list_by_phone_and_dob` filters on both columns. There is no
lookup-by-phone path.

Why phone alone is not enough:

- **Caller ID is spoofable.** Setting an arbitrary caller ID costs nothing, so
  an inbound number is an unauthenticated claim, not proof of identity.
- **Numbers get reassigned.** US carriers recycle disconnected mobile numbers
  after roughly 45 days. Whoever holds the number next would otherwise be read a
  stranger's name and be able to edit their record.
- **Households share lines.** A match on a shared number may be a relative
  rather than the caller.

What that buys:

| Caller supplies            | Result                                             |
| -------------------------- | -------------------------------------------------- |
| Phone + matching DOB        | Verified; name disclosed, update offered           |
| Phone + wrong DOB           | "No match" — nothing disclosed, treated as new     |
| Phone with no DOB           | Refused; the tool will not run                     |
| Matching DOB, wrong phone   | "No match"                                         |

A failed match is deliberately indistinguishable from an unrecognised number.
The agent is instructed never to say whether a number is on file and never to
invite a second guess at the date of birth, so the flow cannot be used to probe
for whose record exists. When two records match — twins on one family line —
only first names are read out.

Asking for the date of birth costs the caller nothing: it is a required field
for registration anyway, so an unmatched lookup wastes no time.

**This is authentication by shared secret, and a weak one.** A date of birth is
not hard to obtain. It is a reasonable bar for a phone intake line, but it is
not sufficient for disclosing clinical information, and it is not a substitute
for identity proofing if this system ever returns test results, notes or
anything beyond the caller's own contact details. Revisit it before widening
what the agent can read out.

### Scope

The agent opens with an open question:

> "Hi there! Welcome to Bilal's Clinic. How can I help you today?"

Set the name with `CLINIC_NAME` in `.env`; it feeds both the greeting and the
agent's self-description.

Because the greeting is open-ended, the prompt has to hold the boundary. The
agent does **two** things — register a patient, and update an existing patient's
details — and refuses everything else in one sentence: appointments, test or lab
results, symptoms, diagnoses, medicines, treatment, billing, claims, referrals,
prescriptions, taking messages, or transferring the call.

It never gives medical advice of any kind, and if a caller describes anything
urgent it says *"If this is an emergency, please hang up and dial 911."* and ends
the call rather than continuing with intake.

Both registering and updating start identically — phone number, then date of
birth, then `lookup_patient` — so the agent never asks "are you a new or
existing patient?". The lookup answers that.

### How the call flows

The agent opens by collecting the phone number and date of birth, then calls
`lookup_patient`. A verified match is offered an update; anything else proceeds
as a new registration, with both values already in hand.

For a new registration it collects the remaining required fields, then makes a
single offer:

> "I can also collect your insurance information, emergency contact, and
> preferred language. Would you like to provide any of those?"

If the caller declines it saves and finishes. If they opt in, it collects only
what they name. It never walks the optional items one at a time — that turns a
two-minute call into a five-minute interrogation.

### Conversation requirements

The prompt in [app/Services/VapiAssistant.py](app/Services/VapiAssistant.py)
covers four behaviours, each pinned by tests in
`tests/test_functional_requirements.py` so a prompt edit cannot silently drop one.

| Requirement      | How it is met                                                                                                   |
| ---------------- | --------------------------------------------------------------------------------------------------------------- |
| Voice interaction | Explicitly forbids IVR phrasing ("press or say", numbered options); takes several values volunteered at once; accepts varied date phrasing and mid-sentence self-corrections; asks a clarifying question rather than guessing |
| Confirmation      | Reads every collected field back — including optional ones — as spoken values rather than field names, invites correction of anything, and only then calls `create_patient` |
| Error handling    | Obvious problems are caught before a tool call; tool failures return the offending field names, and the agent re-prompts for **only** those, keeping everything else. Three failures on one field ends with a staff callback rather than a loop |
| Call completion   | A one-line personalised sign-off ("You're all set, Maria.") then the built-in `endCall` tool hangs up. Also ends when the caller says goodbye |

After a **new registration** the agent signs off immediately. After an **update**
it must ask whether there is anything else to change and keep going until the
caller says no — callers routinely remember a second thing once the first is
done. That rule lives in both the prompt and the `update_patient` tool result,
because the tool result is the fresher context at the moment the agent decides
whether to hang up.

`endCallMessage` is deliberately **not** set. It is a fixed string, so it cannot
contain the caller's name and would play on top of the agent's own sign-off.
The `endCall` tool gives the agent control of both the wording and the hangup.

### Editing the agent

The prompt, first message and tool schema all live in
[app/Services/VapiAssistant.py](app/Services/VapiAssistant.py). Changes take
effect on the next call — nothing to re-publish in the dashboard.

### Gotchas worth knowing

- `docker compose restart` does **not** re-read `.env`. After changing it run
  `docker compose up -d api`, which recreates the container.
- `VAPI_SECRET_HEADER` is a header *name* (`x-vapi-secret`), not the secret.
  Putting a value there used to 401 every webhook silently; the app now refuses
  to start instead.
- The ngrok URL changes each time ngrok restarts on the free tier. Update
  `PUBLIC_BASE_URL`, recreate the api container, and update the Server URL in
  the Vapi dashboard.
