import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import axios from "axios";
import { API_URL, friendlyError } from "../api";
import ResultsView from "../components/ResultsView";

export default function PracticeResultsPage() {
  const { id } = useParams();
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [recruiterOnly, setRecruiterOnly] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await axios.get(`${API_URL}/interview/${id}/results`, { timeout: 90000 });
        if (!cancelled) setReport(response.data);
      } catch (requestError) {
        if (cancelled) return;
        if (requestError.response?.status === 401) {
          setRecruiterOnly(true);
          return;
        }
        setError(friendlyError(requestError, "The feedback could not be loaded."));
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <div className="page">
      <Link className="text-link" to={`/interview/${id}`}>
        Back to interview
      </Link>
      {recruiterOnly ? (
        <section className="card">
          <h1>Results stay with the recruiter</h1>
          <p>This interview's report is not shown on the candidate link.</p>
        </section>
      ) : null}
      {error ? <div className="alert alert-error">{error}</div> : null}
      {!report && !error && !recruiterOnly ? <p className="card">Loading feedback…</p> : null}
      {report ? (
        <>
          <p className="eyebrow">Practice feedback</p>
          <ResultsView report={report} />
        </>
      ) : null}
    </div>
  );
}
