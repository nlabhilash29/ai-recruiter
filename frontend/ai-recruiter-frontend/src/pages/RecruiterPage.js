import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import axios from "axios";
import { API_URL, authHeaders, candidateLink, formatScore, friendlyError, getRecruiterToken, setRecruiterToken } from "../api";
import CopyButton from "../components/CopyButton";

const STATUSES = [
  { value: "", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "ready", label: "Ready" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
];

export default function RecruiterPage() {
  const navigate = useNavigate();
  const [token, setToken] = useState(getRecruiterToken());
  const [passcode, setPasscode] = useState("");
  const [authError, setAuthError] = useState("");
  const [setupMessage, setSetupMessage] = useState("");
  const [signingIn, setSigningIn] = useState(false);

  const [jdFile, setJdFile] = useState(null);
  const [resumeFile, setResumeFile] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [interviewId, setInterviewId] = useState("");
  const [editing, setEditing] = useState({});
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [formError, setFormError] = useState("");

  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [interviews, setInterviews] = useState([]);
  const [listError, setListError] = useState("");

  const loadInterviews = useCallback(async (activeToken) => {
    if (!activeToken) return;
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
        setAuthError("Please sign in again to continue.");
        return;
      }
      const message = friendlyError(error, "The interview list could not be loaded.");
      if (error.response?.status === 503) setSetupMessage(message);
      else setListError(message);
    }
  }, [query, status]);

  useEffect(() => {
    if (token) loadInterviews(token);
  }, [token, loadInterviews]);

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
    setConfirmed(false);
    try {
      const jdData = new FormData();
      jdData.append("file", jdFile);
      const resumeData = new FormData();
      resumeData.append("file", resumeFile);
      const headers = authHeaders();
      const jdResponse = await axios.post(`${API_URL}/upload/jd`, jdData, { headers, timeout: 120000 });
      const resumeResponse = await axios.post(`${API_URL}/upload/resume`, resumeData, { headers, timeout: 120000 });
      const form = new URLSearchParams();
      form.append("jd_id", jdResponse.data.jd_id);
      form.append("resume_id", resumeResponse.data.resume_id);
      const created = await axios.post(`${API_URL}/interview/create`, form, {
        headers: { ...headers, "Content-Type": "application/x-www-form-urlencoded" },
        timeout: 120000,
      });
      setInterviewId(created.data.interview_id);
      setQuestions(created.data.questions || []);
      setNotice("Questions are ready. Edit them if you want, then confirm.");
    } catch (error) {
      setFormError(friendlyError(error, "The interview could not be created."));
    } finally {
      setBusy(false);
    }
  }

  async function saveQuestion(questionId) {
    const question = questions.find((item) => item.id === questionId);
    await axios.put(
      `${API_URL}/interview/questions/${questionId}`,
      { question_text: question.question_text },
      { headers: authHeaders(), timeout: 60000 }
    );
    setEditing((current) => ({ ...current, [questionId]: false }));
  }

  async function confirmQuestions() {
    setBusy(true);
    setFormError("");
    try {
      const dirty = Object.keys(editing).filter((questionId) => editing[questionId]);
      for (const questionId of dirty) {
        await saveQuestion(questionId);
      }
      await axios.post(`${API_URL}/interview/${interviewId}/confirm`, undefined, {
        headers: authHeaders(),
        timeout: 60000,
      });
      setConfirmed(true);
      setNotice("Interview ready. Send the candidate the link, or open it yourself.");
      loadInterviews(token);
    } catch (error) {
      setFormError(friendlyError(error, "The questions could not be confirmed."));
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
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
        <button type="button" className="btn btn-ghost" onClick={signOut}>
          Sign out
        </button>
      </div>

      {formError ? <div className="alert alert-error">{formError}</div> : null}
      {notice ? <div className="alert alert-success">{notice}</div> : null}

      <form className="card" onSubmit={createInterview}>
        <h2>New interview</h2>
        <div className="split">
          <div>
            <label htmlFor="jd-file">Job description</label>
            <input id="jd-file" type="file" accept=".pdf,.doc,.docx,.txt" onChange={(event) => onFile(event, setJdFile)} disabled={busy} />
          </div>
          <div>
            <label htmlFor="resume-file">Resume</label>
            <input id="resume-file" type="file" accept=".pdf,.doc,.docx,.txt" onChange={(event) => onFile(event, setResumeFile)} disabled={busy} />
          </div>
        </div>
        <button className="btn btn-primary" type="submit" disabled={busy || !jdFile || !resumeFile}>
          {busy ? "Working…" : "Generate questions"}
        </button>
      </form>

      {questions.length > 0 && !confirmed && (
        <section className="card">
          <h2>Questions</h2>
          {questions.map((question, index) => {
            const fieldId = `question-${question.id}`;
            return (
              <div className="editor" key={question.id}>
                <div className="editor-head">
                  <label htmlFor={fieldId}>Question {index + 1}</label>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => (editing[question.id] ? saveQuestion(question.id) : setEditing((current) => ({ ...current, [question.id]: true })))}
                  >
                    {editing[question.id] ? "Save" : "Edit"}
                  </button>
                </div>
                <textarea
                  id={fieldId}
                  value={question.question_text}
                  disabled={!editing[question.id]}
                  onChange={(event) =>
                    setQuestions((current) =>
                      current.map((item) => (item.id === question.id ? { ...item, question_text: event.target.value } : item))
                    )
                  }
                />
              </div>
            );
          })}
          <button type="button" className="btn btn-primary" onClick={confirmQuestions} disabled={busy}>
            Use these questions
          </button>
        </section>
      )}

      {confirmed && interviewId && (
        <section className="card ready-card">
          <h2>Interview ready</h2>
          <p>Send this link to the candidate. They will not see the recruiter list or other reports.</p>
          <div className="id-row">
            <code>{interviewId}</code>
            <CopyButton text={interviewId} label="Copy ID" />
          </div>
          <div className="id-row">
            <code>{shareLink}</code>
            <CopyButton text={shareLink} label="Copy link" />
          </div>
          <button type="button" className="btn btn-primary" onClick={() => navigate(`/interview/${interviewId}`)}>
            Start interview
          </button>
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
                    {interview.status === "completed" && score ? ` ${score}/10` : ""}
                  </p>
                </div>
                <div className="controls">
                  <Link className="btn btn-secondary" to={`/recruiter/interviews/${interview.interview_id}`}>
                    View report
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
