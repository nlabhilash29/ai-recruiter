import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import {
  API_URL,
  authHeaders,
  candidateLink,
  formatScore,
  friendlyError,
  getRecruiterToken,
  setRecruiterToken,
} from "../api";
import CopyButton from "../components/CopyButton";
import QuestionEditor from "../components/QuestionEditor";
import { QUESTION_COUNTS, ROLE_OPTIONS } from "../roles";

const STATUSES = [
  { value: "", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "ready", label: "Ready" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
];

export default function RecruiterPage() {
  const [access, setAccess] = useState(null);
  const [token, setToken] = useState(getRecruiterToken());
  const [passcode, setPasscode] = useState("");
  const [authError, setAuthError] = useState("");
  const [setupMessage, setSetupMessage] = useState("");
  const [signingIn, setSigningIn] = useState(false);

  const [jdFile, setJdFile] = useState(null);
  const [resumeFile, setResumeFile] = useState(null);
  const [mode, setMode] = useState("dynamic");
  const [count, setCount] = useState(5);
  const [roleFamily, setRoleFamily] = useState("");
  const [questions, setQuestions] = useState([]);
  const [interviewId, setInterviewId] = useState("");
  const [ready, setReady] = useState(false);
  const [newQuestion, setNewQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [formError, setFormError] = useState("");

  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [interviews, setInterviews] = useState([]);
  const [listError, setListError] = useState("");

  const authRequired = Boolean(access?.auth_required);
  const signedIn = !authRequired || Boolean(token);

  useEffect(() => {
    let cancelled = false;
    axios
      .get(`${API_URL}/recruiter/access`, { timeout: 90000 })
      .then((response) => {
        if (!cancelled) setAccess(response.data);
      })
      .catch(() => {
        if (!cancelled) setAccess({ auth_required: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadInterviews = useCallback(async () => {
    try {
      const response = await axios.get(`${API_URL}/interview/search`, {
        headers: authHeaders(),
        params: { q: query || undefined, status: status || undefined },
        timeout: 90000,
      });
      setInterviews(response.data || []);
      setListError("");
      setSetupMessage("");
    } catch (error) {
      if (error.response?.status === 401) {
        setRecruiterToken("");
        setToken("");
        setAccess({ auth_required: true });
        setAuthError("Please sign in again to continue.");
        return;
      }
      const message = friendlyError(error, "The interview list could not be loaded.");
      if (error.response?.status === 503) setSetupMessage(message);
      else setListError(message);
    }
  }, [query, status]);

  useEffect(() => {
    if (signedIn && access) loadInterviews();
  }, [signedIn, access, loadInterviews]);

  async function signIn(event) {
    event.preventDefault();
    setSigningIn(true);
    setAuthError("");
    setSetupMessage("");
    try {
      const response = await axios.post(`${API_URL}/recruiter/login`, { passcode }, { timeout: 90000 });
      setRecruiterToken(response.data.token);
      setToken(response.data.token);
      setPasscode("");
    } catch (error) {
      const message = friendlyError(error, "Sign-in failed. Please try again.");
      if (error.response?.status === 503) setSetupMessage(message);
      else setAuthError(message);
    } finally {
      setSigningIn(false);
    }
  }

  function signOut() {
    setRecruiterToken("");
    setToken("");
    setInterviews([]);
  }

  function onFile(event, setter) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setFormError("That file is too large. Please keep it under 5 MB.");
      event.target.value = "";
      return;
    }
    setter(file);
    setFormError("");
  }

  async function createInterview(event) {
    event.preventDefault();
    if (!jdFile || !resumeFile) {
      setFormError("Choose both a job description and a resume.");
      return;
    }
    setBusy(true);
    setFormError("");
    setNotice("");
    setReady(false);
    setQuestions([]);
    try {
      const headers = authHeaders();
      const jdData = new FormData();
      jdData.append("file", jdFile);
      const resumeData = new FormData();
      resumeData.append("file", resumeFile);
      const jdResponse = await axios.post(`${API_URL}/upload/jd`, jdData, { headers, timeout: 120000 });
      const resumeResponse = await axios.post(`${API_URL}/upload/resume`, resumeData, { headers, timeout: 120000 });
      const form = new URLSearchParams();
      form.append("jd_id", jdResponse.data.jd_id);
      form.append("resume_id", resumeResponse.data.resume_id);
      form.append("question_mode", mode);
      form.append("main_question_target", String(count));
      if (roleFamily) form.append("role_family", roleFamily);
      const created = await axios.post(`${API_URL}/interview/create`, form, {
        headers: { ...headers, "Content-Type": "application/x-www-form-urlencoded" },
        timeout: 120000,
      });
      setInterviewId(created.data.interview_id);
      if (created.data.question_mode === "preset") {
        setQuestions(created.data.questions || []);
        setNotice("Draft questions are ready. Edit them, then create the candidate link.");
      } else {
        setReady(true);
        setNotice("Interview ready. Send the candidate the link. Questions are written as the conversation goes.");
      }
      loadInterviews();
    } catch (error) {
      setFormError(friendlyError(error, "The interview could not be created."));
    } finally {
      setBusy(false);
    }
  }

  async function saveQuestionText() {
    const headers = authHeaders();
    await Promise.all(
      questions.map((question) =>
        axios.put(
          `${API_URL}/interview/questions/${question.id}`,
          { question_text: question.question_text },
          { headers, timeout: 60000 }
        )
      )
    );
  }

  async function confirmQuestions() {
    setBusy(true);
    setFormError("");
    try {
      await saveQuestionText();
      await axios.post(`${API_URL}/interview/${interviewId}/confirm`, undefined, {
        headers: authHeaders(),
        timeout: 60000,
      });
      setReady(true);
      setNotice("Interview ready. Copy the link and send it to the candidate.");
      loadInterviews();
    } catch (error) {
      setFormError(friendlyError(error, "The questions could not be confirmed."));
    } finally {
      setBusy(false);
    }
  }

  async function addQuestion(event) {
    event.preventDefault();
    const text = newQuestion.trim();
    if (text.length < 8) {
      setFormError("Write a full question before adding it.");
      return;
    }
    setBusy(true);
    setFormError("");
    try {
      const form = new URLSearchParams();
      form.append("question_text", text);
      const response = await axios.post(`${API_URL}/interview/${interviewId}/questions`, form, {
        headers: { ...authHeaders(), "Content-Type": "application/x-www-form-urlencoded" },
        timeout: 60000,
      });
      setQuestions((current) => [...current, response.data]);
      setNewQuestion("");
    } catch (error) {
      setFormError(friendlyError(error, "The question could not be added."));
    } finally {
      setBusy(false);
    }
  }

  async function removeQuestion(question) {
    setBusy(true);
    setFormError("");
    try {
      await axios.delete(`${API_URL}/interview/questions/${question.id}`, {
        headers: authHeaders(),
        timeout: 60000,
      });
      setQuestions((current) => current.filter((item) => item.id !== question.id));
    } catch (error) {
      setFormError(friendlyError(error, "The question could not be removed."));
    } finally {
      setBusy(false);
    }
  }

  if (!access) {
    return (
      <div className="page narrow">
        <p className="card">Opening the recruiter desk…</p>
      </div>
    );
  }

  if (!signedIn) {
    return (
      <div className="page narrow">
        <p className="eyebrow">Recruiter</p>
        <h1>Recruiter sign in</h1>
        <p className="lede">
          This passcode is shared by the hiring team. Candidates with an interview link never see this page.
        </p>
        {setupMessage ? <div className="alert alert-setup">{setupMessage}</div> : null}
        {authError ? <div className="alert alert-error">{authError}</div> : null}
        <form className="card" onSubmit={signIn}>
          <label htmlFor="passcode">Passcode</label>
          <input
            id="passcode"
            type="password"
            autoComplete="current-password"
            value={passcode}
            onChange={(event) => setPasscode(event.target.value)}
            disabled={signingIn || Boolean(setupMessage)}
          />
          <button className="btn btn-primary" type="submit" disabled={signingIn || !passcode.trim() || Boolean(setupMessage)}>
            {signingIn ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    );
  }

  const shareLink = interviewId ? candidateLink(interviewId) : "";

  return (
    <div className="page">
      <div className="interview-top">
        <div>
          <p className="eyebrow">Recruiter</p>
          <h1>Interviews</h1>
        </div>
        {authRequired ? (
          <button type="button" className="btn btn-ghost" onClick={signOut}>
            Sign out
          </button>
        ) : null}
      </div>
      <p className="lede">Create an interview and send the candidate a link. You review the results here.</p>

      {formError ? <div className="alert alert-error">{formError}</div> : null}
      {notice ? <div className="alert alert-success">{notice}</div> : null}
      {setupMessage ? <div className="alert alert-setup">{setupMessage}</div> : null}

      <form className="card" onSubmit={createInterview}>
        <h2>New interview</h2>
        <div className="split">
          <div>
            <label htmlFor="jd-file">Job description</label>
            <input id="jd-file" type="file" accept=".pdf,.docx,.txt" onChange={(event) => onFile(event, setJdFile)} disabled={busy} />
          </div>
          <div>
            <label htmlFor="resume-file">Resume</label>
            <input id="resume-file" type="file" accept=".pdf,.docx,.txt" onChange={(event) => onFile(event, setResumeFile)} disabled={busy} />
          </div>
        </div>
        <div className="split">
          <div>
            <label htmlFor="role-family">Role family</label>
            <select id="role-family" value={roleFamily} onChange={(event) => setRoleFamily(event.target.value)} disabled={busy}>
              {ROLE_OPTIONS.map((option) => (
                <option key={option.value || "infer"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="question-count">Main questions</label>
            <select id="question-count" value={count} onChange={(event) => setCount(Number(event.target.value))} disabled={busy}>
              {QUESTION_COUNTS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </div>
        </div>
        <fieldset className="choice-set">
          <legend>Questions</legend>
          <label className="choice" htmlFor="mode-dynamic">
            <input
              id="mode-dynamic"
              type="radio"
              name="question-mode"
              value="dynamic"
              checked={mode === "dynamic"}
              onChange={() => setMode("dynamic")}
              disabled={busy}
            />
            <span>AI-generated questions</span>
          </label>
          <p className="muted">
            Default. Questions are written during the interview from the job description, the resume, and earlier
            answers. A thin or interesting answer can get one follow-up.
          </p>
          <label className="choice" htmlFor="mode-preset">
            <input
              id="mode-preset"
              type="radio"
              name="question-mode"
              value="preset"
              checked={mode === "preset"}
              onChange={() => setMode("preset")}
              disabled={busy}
            />
            <span>Preset questions</span>
          </label>
          <p className="muted">Draft a fixed list with AI, then edit it before the link goes out.</p>
        </fieldset>
        <button className="btn btn-primary" type="submit" disabled={busy || !jdFile || !resumeFile}>
          {busy ? "Working…" : mode === "preset" ? "Draft questions with AI" : "Create interview"}
        </button>
      </form>

      {questions.length > 0 && !ready && (
        <section className="card">
          <h2>Preset questions</h2>
          <QuestionEditor
            questions={questions}
            disabled={busy}
            onChange={(questionId, questionText) =>
              setQuestions((current) =>
                current.map((item) => (item.id === questionId ? { ...item, question_text: questionText } : item))
              )
            }
            onRemove={removeQuestion}
          />
          <form onSubmit={addQuestion}>
            <label htmlFor="new-question">Add a question</label>
            <textarea
              id="new-question"
              value={newQuestion}
              onChange={(event) => setNewQuestion(event.target.value)}
              disabled={busy || questions.length >= 8}
            />
            <button className="btn btn-ghost" type="submit" disabled={busy || questions.length >= 8}>
              Add question
            </button>
          </form>
          <button type="button" className="btn btn-primary" onClick={confirmQuestions} disabled={busy}>
            Save questions and create link
          </button>
        </section>
      )}

      {ready && interviewId && (
        <section className="card ready-card">
          <h2>Candidate link</h2>
          <p>Send this link to the candidate. The interview opens on their side.</p>
          <div className="id-row">
            <code>{interviewId}</code>
            <CopyButton text={interviewId} label="Copy ID" />
          </div>
          <div className="id-row">
            <code>{shareLink}</code>
            <CopyButton text={shareLink} label="Copy link" />
          </div>
        </section>
      )}

      <section className="card">
        <h2>All interviews</h2>
        <div className="split">
          <div>
            <label htmlFor="interview-search">Search</label>
            <input
              id="interview-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Name, role, or ID"
            />
          </div>
          <div>
            <label htmlFor="status-filter">Status</label>
            <select id="status-filter" value={status} onChange={(event) => setStatus(event.target.value)}>
              {STATUSES.map((item) => (
                <option key={item.value || "all"} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        {listError ? <div className="alert alert-error">{listError}</div> : null}
        {interviews.length === 0 ? <p className="empty-state">No interviews match this view yet.</p> : null}
        <ul className="interview-list">
          {interviews.map((interview) => {
            const score = formatScore(interview.overall_score);
            return (
              <li key={interview.interview_id}>
                <div>
                  <strong>{interview.candidate_name || "Candidate"}</strong>
                  <p>
                    {interview.job_title || "Role"}
                    {interview.company ? ` · ${interview.company}` : ""}
                  </p>
                  <p className="muted">
                    <span className={`pill pill-${interview.status}`}>{interview.status}</span>
                    {interview.question_mode === "dynamic" ? " · AI questions" : " · Preset questions"}
                    {interview.status === "completed" && score ? ` · ${score}/10` : ""}
                  </p>
                </div>
                <div className="controls">
                  <Link className="btn btn-secondary" to={`/recruiter/interviews/${interview.interview_id}`}>
                    View results
                  </Link>
                  <CopyButton text={candidateLink(interview.interview_id)} label="Copy link" />
                </div>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
