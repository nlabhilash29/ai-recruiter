const configured = process.env.REACT_APP_API_URL;
export const API_URL =
  configured || (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");

const TOKEN_KEY = "recruiterToken";

export function getRecruiterToken() {
  return window.localStorage.getItem(TOKEN_KEY) || "";
}

export function setRecruiterToken(token) {
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

export function authHeaders() {
  const token = getRecruiterToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function prefersReducedMotion() {
  try {
    return (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  } catch (error) {
    return false;
  }
}

function extractDetail(error) {
  const data = error?.response?.data;
  if (!data) return "";
  if (data instanceof ArrayBuffer) {
    try {
      const parsed = JSON.parse(new TextDecoder().decode(data));
      return parsed.detail || parsed.message || "";
    } catch (decodeError) {
      return "";
    }
  }
  if (typeof data === "string") return data;
  if (typeof data.detail === "string") return data.detail;
  if (typeof data.message === "string") return data.message;
  return "";
}

export function friendlyError(error, fallback = "Something went wrong. Please try again.") {
  if (!error) return fallback;
  const status = error.response?.status;
  const detail = extractDetail(error);
  const lower = detail.toLowerCase();
  const message = `${detail} ${error.message || ""}`.toLowerCase();

  if (!error.response) {
    if (error.code === "ECONNABORTED" || /timeout/.test(message)) {
      return "The request timed out before the interviewer responded. Please try again.";
    }
    return "We could not reach the interviewer. Check your connection and try again.";
  }
  if (status === 503 && detail) return detail;
  if (/already completed/.test(lower)) return "This interview is already completed.";
  if (status === 404 || /interview not found|not found/.test(lower)) return "Interview not found.";
  if (status === 413 || /too large|5\s?mb/.test(lower)) {
    return "That file is too large. Please keep it under 5 MB.";
  }
  if (
    /text-to-speech failed with status 401|elevenlabs api error:\s*401|voice service/.test(lower) ||
    (status === 401 && /voice|eleven|tts|text-to-speech/.test(lower))
  ) {
    return "The voice service is having trouble right now. Please try again in a moment.";
  }
  if (/transcri|whisper|speech-to-text/.test(lower)) {
    return "The transcription service is having trouble right now. Please try again in a moment.";
  }
  if (status === 504 || /timed out|timeout/.test(lower)) {
    return "The request timed out. Please try again.";
  }
  if (status === 429) return "The service is busy right now. Please wait a moment and try again.";
  if (detail && detail.length < 240 && !/traceback|exception|status \d{3}|api error/i.test(detail)) {
    return detail;
  }
  if (status === 401) return "Please sign in again to continue.";
  return fallback;
}

export function formatScore(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  if (Number.isNaN(number)) return null;
  return (Math.round(number * 10) / 10).toFixed(1);
}

export function candidateLink(interviewId) {
  return `${window.location.origin}/interview/${interviewId}`;
}
