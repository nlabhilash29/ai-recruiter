import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API_URL, friendlyError } from "../api";
import ColdStart from "../components/ColdStart";

function interviewIdFromInput(value) {
  const text = (value || "").trim();
  const match = text.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
  if (match) return match[0];
  const parts = text.split("/").filter(Boolean);
  return parts[parts.length - 1] || "";
}

export default function HomePage() {
  const navigate = useNavigate();
  const [existingId, setExistingId] = useState("");
  const [jdText, setJdText] = useState("");
  const [resumeText, setResumeText] = useState("");
  const [practiceOpen, setPracticeOpen] = useState(() => window.location.hash === "#practice");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    function onHash() {
      if (window.location.hash === "#practice") setPracticeOpen(true);
    }
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function openExisting(event) {
    event.preventDefault();
    const interviewId = interviewIdFromInput(existingId);
    if (!interviewId) {
      setError("Paste an interview link to open it.");
      return;
    }
    navigate(`/interview/${interviewId}`);
  }

  function revealPractice(event) {
    event.preventDefault();
    setPracticeOpen(true);
    if (window.location.hash !== "#practice") {
      window.history.replaceState(null, "", `${window.location.pathname}#practice`);
    }
  }

  async function createPractice(event) {
    event.preventDefault();
    if (!jdText.trim() || !resumeText.trim()) {
      setError("A job description and a resume are both required.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const form = new URLSearchParams();
      form.append("jd_text", jdText.trim());
      form.append("resume_text", resumeText.trim());
      const response = await axios.post(`${API_URL}/mock-interview`, form, {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        timeout: 120000,
      });
      navigate(`/interview/${response.data.interview_id}`);
    } catch (requestError) {
      setError(friendlyError(requestError, "The practice interview could not be created. Please try again."));
      setLoading(false);
    }
  }

  const canPractice = Boolean(jdText.trim() && resumeText.trim());

  return (
    <div className="page narrow">
      <ColdStart active={loading} />
      <p className="eyebrow">Candidate</p>
      <h1>Take an interview or practice</h1>
      {error ? <div className="alert alert-error">{error}</div> : null}
      <section>
        <h2>Start an interview</h2>
        <form onSubmit={openExisting}>
          <label htmlFor="existing-id">Interview link</label>
          <input
            id="existing-id"
            value={existingId}
            onChange={(event) => setExistingId(event.target.value)}
            placeholder="Paste the interview link"
          />
          <button className="btn btn-primary" type="submit" disabled={!existingId.trim()}>
            Start
          </button>
        </form>
      </section>
      <p>
        <a className="plain-link" href="#practice" onClick={revealPractice}>
          Do you want to practice first? Click here.
        </a>
      </p>
      {practiceOpen ? (
        <form id="practice" onSubmit={createPractice}>
          <label htmlFor="practice-jd">Job description</label>
          <textarea
            id="practice-jd"
            value={jdText}
            onChange={(event) => setJdText(event.target.value)}
            placeholder="Paste the job description"
            disabled={loading}
          />
          <label htmlFor="practice-resume">Resume</label>
          <textarea
            id="practice-resume"
            value={resumeText}
            onChange={(event) => setResumeText(event.target.value)}
            placeholder="Paste the resume"
            disabled={loading}
          />
          <button className="btn btn-primary" type="submit" disabled={loading || !canPractice}>
            {loading ? "Creating your interview…" : "Start practice"}
          </button>
        </form>
      ) : null}
    </div>
  );
}
