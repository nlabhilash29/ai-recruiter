import { calibrateThreshold, createVadController, NO_SPEECH_MS, SILENCE_MS, SPEECH_HOLD_MS } from "./vad";

test("calibration raises the floor above room noise and stays bounded", () => {
  expect(calibrateThreshold([])).toBeCloseTo(0.03);
  expect(calibrateThreshold([0.01, 0.01, 0.02, 0.04])).toBeGreaterThan(0.03);
  expect(calibrateThreshold([0.5, 0.5, 0.5])).toBeCloseTo(0.2);
});

function walk(vad, rms, from, duration) {
  let now = from;
  let last = null;
  while (now < from + duration) {
    now += 100;
    last = vad.step(rms, now);
  }
  return last;
}

test("silence counts only after speech, and more speech cancels the countdown", () => {
  const vad = createVadController({ threshold: 0.05 });
  expect(vad.step(0.2, 0).event).toBe("listening");
  const started = walk(vad, 0.2, 0, SPEECH_HOLD_MS);
  expect(started.speechStarted).toBe(true);

  const hint = walk(vad, 0.01, SPEECH_HOLD_MS, 900);
  expect(hint.event).toBe("listening");
  expect(hint.countdown).toBe(2);

  const cancelled = vad.step(0.2, SPEECH_HOLD_MS + 1000);
  expect(cancelled.countdown).toBeNull();

  const closed = walk(vad, 0.01, SPEECH_HOLD_MS + 1000, SILENCE_MS);
  expect(closed.event).toBe("silence");
});

test("no speech re-prompts once, then ends the turn", () => {
  const vad = createVadController({ threshold: 0.05 });
  expect(vad.step(0.01, 0).event).toBe("listening");
  expect(walk(vad, 0.01, 0, NO_SPEECH_MS).event).toBe("reprompt");
  vad.markReprompted();
  expect(vad.step(0.01, 0).event).toBe("listening");
  expect(walk(vad, 0.01, 0, NO_SPEECH_MS).event).toBe("no-speech");
});
