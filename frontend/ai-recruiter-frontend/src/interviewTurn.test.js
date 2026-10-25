import { createTurnController } from "./interviewTurn";

test("silence after playback uploads once and the next question plays once", () => {
  const turn = createTurnController();
  expect(turn.startPlayback("q1")).toBe("play");
  expect(turn.vad("silence")).toBe("ignore");
  expect(turn.playbackEnded()).toBe("listen");
  expect(turn.vad("listening")).toBe("wait");
  expect(turn.vad("silence")).toBe("upload");
  expect(turn.vad("silence")).toBe("ignore");
  expect(turn.uploaded({ nextKey: "q2", completed: false })).toBe("play-next");
  expect(turn.uploaded({ nextKey: "q3", completed: false })).toBe("ignore");
  expect(turn.playbackEnded()).toBe("listen");
  expect(turn.vad("silence")).toBe("upload");
  expect(turn.uploaded({ nextKey: "", completed: true })).toBe("goodbye");
  expect(turn.vad("silence")).toBe("ignore");
});

test("a missed answer replays the question once, then moves on without another replay", () => {
  const turn = createTurnController();
  turn.startPlayback("q1");
  turn.playbackEnded();
  expect(turn.vad("reprompt")).toBe("replay");
  expect(turn.vad("reprompt")).toBe("ignore");
  expect(turn.playbackEnded()).toBe("listen");
  expect(turn.vad("reprompt")).toBe("upload-silent");
  expect(turn.uploaded({ nextKey: "q1", completed: false })).toBe("listen");
  expect(turn.vad("silence")).toBe("upload");
});
