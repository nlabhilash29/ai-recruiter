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

function anchorText(anchors, score) {
  if (!anchors || score == null) return "";
  const value = Number(score);
  const points = Object.keys(anchors)
    .map((key) => Number(key))
    .filter((key) => Number.isFinite(key))
    .sort((left, right) => Math.abs(left - value) - Math.abs(right - value));
  if (!points.length) return "";
  return anchors[points[0]] || anchors[String(points[0])] || "";
}

const LEGACY_NOTE =
  "Each answer is scored out of 10. The number on a question is how relevant that answer was. The overall score averages technical accuracy and communication (clarity) across all answers, and it is also out of 10. Because those are different measures, one question can sit above or below the overall score.";

export default function ResultsView({ report }) {
  const scoring = report.scoring || {};
  const summary = report.interview_summary || {};
  const strengths = (summary.strengths || []).map((item) => String(item || "").trim()).filter(Boolean);
  const improvements = (summary.areas_for_improvement || [])
    .map((item) => String(item || "").trim())
    .filter(Boolean);
  const overall = formatScore(scoring.overall_score);
  const legacy = Boolean(scoring.legacy);
  const dimensions = scoring.rubric?.dimensions || [];
  const subscores = [
    ["Technical", scoring.technical_score],
    ["Communication", scoring.communication_score],
    ["Cultural fit", scoring.cultural_fit_score],
  ].filter(([, value]) => formatScore(value) !== null);

  return (
    <div className="results">
      <article className="summary-card">
        <h2>
          {[report.candidate?.name, report.job_description?.title].filter(Boolean).join(" · ") || "Interview"}
        </h2>
        <p className="lede">{summary.overall_recommendation || "Results"}</p>
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
        <p className="score-note">{scoring.score_note || LEGACY_NOTE}</p>
        {legacy && subscores.length > 0 && (
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
        {!legacy && dimensions.length > 0 && (
          <ul className="subscore-list">
            {dimensions.map((dimension) => {
              const value = scoring.dimension_scores?.[dimension.id];
              const text = formatScore(value);
              return (
                <li key={dimension.id}>
                  <span>
                    {dimension.label}
                    <small className="weight"> {dimension.weight}%</small>
                  </span>
                  <strong>{text ? `${text}/10` : "Not assessed"}</strong>
                  {text ? <ScoreBar value={value} /> : null}
                  <p className="muted">{dimension.descriptor}</p>
                </li>
              );
            })}
          </ul>
        )}
        {!legacy && dimensions[0]?.anchors && (
          <details className="anchors">
            <summary>How a 1–10 score is anchored</summary>
            {dimensions.map((dimension) => (
              <div key={dimension.id}>
                <h3>{dimension.label}</h3>
                <ul className="plain-list">
                  {Object.keys(dimension.anchors)
                    .sort((left, right) => Number(left) - Number(right))
                    .map((mark) => (
                      <li key={mark}>
                        <strong>{mark}.</strong> {dimension.anchors[mark]}
                      </li>
                    ))}
                </ul>
              </div>
            ))}
          </details>
        )}
      </article>

      {(report.questions || []).map((question, index) => (
        <article className="question-card" key={question.id || index}>
          <header className="question-card-head">
            <p>{question.progress_label || `Question ${question.sequence_number || index + 1}`}</p>
            {question.is_follow_up ? <span className="chip">Follow-up</span> : null}
          </header>
          <h3>{question.question_text}</h3>
          {(question.responses || []).length === 0 && <p className="muted">No answer recorded.</p>}
          {(question.responses || []).map((response, responseIndex) => {
            const feedback = (response.ai_feedback || "").trim();
            const improve = (response.improvement_suggestions || "").trim();
            const evidence = (response.evidence || "").trim();
            const dimensionScores = response.dimension_scores || {};
            const scoredDimensions = dimensions.filter((dimension) => formatScore(dimensionScores[dimension.id]) !== null);
            const primary = dimensions.find((dimension) => dimension.id === question.dimension);
            const primaryScore = primary ? dimensionScores[primary.id] : null;
            const nearest = anchorText(primary?.anchors, primaryScore);
            return (
              <div className="answer-block" key={responseIndex}>
                <h4>Transcript</h4>
                <p className="transcript">{response.response_text || "No transcript was saved."}</p>
                {evidence ? (
                  <>
                    <h4>Evidence</h4>
                    <p>“{evidence}”</p>
                  </>
                ) : null}
                <div className="chip-row">
                  {scoredDimensions.map((dimension) => (
                    <ScoreChip key={dimension.id} label={dimension.label} value={dimensionScores[dimension.id]} />
                  ))}
                  {scoredDimensions.length === 0 && (
                    <>
                      <ScoreChip label="Relevance" value={response.score} />
                      <ScoreChip label="Clarity" value={response.clarity_score} />
                      <ScoreChip label="Technical" value={response.technical_accuracy} />
                    </>
                  )}
                </div>
                {nearest ? <p className="muted">Nearest anchor: {nearest}</p> : null}
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
