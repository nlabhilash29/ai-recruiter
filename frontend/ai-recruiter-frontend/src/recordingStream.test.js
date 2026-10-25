import { liveAudioTracks } from "./recordingStream";

test("recording uses the live microphone track and leaves the camera track out", () => {
  const audio = { kind: "audio", readyState: "live" };
  const ended = { kind: "audio", readyState: "ended" };
  const camera = { kind: "video", readyState: "live" };
  const stream = {
    getAudioTracks: () => [ended, audio],
    getVideoTracks: () => [camera],
  };
  expect(liveAudioTracks(stream)).toEqual([audio]);
  expect(liveAudioTracks(null)).toEqual([]);
});
