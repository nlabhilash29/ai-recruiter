export const API_URL = (process.env.REACT_APP_API_URL || 'http://localhost:8000').replace(/\/$/, '');

export function apiErrorMessage(error, fallback) {
  let data = error?.response?.data;

  if (data instanceof ArrayBuffer) {
    try {
      data = JSON.parse(new TextDecoder().decode(new Uint8Array(data)));
    } catch (parseError) {
      data = null;
    }
  }

  if (typeof data === 'string') {
    const trimmed = data.trim();
    if (trimmed.startsWith('<')) {
      return 'The interview API is unavailable. It returned a web page instead of JSON.';
    }
    try {
      data = JSON.parse(trimmed);
    } catch (parseError) {
      return trimmed.slice(0, 300) || fallback;
    }
  }

  const detail = data?.detail ?? data?.message;
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg || JSON.stringify(item)).join('; ');
  }
  if (!error?.response) {
    return 'No response from the interview API. Check that the backend is running and REACT_APP_API_URL points at it.';
  }
  return fallback;
}

export function decodeAssistantText(headerValue) {
  if (!headerValue) return '';
  try {
    const binary = window.atob(headerValue);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  } catch (error) {
    return '';
  }
}
