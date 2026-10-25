import { formatScore } from "../api";

function ScoreBar({ value }) {
  const label = formatScore(value);
  if (label === null) return null;
  const width = Math.max(0, Math.min(100, Number(label) * 10));
  return (
    <div className="score-bar" aria-hidden="true">
      <span style={{ width: `${width}%` }} />
    </div>
  );
}

function ScoreChip({ label, value }) {
  const text = formatScore(value);
  if (text === null) return null;
  return (
    <span className="chip">
      {label} {text}/10
    </span>
  );
}

export default function ResultsView({ report }) {
  const scoring = report.scoring || {};
  const summary = report.interview_summary || {};
  const strengths = (summary.strengths || []).map((item) => String(item || "").trim()).filter(Boolean);
  const improvements = (summary.areas_for_improvement || [])
    .map((item) => String(item || "").trim())
    .filter(Boolean);
  const overall = formatScore(scoring.overall_score);
  const subscores = [
    ["Technical", scoring.technical_score],
    ["Communication", scoring.communication_score],
    ["Cultural fit", scoring.cultural_fit_score],
  ].filter(([, value]) => formatScore(value) !== null);

  return (
    <div className="results">
      <article className="summary-card">
        <p className="eyebrow">
          {report.job_description?.title || "Interview"}
          {report.candidate?.name ? ` · ${report.candidate.name}` : ""}
        </p>
        <h2>{summary.overall_recommendation || "Results"}</h2>
        <div className="overall-score">
          <p className="overall-number">
            <span>{overall || "—"}</span>
            <small>/10</small>
          </p>
          <div>
            <p className="overall-label">Overall score</p>
            <ScoreBar value={scoring.overall_score} />
          </div>
        </div>
        <p className="score-note">
          Each answer is scored out of 10. The number on a question is how relevant that answer was.
          The overall score averages technical accuracy and communication (clarity) across all answers,
          and it is also out of 10. Because those are different measures, one question can sit above
          or below the overall score.
        </p>
        {subscores.length > 0 && (
          <ul className="subscore-list">
            {subscores.map(([label, value]) => (
              <li key={label}>
                <span>{label}</span>
                <strong>{formatScore(value)}/10</strong>
                <ScoreBar value={value} />
              </li>
            ))}
          </ul>
        )}
      </article>

      {(report.questions || []).map((question, index) => (
        <article className="question-card" key={question.id || index}>
          <header className="question-card-head">
            <p>Question {question.sequence_number || index + 1}</p>
            {question.question_type ? <span className="chip">{question.question_type}</span> : null}
          </header>
          <h3>{question.question_text}</h3>
          {(question.responses || []).length === 0 && <p className="muted">No answer recorded.</p>}
          {(question.responses || []).map((response, responseIndex) => {
            const feedback = (response.ai_feedback || "").trim();
            const improve = (response.improvement_suggestions || "").trim();
            return (
              <div className="answer-block" key={responseIndex}>
                <h4>Transcript</h4>
                <p className="transcript">{response.response_text || "No transcript was saved."}</p>
                <div className="chip-row">
                  <ScoreChip label="Relevance" value={response.score} />
                  <ScoreChip label="Clarity" value={response.clarity_score} />
                  <ScoreChip label="Technical" value={response.technical_accuracy} />
                </div>
                {feedback ? (
                  <>
                    <h4>Feedback</h4>
                    <p>{feedback}</p>
                  </>
                ) : null}
                {improve ? (
                  <>
                    <h4>What to improve</h4>
                    <p>{improve}</p>
                  </>
                ) : null}
              </div>
            );
          })}
        </article>
      ))}

      <section className="summary-card">
        <h3>Strengths</h3>
        {strengths.length > 0 ? (
          <ul className="plain-list">
            {strengths.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        ) : (
          <p className="empty-state">
            No standout strengths yet. Answers scored 8.0/10 or higher are collected here.
          </p>
        )}
        {improvements.length > 0 && (
          <>
            <h3>Lower-scoring answers</h3>
            <ul className="plain-list">
              {improvements.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
