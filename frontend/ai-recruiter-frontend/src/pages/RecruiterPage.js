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
import ColdStart from "../components/ColdStart";
import CopyButton from "../components/CopyButton";

const STATUSES = [
  { value: "", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "ready", label: "Ready" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
];

const FALLBACK_EVALUATION = [
  { id: "problem_solving", label: "Problem solving", description: "Structures an unfamiliar problem and checks the result." },
  { id: "communication", label: "Communication", description: "Is clear, sequenced, and concrete." },
  { id: "role_knowledge", label: "Role knowledge", description: "Shows real skill in the work the job description describes." },
  { id: "ownership", label: "Ownership and impact", description: "Separates what they did from what the team did, and names a result." },
  { id: "collaboration", label: "Collaboration", description: "Works with other people and handles disagreement." },
];

export default function RecruiterPage() {
  const [access, setAccess] = useState({ auth_required: false });
  const [token, setToken] = useState(getRecruiterToken());
  const [passcode, setPasscode] = useState("");
  const [authError, setAuthError] = useState("");
  const [setupMessage, setSetupMessage] = useState("");
  const [signingIn, setSigningIn] = useState(false);

  const [jdText, setJdText] = useState("");
  const [resumeText, setResumeText] = useState("");
  const [interviewId, setInterviewId] = useState("");
  const [evaluation, setEvaluation] = useState([]);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [interviews, setInterviews] = useState([]);
  const [listReady, setListReady] = useState(false);
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
      setInterviews(Array.isArray(response.data) ? response.data : []);
      setListReady(true);
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
    if (signedIn) loadInterviews();
  }, [signedIn, loadInterviews]);

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

  async function createInterview(event) {
    event.preventDefault();
    if (!jdText.trim() || !resumeText.trim()) {
      setFormError("A job description and a resume are both required.");
      return;
    }
    setBusy(true);
    setFormError("");
    setReady(false);
    try {
      const headers = authHeaders();
      const form = new URLSearchParams();
      form.append("jd_text", jdText.trim());
      form.append("resume_text", resumeText.trim());
      const created = await axios.post(`${API_URL}/interview/create`, form, {
        headers: { ...headers, "Content-Type": "application/x-www-form-urlencoded" },
        timeout: 120000,
      });
      setInterviewId(created.data.interview_id);
      setEvaluation(created.data.evaluation?.length ? created.data.evaluation : FALLBACK_EVALUATION);
      setReady(true);
      loadInterviews();
    } catch (error) {
      setFormError(friendlyError(error, "The interview could not be created."));
    } finally {
      setBusy(false);
    }
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
  const dimensions = evaluation.length ? evaluation : FALLBACK_EVALUATION;

  const canCreate = Boolean(jdText.trim() && resumeText.trim());

  return (
    <div className="page">
      <ColdStart active={busy} />
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
      <p className="lede">Create an interview from a job description and a resume, then send the link.</p>

      {formError ? <div className="alert alert-error">{formError}</div> : null}
      {setupMessage ? <div className="alert alert-setup">{setupMessage}</div> : null}

      <form className="card" onSubmit={createInterview}>
        <h2>New interview</h2>
        <label htmlFor="jd-text">Job description</label>
        <textarea
          id="jd-text"
          value={jdText}
          onChange={(event) => setJdText(event.target.value)}
          placeholder="Paste the job description"
          disabled={busy}
        />
        <label htmlFor="resume-text">Resume</label>
        <textarea
          id="resume-text"
          value={resumeText}
          onChange={(event) => setResumeText(event.target.value)}
          placeholder="Paste the resume"
          disabled={busy}
        />
        <button className="btn btn-primary" type="submit" disabled={busy || !canCreate}>
          {busy ? "Working…" : "Create interview"}
        </button>
      </form>

      {ready && interviewId && (
        <section className="card ready-card">
          <h2>Interview is ready. Questions are ready.</h2>
          <p>The candidate will be evaluated on:</p>
          <ul className="dimension-list">
            {dimensions.map((item) => (
              <li key={item.id || item.label}>
                <strong>{item.label}</strong>
                <span>{item.description}</span>
              </li>
            ))}
          </ul>
          <h3>Send this link to the candidate</h3>
          <p className="interview-link-label">Interview link</p>
          <div className="id-row">
            <code>{shareLink}</code>
            <CopyButton text={shareLink} label="Copy link" />
          </div>
        </section>
      )}

      <section className="card">
        <h2>View candidate reports</h2>
        <div className="split">
          <div>
            <label htmlFor="interview-search">Search</label>
            <input
              id="interview-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Name, role, or link"
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
        {listReady && interviews.length === 0 ? <p className="empty-state">No reports match this view yet.</p> : null}
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
                    {interview.status === "completed" && score ? ` · ${score}/10` : ""}
                  </p>
                </div>
                <div className="controls">
                  <Link className="btn btn-secondary" to={`/recruiter/interviews/${interview.interview_id}`}>
                    View candidate report
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
