export default function QuestionEditor({ questions, onChange, onRemove, disabled }) {
  return (
    <div>
      {questions.map((question, index) => {
        const fieldId = `question-${question.id || index}`;
        return (
          <div className="editor" key={question.id || index}>
            <div className="editor-head">
              <label htmlFor={fieldId}>Question {index + 1}</label>
              {questions.length > 1 ? (
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => onRemove(question)}
                  disabled={disabled}
                >
                  Remove
                </button>
              ) : null}
            </div>
            <textarea
              id={fieldId}
              value={question.question_text}
              disabled={disabled}
              onChange={(event) => onChange(question.id, event.target.value)}
            />
          </div>
        );
      })}
    </div>
  );
}
