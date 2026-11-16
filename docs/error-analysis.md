# Error analysis

Use this after a demo or a batch of interviews. The goal is to name why a score or a question was wrong, using the trace and the recruiter's verdict, and to pick the next fix from the counts.

Golden-set evals are not part of this loop yet. Start from recruiter feedback and the traces.

## How to collect a row

1. Open the recruiter report and read **How this score was built**.
2. Save a verdict on the question. A down vote should include a reason.
3. Open the Langfuse trace when it is configured, or the matching line in `backend/.traces/*.jsonl`. The trace id is the interview id with the dashes removed.
4. Export the rows:

```bash
curl -o feedback.csv "$API/recruiter/feedback.csv"
```

From `backend/` against the local database:

```bash
python scripts/export_feedback.py --output feedback.csv
```

5. Add one line to the table below. The reason picker maps onto the taxonomy like this:

| Recruiter reason | Starting category |
| --- | --- |
| Transcription error | Transcription error |
| Score too high / score too low, and the quote is missing or invented | Score without evidence |
| Evidence not in the answer | Score without evidence |
| Bad question | Generic or overlapping question, or wrong role inferred |
| Other, and the trace shows `fallback_used` | Fallback fired |
| Other, and the span latency is the complaint | Latency or cold start |

## Starting taxonomy

| Category | What it looks like | Where to confirm |
| --- | --- | --- |
| Transcription error | The transcript does not match what was said, or it is cut off mid-word | `transcription` span and the saved transcript |
| Answer cut off early | The answer stops before the example is finished, often right at the silence timeout | Transcript length and the listening timestamps |
| Score without evidence | A dimension has a number, but the quote is empty or is not in the transcript | Confidence checks `scored_without_evidence` and `evidence_in_transcript` |
| Wrong role inferred | Questions or anchors assume a different job than the description | `role_family` on the interview and the question text |
| Generic or overlapping question | The question could be asked of anyone, or it repeats an earlier anchor | `question.next` span and the question list |
| Fallback fired | Default questions, a thin-answer analysis, or **Not assessed — scoring unavailable** | Error event on the span, `fallback_used` on the answer |
| Latency or cold start | The first request or a model call takes long enough that the interview feels stalled | Span `ms`, and the cold-start copy on the first hit after Render sleeps |

## Table

| Interview | Question | Category | What happened | Evidence in the trace | Next fix |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

## After a batch

Count the rows by category. Fix the category that recruiters hit most often, then run another interview and see whether that category shrinks. Keep the model price table (`MODEL_PRICES_JSON`) next to the cost column so a slow, expensive call is visible beside a wrong score.
