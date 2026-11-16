# AI Recruiter

AI video interviews by [Abhilash N L](https://github.com/nlabhilash29).

A candidate opens a link and has a spoken conversation with an AI interviewer. The interviewer asks the next question on its own, transcribes the answer, and scores it. A recruiter creates the interview, copies a candidate link, and reads the results. The recruiter desk is open unless `RECRUITER_AUTH_REQUIRED` is turned on.

## Live demo

- Frontend: https://ai-recruiter-one-sigma.vercel.app
- Backend: https://ai-recruiter-x7qm.onrender.com
- Source: https://github.com/nlabhilash29/ai-recruiter

The Render service is on the free plan and sleeps when idle. The first request can take up to a minute. The app shows "The interviewer is getting ready. This can take up to a minute." while the API wakes up.

## Tech stack

- **React** (Create React App) for the interface, deployed on Vercel.
- **FastAPI** and **SQLAlchemy** for the API, deployed on Render (Python 3.11).
- **Groq `openai/gpt-oss-120b`** for interview questions, job-description drafts, and scoring.
- **OpenAI Whisper** for speech to text.
- **ElevenLabs** for speaking the questions.
- **SQLite** locally, **Postgres** when `DATABASE_URL` is set.

## Features

**Candidate interview**

- The Candidate tab asks for a name, then an interview link, or “Do you want to practice first? Click here.” Practice asks for a job description and a resume. A direct `/interview/:id` link skips that page.
- Deep links stay at `/interview/:id`.
- Microphone and camera check, including a short room-noise calibration. Only audio is recorded and transcribed. The camera is a framing preview and is not uploaded.
- One **Begin interview** click unlocks audio. After that there are no Start, Stop, Re-record, or Submit buttons. The interviewer speaks, then listens. About 2.8 seconds of silence after speech ends the answer. A live microphone level, "Listening…", and "Moving on in 2…" keep the state obvious. Resumed speech cancels the countdown.
- No speech for about 15 seconds replays the question once, then moves on without a score. Answers stop before the 5 MB upload limit. After the last answer the interviewer says goodbye, and a Go back button returns to the Candidate tab.
- Every new interview is five AI-generated questions. "Question X of 5" counts those questions. Older interviews that stored a different count or a fixed list still play.

**Recruiter area**

- Two tabs only, in this order: Recruiter (the default) and Candidate. The recruiter page pastes a job description and a resume, then shows an interview link to copy. It does not start the interview, and it does not wait on the access check before rendering. Questions are generated only when both documents are present.
- Open by default. Set `RECRUITER_AUTH_REQUIRED=true` to require `RECRUITER_PASSCODE`. The passcode alone does not lock the desk.
- **View candidate reports** lists completed interviews, titled with the candidate's name and a short role title.
- The role used for rubric weights is inferred from the job description and resume. There is no role picker and no question-count or preset-question control.

**Results**

- Five dimensions, scored 1–10 only when the answer contains evidence: problem solving, communication, role knowledge, ownership and impact, collaboration. Missing evidence stays "Not assessed".
- Role weights differ for Software Developer, Forward-Deployed Engineer, Product Manager, Sales, and a general mix. The report shows the weight, the evidence quote, and the nearest 1–10 anchor.
- The recommendation is Strong yes, Yes, Mixed, No, or not enough evidence.
- Older interviews that only have technical, communication, and cultural-fit scores still render with the earlier explanation.
- Empty feedback labels are hidden. A missing model reply is retried, then replaced with a short fallback so Feedback is never blank.

## Architecture

```
Browser (Vercel)
  /                         Recruiter tab: paste a job description and resume, copy the link
  /candidate                Candidate tab: start from a link, or practice
  /interview/:id            hands-free interview from a recruiter link
  /interview/:id/results    score report
  /recruiter                same recruiter desk
  /recruiter/interviews/:id recruiter report
        |
        |  HTTPS, REACT_APP_API_URL
        v
FastAPI (Render)
  /health, /mock-interview, /talk-video, /interview/:id/session
  /recruiter/access         says whether a passcode is required
        |
        +-- Whisper      audio -> transcript
        +-- Groq         questions, follow-ups, and rubric scores
        +-- ElevenLabs   question audio
        +-- SQLite or Postgres
```

`frontend/ai-recruiter-frontend/vercel.json` rewrites client routes to `index.html`, so a refresh on `/interview/:id` or `/recruiter` still loads the app.

Recruiter routes are public unless `RECRUITER_AUTH_REQUIRED` is true. When that flag is on, they check an HMAC token derived from `RECRUITER_PASSCODE` (12 hours, stored in `localStorage`). If the flag is on and the passcode is unset, those routes return HTTP 503 and name the missing variable. Candidate interview links work either way.

The API process starts even when a provider key is missing. The route that needs the key returns HTTP 503 and names it. `AI_STUB=1` skips Groq, Whisper, and ElevenLabs for a local demo.

## Local setup

Requirements: Node.js and npm, Python 3.11, and the environment variables below.

```bash
git clone https://github.com/nlabhilash29/ai-recruiter.git
cd ai-recruiter
```

Backend, from `backend/`:

```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Frontend, from `frontend/ai-recruiter-frontend/`:

```bash
npm ci
cp .env.example .env.local
npm start
```

The UI is at http://localhost:3000 and the API at http://localhost:8000.

Tests, from `backend/`:

```bash
python -m unittest discover tests
```

Frontend production build:

```bash
CI=true npm run build
```

## Environment variables

Names only. Put real values in `backend/.env` and in the host's dashboard, not in git. Defaults and comments are in `backend/.env.example` and `frontend/ai-recruiter-frontend/.env.example`.

**Backend (Render)**

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Whisper transcription |
| `GROQ_API_KEY` | Questions and scoring |
| `GROQ_MODEL` | Groq model id. Default is `openai/gpt-oss-120b` |
| `GROQ_REASONING_EFFORT` | Reasoning budget. Default is `low` |
| `ELEVENLABS_API_KEY` | Spoken questions |
| `ELEVENLABS_MODEL_ID` | ElevenLabs model. Default is `eleven_flash_v2_5` |
| `ELEVENLABS_VOICE_ID` | ElevenLabs voice |
| `RECRUITER_AUTH_REQUIRED` | Set to `true` to lock the recruiter area. Off by default |
| `RECRUITER_PASSCODE` | Shared passcode. Used only when `RECRUITER_AUTH_REQUIRED` is true |
| `DATABASE_URL` | Postgres URL. Omit it locally to use SQLite |
| `CORS_ORIGINS` | Extra browser origins, comma-separated |
| `AI_STUB` | Set to `1` to skip the AI providers locally |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key. Tracing stays local until this, the secret, and the host are all set |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key |
| `LANGFUSE_HOST` | Langfuse host for the project region, such as `https://us.cloud.langfuse.com` |
| `AI_RECRUITER_TRACES` | Set to `off` to disable traces. On by default outside tests |
| `TRACES_DIR` | Folder for local JSONL traces. Default is `backend/.traces` |
| `MODEL_PRICES_JSON` | Optional token prices in USD per 1,000,000 tokens |

Do not set `llama3-70b-8192` or `eleven_monolingual_v1`. Those model ids were removed by the providers.

**Frontend (Vercel)**

| Variable | Purpose |
| --- | --- |
| `REACT_APP_API_URL` | FastAPI origin, no trailing slash. Read at build time |

Locally this is `http://localhost:8000`. On Vercel it is the Render origin. Changing it requires a new Vercel deploy.

## Observability and quality

Each interview is one trace. The Langfuse session id is the interview id, and the trace id is that id with the dashes removed, so every later request joins the same trace. A span records the model, the prompt, the reply, token usage, latency, estimated cost, and which structured-output path and retries were used. Spans cover question generation, transcription, scoring, the next question, a follow-up when one is asked, and speech.

Traces are written to `backend/.traces/*.jsonl` whenever tracing is on. They are sent to Langfuse as OpenTelemetry spans (`POST /api/public/otel/v1/traces`, header `x-langfuse-ingestion-version: 4`) when `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST` are all set. Use the host for the project's region. The older `/api/public/ingestion` batch stopped storing traces on 16 November 2026: it still returns HTTP 207 while rejecting each event, and that 207 is logged when the body lists errors. A refused key or a network error leaves the interview running and keeps the local file. Emails and phone numbers are masked before they are written. Unit tests leave tracing off unless `AI_RECRUITER_TRACES=1`.

The report link is `https://<host>/project/<projectId>/traces/<traceId>`. The project id comes from `GET /api/public/projects`. After deploy, confirm the connection:

```bash
curl -X POST https://ai-recruiter-x7qm.onrender.com/recruiter/langfuse/test
```

The JSON includes `http_status`, `errors`, and `trace_url`. Open `trace_url`. A span named `langfuse.connectivity` should be on that trace. The API log records the first ingestion status and any later rejection, with Langfuse's message and without the keys. Send the recruiter bearer token when `RECRUITER_AUTH_REQUIRED=true`.

Cost is estimated from token counts. The built-in table prices `openai/gpt-oss-120b` at $0.15 per million input tokens and $0.60 per million output tokens. Replace those rates with `MODEL_PRICES_JSON` when the invoice differs.

On the recruiter report, **How this score was built** shows the evidence check, model, latency, cost, prompt version, and a fallback badge. The confidence line is deterministic: it checks that the evidence quote is in the transcript, that a dimension was not scored without a quote, that the answer is not too thin, and that a fallback was not used. It does not call a model. When Langfuse is configured, the panel links to that interview's trace.

If scoring fails, the answer stays **Not assessed — scoring unavailable**, with empty dimension scores. Silence and answers that are too thin to score use that same empty state. A fallback (default questions, a thin answer, or a scoring failure) is an error event on the trace.

Thumbs on a question save a recruiter verdict: helpful or not, an optional reason (score too high, score too low, evidence not in the answer, bad question, transcription error, other), an optional 1–10 override, and a note. The verdict is stored on the answer and, when Langfuse is configured, posted as a score on the trace. Export it with:

```bash
curl -o feedback.csv https://ai-recruiter-x7qm.onrender.com/recruiter/feedback.csv
```

or, from `backend/`:

```bash
python scripts/export_feedback.py --output feedback.csv
```

`docs/error-analysis.md` is the worksheet for sorting that export into the failure taxonomy.

**Demo**

1. Set the three `LANGFUSE_*` variables on Render and redeploy. `GET /health` reports `observability.langfuse: true`.
2. Run one interview. Open the recruiter report. Each question shows how the score was built, and **Open this interview in Langfuse** opens the trace with a span per step.
3. Mark one score **Not helpful**, choose **Evidence not in the answer**, optionally enter a score override, and save. The same trace in Langfuse gains a `recruiter.vote` score.
4. Download `/recruiter/feedback.csv` and drop the row into `docs/error-analysis.md`.

With `AI_STUB=1` and no Langfuse keys, the report still shows the panel from the stub score, and the trace file is local only.

## Deployment

**Render (API)**

- Root directory: `backend/`
- Runtime: Python 3.11
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Set the backend variables above. Use the Render Postgres URL for `DATABASE_URL`. `postgres://` is accepted and rewritten to `postgresql+psycopg2://`.
- SQLite on the instance disk does not survive free-plan restarts.

**Vercel (frontend)**

- Root directory: `frontend/ai-recruiter-frontend`
- Build command: `npm run build`
- Output directory: `build`
- Set `REACT_APP_API_URL` to `https://ai-recruiter-x7qm.onrender.com` and redeploy.

CORS already allows the production Vercel domain, localhost, and `https://*.vercel.app`.

## What I built

This fork is the work in [nlabhilash29/ai-recruiter](https://github.com/nlabhilash29/ai-recruiter):

- **Deployment fixes.** The API boots without every provider key and names the missing one with HTTP 503. Recordings are sent to Whisper in their real format. Question edits no longer write a column that does not exist. Retired Groq and ElevenLabs model ids are not the defaults. A clean frontend install no longer depends on `react-mic`.
- **Feedback reliability.** Scores and feedback survive multiline labels, markdown headings, and JSON. Empty feedback is retried, then filled with a short fallback, and improvement notes are stored and shown.
- **Recruiter and Candidate tabs.** The Recruiter tab is the default. The Candidate tab pastes an interview link or practices. A sent link still opens `/interview/:id`. The desk is open unless `RECRUITER_AUTH_REQUIRED=true`.
- **Hands-free interviews.** Five AI-generated questions, browser voice detection, and a five-dimension rubric. The role weight is inferred from the job description and resume.
- **Results redesign.** Summary card, score bars, per-question evidence, and a plain explanation of how the score was built. Older technical / communication / cultural-fit rows still render.
- **UX and accessibility.** Cold-start copy, device check, spoken questions, visible listening state, copy-link buttons, visible focus, labelled inputs, and `prefers-reduced-motion`.
- **Postgres-ready persistence.** `DATABASE_URL` works with Render's `postgres://` URLs. The old sample database and session files are not shipped.

## Acknowledgements

Originally based on kodegod/ai-recruiter.
