import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import axios from "axios";
import { API_URL, authHeaders, friendlyError } from "../api";
import ResultsView from "../components/ResultsView";

export default function ReportPage() {
  const { id } = useParams();
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await axios.get(`${API_URL}/interview/${id}/details`, {
          headers: authHeaders(),
          timeout: 90000,
        });
        if (!cancelled) setReport(response.data);
      } catch (requestError) {
        if (!cancelled) setError(friendlyError(requestError, "The report could not be loaded."));
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <div className="page">
      <Link className="text-link" to="/recruiter">
        All interviews
      </Link>
      {error ? <div className="alert alert-error">{error}</div> : null}
      {!report && !error ? <p className="card">Loading the report…</p> : null}
      {report ? <ResultsView report={report} /> : null}
    </div>
  );
}
