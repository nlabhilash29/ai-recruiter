import { API_URL } from "../api";

export const READY_TEXT = "The interviewer is getting ready. This can take up to a minute.";

const MISSING_API = "This deployment has no API address. Set REACT_APP_API_URL and rebuild.";

export function MissingApiNotice() {
  if (API_URL) return null;
  return (
    <div className="cold-start" role="status">
      {MISSING_API}
    </div>
  );
}

export default function ColdStart({ active = false }) {
  if (!active || !API_URL) return null;
  return (
    <div className="cold-start" role="status" aria-live="polite">
      {READY_TEXT}
    </div>
  );
}
