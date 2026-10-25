import { useEffect, useState } from "react";
import axios from "axios";
import { API_URL } from "../api";

const READY_TEXT = "The interviewer is getting ready. This can take up to a minute.";

export default function ColdStart() {
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!API_URL) {
      setMessage("This deployment has no API address. Set REACT_APP_API_URL and rebuild.");
      return undefined;
    }

    let cancelled = false;
    let showedSlow = false;
    const slowTimer = window.setTimeout(() => {
      showedSlow = true;
      if (!cancelled) setMessage(READY_TEXT);
    }, 700);

    async function ping() {
      try {
        await axios.get(`${API_URL}/health`, { timeout: 90000 });
        if (!cancelled) setMessage("");
      } catch (error) {
        if (cancelled) return;
        setMessage(READY_TEXT);
        window.setTimeout(ping, 4000);
      }
    }

    ping();
    return () => {
      cancelled = true;
      window.clearTimeout(slowTimer);
      if (!showedSlow) setMessage("");
    };
  }, []);

  if (!message) return null;

  return (
    <div className="cold-start" role="status" aria-live="polite">
      {message}
    </div>
  );
}
