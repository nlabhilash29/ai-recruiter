import { useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API_URL, friendlyError } from "../api";
import QuestionEditor from "../components/QuestionEditor";
import { QUESTION_COUNTS, ROLE_OPTIONS } from "../roles";

function interviewIdFromInput(value) {
  const text = (value || "").trim();
  const match = text.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
  if (match) return match[0];
  const parts = text.split("/").filter(Boolean);
  return parts[parts.length - 1] || "";
}

export default function HomePage() {
  const navigate = useNavigate();
  const [jobRole, setJobRole] = useState("");
  const [existingId, setExistingId] = useState("");
  const [mode, setMode] = useState("dynamic");
  const [count, setCount] = useState(5);
  const [roleFamily, setRoleFamily] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [draftId, setDraftId] = useState("");
  const [questions, setQuestions] = useState([]);
  const [newQuestion, setNewQuestion] = useState("");

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
      form.append("question_mode", mode);
      form.append("main_question_target", String(count));
      if (roleFamily) form.append("role_family", roleFamily);
      const response = await axios.post(`${API_URL}/mock-interview`, form, {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        timeout: 120000,
      });
      if (mode === "preset") {
        setDraftId(response.data.interview_id);
        setQuestions(response.data.questions || []);
        setLoading(false);
        return;
      }
      navigate(`/interview/${response.data.interview_id}`);
    } catch (requestError) {
      setError(friendlyError(requestError, "The practice interview could not be created. Please try again."));
      setLoading(false);
    }
  }

  function openExisting(event) {
    event.preventDefault();
    const interviewId = interviewIdFromInput(existingId);
    if (!interviewId) {
      setError("Enter an interview link or ID to open it.");
      return;
    }
    navigate(`/interview/${interviewId}`);
  }

  async function saveQuestions() {
    await Promise.all(
      questions.map((question) =>
        axios.put(
          `${API_URL}/interview/questions/${question.id}`,
          { question_text: question.question_text },
          { timeout: 60000 }
        )
      )
    );
  }

  async function startPractice() {
    setLoading(true);
    setError("");
    try {
      await saveQuestions();
      navigate(`/interview/${draftId}`);
    } catch (requestError) {
      setError(friendlyError(requestError, "The questions could not be saved."));
      setLoading(false);
    }
  }

  async function addQuestion(event) {
    event.preventDefault();
    const text = newQuestion.trim();
    if (text.length < 8) {
      setError("Write a full question before adding it.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const form = new URLSearchParams();
      form.append("question_text", text);
      const response = await axios.post(`${API_URL}/interview/${draftId}/questions`, form, {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        timeout: 60000,
      });
      setQuestions((current) => [...current, response.data]);
      setNewQuestion("");
    } catch (requestError) {
      setError(friendlyError(requestError, "The question could not be added."));
    } finally {
      setLoading(false);
    }
  }

  async function removeQuestion(question) {
    setLoading(true);
    setError("");
    try {
      await axios.delete(`${API_URL}/interview/questions/${question.id}`, { timeout: 60000 });
      setQuestions((current) => current.filter((item) => item.id !== question.id));
    } catch (requestError) {
      setError(friendlyError(requestError, "The question could not be removed."));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page narrow">
      <p className="eyebrow">Interview</p>
      <h1>Interview</h1>
      <p className="lede">Open the interview you were sent. Paste the link or the interview ID.</p>
      {error ? <div className="alert alert-error">{error}</div> : null}
      <form className="card" onSubmit={openExisting}>
        <label htmlFor="existing-id">Interview link or ID</label>
        <input
          id="existing-id"
          value={existingId}
          onChange={(event) => setExistingId(event.target.value)}
          placeholder="Paste an interview link or ID"
        />
        <button className="btn btn-primary" type="submit" disabled={!existingId.trim()}>
          Open interview
        </button>
      </form>

      <section className="card" aria-labelledby="practice-heading">
        <h2 id="practice-heading">Practice</h2>
        <p>Want to warm up? Practice with a sample interview before the real one.</p>
        <form onSubmit={createPractice}>
          <label htmlFor="job-role">Job role</label>
          <input
            id="job-role"
            value={jobRole}
            onChange={(event) => setJobRole(event.target.value)}
            placeholder="Backend engineer"
            disabled={loading || Boolean(draftId)}
          />
          <label htmlFor="practice-role">Role family</label>
          <select
            id="practice-role"
            value={roleFamily}
            onChange={(event) => setRoleFamily(event.target.value)}
            disabled={loading || Boolean(draftId)}
          >
            {ROLE_OPTIONS.map((option) => (
              <option key={option.value || "infer"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <label htmlFor="practice-count">Main questions</label>
          <select
            id="practice-count"
            value={count}
            onChange={(event) => setCount(Number(event.target.value))}
            disabled={loading || Boolean(draftId)}
          >
            {QUESTION_COUNTS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
          <fieldset className="choice-set" disabled={loading || Boolean(draftId)}>
            <legend>Questions</legend>
            <label className="choice" htmlFor="practice-dynamic">
              <input
                id="practice-dynamic"
                type="radio"
                name="practice-mode"
                value="dynamic"
                checked={mode === "dynamic"}
                onChange={() => setMode("dynamic")}
              />
              <span>AI-generated questions</span>
            </label>
            <p className="muted">
              Written during the interview from the role and your earlier answers, with at most one follow-up each.
            </p>
            <label className="choice" htmlFor="practice-preset">
              <input
                id="practice-preset"
                type="radio"
                name="practice-mode"
                value="preset"
                checked={mode === "preset"}
                onChange={() => setMode("preset")}
              />
              <span>Preset questions</span>
            </label>
            <p className="muted">Draft a fixed list with AI, then edit it before you start.</p>
          </fieldset>
          {!draftId ? (
            <button className="btn btn-secondary" type="submit" disabled={loading || !jobRole.trim()}>
              {loading ? "Creating your interview…" : mode === "preset" ? "Draft practice questions" : "Start practice"}
            </button>
          ) : null}
        </form>
        {draftId ? (
          <div>
            <QuestionEditor
              questions={questions}
              disabled={loading}
              onChange={(questionId, questionText) =>
                setQuestions((current) =>
                  current.map((item) => (item.id === questionId ? { ...item, question_text: questionText } : item))
                )
              }
              onRemove={removeQuestion}
            />
            <form onSubmit={addQuestion}>
              <label htmlFor="practice-new-question">Add a question</label>
              <textarea
                id="practice-new-question"
                value={newQuestion}
                onChange={(event) => setNewQuestion(event.target.value)}
                disabled={loading || questions.length >= 8}
              />
              <button className="btn btn-ghost" type="submit" disabled={loading || questions.length >= 8}>
                Add question
              </button>
            </form>
            <button className="btn btn-primary" type="button" onClick={startPractice} disabled={loading}>
              {loading ? "Saving…" : "Start practice"}
            </button>
          </div>
        ) : null}
      </section>
    </div>
  );
}
