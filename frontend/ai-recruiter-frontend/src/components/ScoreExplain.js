import { useState } from "react";
import { friendlyError, saveScoreFeedback } from "../api";

const REASONS = [
  ["score_too_high", "Score too high"],
  ["score_too_low", "Score too low"],
  ["evidence_not_in_answer", "Evidence not in the answer"],
  ["bad_question", "Bad question"],
  ["transcription_error", "Transcription error"],
  ["other", "Other"],
];

function formatLatency(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (Number.isNaN(number)) return "—";
  if (number < 1000) return `${Math.round(number)} ms`;
  return `${(number / 1000).toFixed(1)} s`;
}

function formatCost(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (Number.isNaN(number)) return "—";
  if (number === 0) return "$0";
  if (number < 0.0001) return `$${number.toFixed(6)}`;
  return `$${number.toFixed(4)}`;
}

export default function ScoreExplain({ interviewId, response, traceUrl }) {
  const confidence = response.confidence || {};
  const saved = response.feedback || {};
  const [vote, setVote] = useState(saved.vote || "");
  const [reason, setReason] = useState(saved.reason || "");
  const [override, setOverride] = useState(
    saved.score_override === null || saved.score_override === undefined ? "" : String(saved.score_override)
  );
  const [note, setNote] = useState(saved.note || "");
  const [status, setStatus] = useState(saved.vote ? "Saved" : "");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const level = confidence.level || "not_assessed";
  const quoteFound = confidence.evidence_in_transcript;

  async function save() {
    setPending(true);
    setError("");
    try {
      const payload = {
        vote,
        reason: vote === "down" ? reason || null : null,
        note: note.trim() || null,
        score_override: override === "" ? null : Number(override),
      };
      await saveScoreFeedback(interviewId, response.id, payload);
      setStatus("Saved");
    } catch (requestError) {
      setStatus("");
      setError(friendlyError(requestError, "Feedback could not be saved."));
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="explain" aria-label="How this score was built">
      <h4>How this score was built</h4>
      <div className="chip-row">
        <span className={`badge badge-${level}`}>{confidence.label || "Not assessed"}</span>
        {response.fallback_label ? <span className="badge badge-warn">Fallback · {response.fallback_label}</span> : null}
        {quoteFound === true ? <span className="badge badge-high">Quote in transcript</span> : null}
        {quoteFound === false ? <span className="badge badge-low">Quote not in transcript</span> : null}
      </div>
      {confidence.reasons?.length ? (
        <ul className="plain-list explain-reasons">
          {confidence.reasons.map((reasonText) => (
            <li key={reasonText}>{reasonText}</li>
          ))}
        </ul>
      ) : null}
      <dl className="explain-meta">
        <div>
          <dt>Model</dt>
          <dd>{response.model || "Not recorded"}</dd>
        </div>
        <div>
          <dt>Latency</dt>
          <dd>{formatLatency(response.latency_ms)}</dd>
        </div>
        <div>
          <dt>Est. cost</dt>
          <dd>{formatCost(response.cost_usd)}</dd>
        </div>
        <div>
          <dt>Prompt</dt>
          <dd>{response.prompt_version || "—"}</dd>
        </div>
      </dl>
      {traceUrl ? (
        <a className="plain-link" href={traceUrl} target="_blank" rel="noreferrer">
          Open this trace in Langfuse
        </a>
      ) : (
        <p className="muted explain-note">
          Langfuse is not configured, so this trace stays in the API log.
        </p>
      )}

      <div className="feedback-box">
        <p className="feedback-label">Recruiter check</p>
        <div className="chip-row">
          <button
            type="button"
            className={`btn btn-secondary ${vote === "up" ? "is-selected" : ""}`}
            aria-pressed={vote === "up"}
            onClick={() => setVote("up")}
          >
            Helpful
          </button>
          <button
            type="button"
            className={`btn btn-secondary ${vote === "down" ? "is-selected" : ""}`}
            aria-pressed={vote === "down"}
            onClick={() => setVote("down")}
          >
            Not helpful
          </button>
        </div>
        {vote === "down" ? (
          <label>
            Reason
            <select value={reason} onChange={(event) => setReason(event.target.value)}>
              <option value="">Choose a reason</option>
              {REASONS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label>
          Score override
          <input
            type="number"
            min="1"
            max="10"
            step="0.1"
            inputMode="decimal"
            value={override}
            placeholder="Optional, 1–10"
            onChange={(event) => setOverride(event.target.value)}
          />
        </label>
        <label>
          Note
          <input value={note} maxLength={500} placeholder="Optional" onChange={(event) => setNote(event.target.value)} />
        </label>
        <div className="chip-row">
          <button type="button" className="btn btn-primary" disabled={!vote || pending} onClick={save}>
            {pending ? "Saving…" : "Save feedback"}
          </button>
          {status ? <span className="muted">{status}</span> : null}
        </div>
        {error ? <p className="alert alert-error">{error}</p> : null}
      </div>
    </section>
  );
}
