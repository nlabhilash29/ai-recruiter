# AI Recruiter

AI video interviews by [Abhilash N L](https://github.com/nlabhilash29).

A candidate opens a link, checks the microphone and camera, and answers spoken questions out loud. The app transcribes the audio, scores each answer, and writes feedback. A recruiter signs in with a shared passcode, builds an interview from a job description and a resume, and reviews the report.

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

- Practice interview from a job title, or a shareable link at `/interview/:id`.
- Microphone and camera check before the first question. Only audio is recorded and transcribed. The camera is a framing preview and is not uploaded.
- The current question is on screen, with "Question X of N" and a replay control. A blocked autoplay is explained instead of failing silently.
- Record, then review the take and re-record or submit. A timer and recording dot auto-stop before the 5 MB upload limit.
- After submit, the page shows a processing state and keeps Start and Stop disabled until the next question arrives.

**Recruiter area**

- `/recruiter` is separate from the candidate link. Candidates do not see the dashboard or other people's reports.
- Sign-in uses a shared passcode (`RECRUITER_PASSCODE`). The browser keeps a short-lived token.
- Searchable interview list with a status filter, instead of pasting raw ids.
- Upload a job description and a resume, edit the generated questions, confirm them, and open the candidate link in one click.

**Results**

- Summary card with a recommendation, an overall score out of 10, and sub-scores.
- Per-question cards with the question, transcript, score, feedback, and what to improve.
- The per-question score is relevance. The overall score averages technical accuracy and communication, and the page says so.
- Empty feedback labels are hidden. A missing model reply is retried, then replaced with a short fallback so Feedback is never blank.

## Architecture

```
Browser (Vercel)
  /                         practice setup
  /interview/:id            candidate interview
  /interview/:id/results    practice feedback
  /recruiter                passcode, list, new interview
  /recruiter/interviews/:id recruiter report
        |
        |  HTTPS, REACT_APP_API_URL
        v
FastAPI (Render)
  /health, /mock-interview, /talk-video, /interview/:id/session
  /recruiter/login and the report/list/upload routes (token required)
        |
        +-- Whisper      audio -> transcript
        +-- Groq         questions and scores (JSON, then a text parser)
        +-- ElevenLabs   question audio
        +-- SQLite or Postgres
```

`frontend/ai-recruiter-frontend/vercel.json` rewrites client routes to `index.html`, so a refresh on `/interview/:id` or `/recruiter` still loads the app.

Recruiter routes check an HMAC token derived from `RECRUITER_PASSCODE` (12 hours, stored in `localStorage`). If that variable is unset, those routes return HTTP 503 and name the missing variable. They are not left open. Practice interviews and candidate links still work.

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
| `RECRUITER_PASSCODE` | Shared recruiter passcode. Required for the recruiter area |
| `DATABASE_URL` | Postgres URL. Omit it locally to use SQLite |
| `CORS_ORIGINS` | Extra browser origins, comma-separated |
| `AI_STUB` | Set to `1` to skip the AI providers locally |

Do not set `llama3-70b-8192` or `eleven_monolingual_v1`. Those model ids were removed by the providers.

**Frontend (Vercel)**

| Variable | Purpose |
| --- | --- |
| `REACT_APP_API_URL` | FastAPI origin, no trailing slash. Read at build time |

Locally this is `http://localhost:8000`. On Vercel it is the Render origin. Changing it requires a new Vercel deploy.

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
- **Candidate and recruiter separation.** Candidates use `/interview/:id`. Recruiters sign in at `/recruiter` and get a searchable list. Reports for real interviews stay behind the passcode.
- **Results redesign.** Summary card, score bar, per-question cards, and a plain explanation of the two score scales.
- **UX and accessibility.** Cold-start copy, device check, replay, re-record, processing state, recording timer, copy-link buttons, visible focus, labelled inputs, and `prefers-reduced-motion`.
- **Postgres-ready persistence.** `DATABASE_URL` works with Render's `postgres://` URLs. The old sample database and session files are not shipped.

## Acknowledgements

Originally based on kodegod/ai-recruiter.
