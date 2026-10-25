/**
 * Decides when a hands-free interview may listen, upload, or move on.
 * Playback ending is the only way into listening. Silence uploads once.
 * A no-speech replay can happen once; the same question is not spoken again after that.
 */
export function createTurnController() {
  let mode = "idle";
  let questionKey = "";
  let reprompted = false;
  let uploadedKey = "";

  return {
    get mode() {
      return mode;
    },
    startPlayback(key) {
      if (key) questionKey = String(key);
      mode = "speaking";
      return "play";
    },
    playbackEnded() {
      if (mode !== "speaking") return "ignore";
      mode = "listening";
      return "listen";
    },
    vad(event) {
      if (mode !== "listening") return "ignore";
      if (event === "silence" || event === "max") {
        mode = "uploading";
        uploadedKey = questionKey;
        return "upload";
      }
      if (event === "reprompt") {
        if (reprompted) {
          mode = "uploading";
          uploadedKey = questionKey;
          return "upload-silent";
        }
        reprompted = true;
        mode = "speaking";
        return "replay";
      }
      if (event === "no-speech") {
        mode = "uploading";
        uploadedKey = questionKey;
        return "upload-silent";
      }
      return "wait";
    },
    uploaded({ nextKey, completed }) {
      if (mode !== "uploading") return "ignore";
      if (completed || !nextKey) {
        mode = "goodbye";
        questionKey = "";
        return "goodbye";
      }
      if (String(nextKey) === uploadedKey) {
        mode = "listening";
        return "listen";
      }
      questionKey = String(nextKey);
      reprompted = false;
      mode = "speaking";
      return "play-next";
    },
  };
}
