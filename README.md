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
- **SQLAlchemy:** ORM for database operations.
- **OpenAI Whisper API:** Audio-to-text transcription.
- **OpenAI GPT-like models:** AI-powered question generation and feedback.
- **ElevenLabs API:** Text-to-speech functionality for audio responses.

### Database
- **SQLite:** Used as the default database (can be swapped for PostgreSQL, MySQL, etc.).

## Usage

### Mock Interview

- Navigate to the Mock Interview tab in the app.
- Enter a job role and click Create Mock Interview.
- The backend generates a dynamic JD and interview questions for the role.

### Recruiter Dashboard
- Navigate to the Recruiter Dashboard tab.
- Upload:
        - Job Description file.
        - Candidate Resume file.
        - Customize or confirm AI-generated interview questions.
- A unique Interview ID is generated.

### Video Interview

- Navigate to the Video Interview tab.
- Enter the Interview ID generated from the Recruiter Dashboard or Mock Interview.
- Answer questions in real-time, and the backend:
- Transcribes audio.
- Scores and analyzes responses.
- Provides feedback.

## Setup and Installation

### Prerequisites

1. Node.js and npm (for the frontend).
2. Python 3.9+ (for the backend).
3. Environment variables. The API starts without them. Routes that call a provider return HTTP 503 naming the missing variable. Set `AI_STUB=1` only for a local demo that skips those providers.

| Variable | Where | Required for | Default |
| --- | --- | --- | --- |
| `REACT_APP_API_URL` | Frontend build (Vercel) | Browser calls to the API. Create React App inlines this at build time, so changing it requires a new deploy. | `http://localhost:8000` |
| `OPENAI_API_KEY` | Backend host | Whisper transcription (`whisper-1`) | none |
| `GROQ_API_KEY` | Backend host | Question generation, mock job descriptions, and scoring | none; built-in questions are used when it is missing |
| `GROQ_MODEL` | Backend host | Groq model id | `openai/gpt-oss-120b` |
| `GROQ_REASONING_EFFORT` | Backend host | Optional reasoning budget (`low`, `medium`, `high`, or empty to omit) | `low` |
| `ELEVENLABS_API_KEY` | Backend host | Spoken interviewer prompts | none |
| `ELEVENLABS_MODEL_ID` | Backend host | ElevenLabs model | `eleven_flash_v2_5` |
| `ELEVENLABS_VOICE_ID` | Backend host | ElevenLabs voice | `pNInz6obpgDQGcFmaJgB` |
| `DATABASE_URL` | Backend host | SQLAlchemy database URL | `sqlite:///./test.db` |
| `AI_STUB` | Backend host | Local demo mode. Set to `1` to skip Groq, OpenAI, and ElevenLabs. Do not enable this in production. | off |

`llama3-70b-8192` and `eleven_monolingual_v1` no longer exist at those providers. Do not set them.

### Frontend Setup

From `frontend/ai-recruiter-frontend`:

```
npm install
```

Optional `.env` (no spaces around `=`):

```
REACT_APP_API_URL=http://localhost:8000
```

```
npm start
```

The app is at http://localhost:3000. `npm test -- --watchAll=false` runs the UI test, and `npm run build` creates the production bundle.

### Backend Setup

From `backend`:

```
pip install -r requirements.txt
```

Create `backend/.env` with the provider keys you have. Then:

```
uvicorn main:app --reload
```

The API is at http://localhost:8000. `python -m pytest` runs the API tests. Those tests force `AI_STUB=1` and do not call the providers.

### Production

The Vercel project at https://ai-recruiter-tau.vercel.app/ is the static frontend only. Its built bundle calls `https://ai-recruiter-1dev.onrender.com`. That Render service is suspended by its owner (`x-render-routing: suspend-by-user`), so every API route returns HTTP 503 HTML and the browser reports a network/CORS error.

Vercel settings that matter:

- Root directory: `frontend/ai-recruiter-frontend`
- Build command: `npm run build`
- Output directory: `build`
- Environment variable: `REACT_APP_API_URL` set to the public backend origin, then redeploy. The value is baked into the JavaScript bundle.

The FastAPI app is not a Vercel function. Interview audio plus Whisper, Groq, and ElevenLabs exceeds typical serverless time and body-size limits, and SQLite on a serverless disk does not persist. Host the API on a long-running service (unsuspend or recreate the Render service, or another host) and put `OPENAI_API_KEY`, `GROQ_API_KEY`, `ELEVENLABS_API_KEY`, and `DATABASE_URL` in that host's environment, not in Vercel.






