import { useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API_URL, friendlyError } from "../api";

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
  const [jobRole, setJobRole] = useState("");
  const [jdText, setJdText] = useState("");
  const [resumeText, setResumeText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function openExisting(event) {
    event.preventDefault();
    const interviewId = interviewIdFromInput(existingId);
    if (!interviewId) {
      setError("Paste an interview link to open it.");
      return;
    }
    navigate(`/interview/${interviewId}`);
  }

  async function createPractice(event) {
    event.preventDefault();
    if (!jobRole.trim() && !jdText.trim()) {
      setError("Enter a role or a job description.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const form = new URLSearchParams();
      form.append("job_role", jobRole.trim());
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

  return (
    <div className="page">
      <p className="eyebrow">Interview</p>
      <h1>Interview</h1>
      <p className="lede">
        Most people open the link a recruiter sent. If you are here without one, start from the link or try a short practice.
      </p>
      {error ? <div className="alert alert-error">{error}</div> : null}
      <div className="choice-grid">
        <section className="card choice-card">
          <h2>I have an interview link</h2>
          <p>Paste the link or code your recruiter sent and go straight in.</p>
          <form onSubmit={openExisting}>
            <label htmlFor="existing-id">Interview link</label>
            <input
              id="existing-id"
              value={existingId}
              onChange={(event) => setExistingId(event.target.value)}
              placeholder="Paste the interview link"
            />
            <button className="btn btn-primary" type="submit" disabled={!existingId.trim()}>
              Open interview
            </button>
          </form>
        </section>
        <section className="card choice-card" id="practice">
          <h2>Practice first</h2>
          <p>Try a 5-question sample interview to get comfortable. It isn't shared with anyone.</p>
          <form onSubmit={createPractice}>
            <label htmlFor="job-role">Role</label>
            <input
              id="job-role"
              value={jobRole}
              onChange={(event) => setJobRole(event.target.value)}
              placeholder="Backend engineer"
              disabled={loading}
            />
            <label htmlFor="practice-jd">Job description (optional)</label>
            <textarea
              id="practice-jd"
              value={jdText}
              onChange={(event) => setJdText(event.target.value)}
              placeholder="Paste a job description if you have one"
              disabled={loading}
            />
            <label htmlFor="practice-resume">Resume (optional)</label>
            <textarea
              id="practice-resume"
              value={resumeText}
              onChange={(event) => setResumeText(event.target.value)}
              placeholder="Paste a resume if you have one"
              disabled={loading}
            />
            <button className="btn btn-secondary" type="submit" disabled={loading || (!jobRole.trim() && !jdText.trim())}>
              {loading ? "Creating your interview…" : "Start practice"}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
