/** Audio tracks that can be handed to MediaRecorder. Video tracks must stay out. */

export function liveAudioTracks(stream) {
  if (!stream || typeof stream.getAudioTracks !== "function") return [];
  return stream.getAudioTracks().filter((track) => track && track.readyState === "live");
}
