/** Energy-based voice activity for the hands-free interview. */

export const SILENCE_MS = 2800;
export const NO_SPEECH_MS = 15000;
export const SPEECH_HOLD_MS = 400;
export const MAX_ANSWER_MS = 165000;
export const THRESHOLD_FLOOR = 0.03;
export const THRESHOLD_CAP = 0.2;

export function calibrateThreshold(samples) {
  const usable = (samples || []).filter((value) => Number.isFinite(value) && value >= 0);
  if (!usable.length) return THRESHOLD_FLOOR;
  const sorted = [...usable].sort((left, right) => left - right);
  const index = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.8));
  const ambient = sorted[index];
  return Math.min(THRESHOLD_CAP, Math.max(THRESHOLD_FLOOR, ambient * 3.5 + 0.015));
}

export function levelPercent(rms) {
  if (!Number.isFinite(rms) || rms <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round(rms * 420)));
}

/**
 * step(rms, nowMs) returns { event, countdown }.
 * event is listening, reprompt, no-speech, silence, or max.
 * Silence is counted only after speech has been heard.
 * countdown is 2, then 1, while the closing silence is underway.
 */
export function createVadController({ threshold = THRESHOLD_FLOOR } = {}) {
  let speechMs = 0;
  let silenceMs = 0;
  let elapsedMs = 0;
  let last = null;
  let speechStarted = false;
  let reprompted = false;

  function restart() {
    speechMs = 0;
    silenceMs = 0;
    elapsedMs = 0;
    last = null;
    speechStarted = false;
  }

  return {
    get speechStarted() {
      return speechStarted;
    },
    get reprompted() {
      return reprompted;
    },
    restart,
    markReprompted() {
      reprompted = true;
      restart();
    },
    step(rms, nowMs) {
      const loud = Number(rms) >= threshold;
      const delta = last == null ? 0 : Math.min(300, Math.max(0, nowMs - last));
      last = nowMs;
      elapsedMs += delta;

      if (!speechStarted) {
        if (loud) speechMs += delta;
        else speechMs = 0;
        if (speechMs >= SPEECH_HOLD_MS) speechStarted = true;
        if (!speechStarted && elapsedMs >= NO_SPEECH_MS) {
          return { event: reprompted ? "no-speech" : "reprompt", countdown: null, speechStarted: false };
        }
        return { event: "listening", countdown: null, speechStarted };
      }

      if (loud) silenceMs = 0;
      else silenceMs += delta;

      if (elapsedMs >= MAX_ANSWER_MS) {
        return { event: "max", countdown: null, speechStarted: true };
      }
      if (silenceMs >= SILENCE_MS) {
        return { event: "silence", countdown: null, speechStarted: true };
      }
      const remaining = SILENCE_MS - silenceMs;
      const countdown = silenceMs > 0 && remaining <= 2000 ? Math.max(1, Math.ceil(remaining / 1000)) : null;
      return { event: "listening", countdown, speechStarted: true };
    },
  };
}
