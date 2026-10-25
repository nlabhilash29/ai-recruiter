# [AI Recruiter](https://ai-recruiter-tau.vercel.app/)

Live Link - https://ai-recruiter-tau.vercel.app/

[AI Recruiter](https://ai-recruiter-tau.vercel.app/) is an intelligent platform that streamlines and enhances the hiring process by leveraging AI technologies to conduct mock interviews, create customized interviews for recruiters, and facilitate real-time video interviews with automated scoring and feedback.

## Overview

AI Recruiter has two main components:

- **Frontend:** Built using React and Three.js, the frontend provides an interactive and visually engaging user interface.
- **Backend:** Powered by FastAPI, the backend handles data processing, interview session management, AI-driven question generation, audio transcription, and feedback analysis.

## Features

### Frontend Features

- **Mock Interview:**

    - Allows candidates to quickly prepare for interviews by entering a job role.
    - Automatically generates interview questions for the specified role.

- **Recruiter Dashboard:**

    - Uploading a Job Description (JD) file.
    - Uploading a candidate's resume.
    - Adding custom interview questions.
    - Automatically generates questions based on the JD and resume.

- **Video Interview:**

    - Enables real-time interviews where candidates respond to AI-generated questions.
    - Automatically transcribes and analyzes audio responses.
    - Provides scores and feedback for:
        - Technical Proficiency
        - Communication Skills
        - Cultural Fit

### Backend Features

- **Job Description Management:**

Upload and process JDs to extract role-specific details like title, company, and requirements.

- **Resume Management:**

Upload and process resumes to extract candidate information, skills, and experience.

- **Interview Session Management:**

    - Combine JD and resume to create interview sessions.
    - Generate AI-powered questions tailored to the JD and resume.
    - Edit, update, and confirm questions before starting the interview.

- **Mock Interview Generation:**

Dynamically generate a JD and interview questions for candidates without requiring any uploads.

- **Audio Transcription:**

Converts candidate audio responses into text using OpenAI Whisper API.

- **AI Feedback and Scoring:**

    - Analyzes transcriptions to provide scores and feedback on:
    - Relevance to the question.
    - Clarity of response.
    - Technical accuracy.
    - Generates improvement suggestions and highlights strengths.

- **Text-to-Speech:**

Responds to candidates with audio feedback using ElevenLabs API.


## Technology Stack

### Frontend

- **React:** Component-based architecture for building the user interface.
- **Three.js:** 3D animations and visual effects for the landing animation and background.
- **CSS:** Styling for components and layouts.

### Backend
- **FastAPI:** Framework for building the RESTful API.
- **SQLAlchemy:** ORM for SQLite and Postgres.
- **OpenAI Whisper API:** Audio-to-text transcription.
- **Groq `openai/gpt-oss-120b`:** Question generation and answer scoring. Responses are requested as JSON, with a labelled-text parser and a fallback when feedback would otherwise be empty.
- **ElevenLabs API:** Text-to-speech for question playback.

### Database
- **SQLite** locally when `DATABASE_URL` is unset (`sqlite:///./test.db`).
- **Postgres** when `DATABASE_URL` is set. Render's `postgres://` URLs are rewritten to `postgresql+psycopg2://`.
- The app creates tables on startup and does not load sample interviews.

## Routes

- `/` practice interview for a candidate working on their own.
- `/interview/:id` candidate interview. The page does not link to the recruiter area or to other reports.
- `/interview/:id/results` feedback for a practice interview. A real interview report returns a sign-in error here.
- `/recruiter` recruiter sign-in, interview list, and new-interview flow.
- `/recruiter/interviews/:id` full report.

`frontend/ai-recruiter-frontend/vercel.json` rewrites those paths to `index.html` so a refresh on Vercel still loads the app.

## Recruiter access

Set `RECRUITER_PASSCODE` on the backend. `POST /recruiter/login` checks it and returns an HMAC token that the browser stores in `localStorage` for 12 hours. Upload, question editing, the interview list, and report endpoints require that token.

If `RECRUITER_PASSCODE` is unset, those endpoints respond with HTTP 503 and the message `Recruiter access is not configured. Set RECRUITER_PASSCODE on the server.` They are not left open. Practice interviews and candidate interview links keep working.

Only audio is uploaded from the interview page. The camera preview is for framing and is not sent to the API.

## Setup and Installation

### Prerequisites

1. Node.js and npm (frontend).
2. Python 3.11 (backend; 3.11.9 on Render).
3. Environment variables listed in `backend/.env.example` and `frontend/ai-recruiter-frontend/.env.example`.

### Frontend

```
git clone https://github.com/nlabhilash29/ai-recruiter.git
cd frontend/ai-recruiter-frontend
npm ci
```

Create `.env.local`:

```
REACT_APP_API_URL=http://localhost:8000
```

`REACT_APP_API_URL` is read at build time. On Vercel, set it to the Render URL (`https://ai-recruiter-x7qm.onrender.com`) and redeploy after changing it.

```
npm start
```

The app is at http://localhost:3000.

### Backend

From `backend/`:

```
pip install -r requirements.txt
```

Create `.env` from `.env.example`. The API still starts if `OPENAI_API_KEY`, `GROQ_API_KEY`, or `ELEVENLABS_API_KEY` is missing. A route that needs a missing key returns HTTP 503 and names the variable. Set `RECRUITER_PASSCODE` before using the recruiter pages. Questions and scoring use Groq `openai/gpt-oss-120b` (`GROQ_MODEL` overrides it). `GROQ_REASONING_EFFORT` defaults to `low`. Transcription uses OpenAI Whisper and sends the recording in its real format. Speech uses ElevenLabs `eleven_flash_v2_5` (`ELEVENLABS_MODEL_ID` and `ELEVENLABS_VOICE_ID` override the voice). Do not set `llama3-70b-8192` or `eleven_monolingual_v1`; those model ids were removed.

```
uvicorn main:app --host 0.0.0.0 --port 8000
```

Render start command, with root directory `backend/`:

```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Set `DATABASE_URL` on Render to the Postgres connection string so interviews survive restarts. SQLite on Render's filesystem does not persist.

`AI_STUB=1` runs the API without calling Groq, Whisper, or ElevenLabs. Useful for local smoke tests.

### Tests

From `backend/`:

```
python -m unittest discover tests
```






