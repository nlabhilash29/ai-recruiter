import { useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API_URL, friendlyError } from "../api";

export default function HomePage() {
  const navigate = useNavigate();
  const [jobRole, setJobRole] = useState("");
  const [existingId, setExistingId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function createPractice(event) {
    event.preventDefault();
    const role = jobRole.trim();
    if (!role) {
      setError("Please enter a job role.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const form = new URLSearchParams();
      form.append("job_role", role);
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

  function openExisting(event) {
    event.preventDefault();
    const id = existingId.trim();
    if (!id) {
      setError("Enter an interview ID to open it.");
      return;
    }
    navigate(`/interview/${id}`);
  }

  return (
    <div className="page narrow">
      <p className="eyebrow">Practice</p>
      <h1>Practice interview</h1>
      <p className="lede">
        Choose a role and you will get five spoken questions. Only your audio is recorded and
        transcribed. When you finish, the feedback is on this device.
      </p>
      {error ? <div className="alert alert-error">{error}</div> : null}
      <form className="card" onSubmit={createPractice}>
        <label htmlFor="job-role">Job role</label>
        <input
          id="job-role"
          value={jobRole}
          onChange={(event) => setJobRole(event.target.value)}
          placeholder="Backend engineer"
          disabled={loading}
        />
        <button className="btn btn-primary" type="submit" disabled={loading || !jobRole.trim()}>
          {loading ? "Creating your interview…" : "Create practice interview"}
        </button>
      </form>
      <form className="card" onSubmit={openExisting}>
        <label htmlFor="existing-id">Have an interview ID?</label>
        <input
          id="existing-id"
          value={existingId}
          onChange={(event) => setExistingId(event.target.value)}
          placeholder="Paste the interview ID"
        />
        <button className="btn btn-secondary" type="submit" disabled={!existingId.trim()}>
          Open interview
        </button>
      </form>
    </div>
  );
}
