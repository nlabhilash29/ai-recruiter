import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import axios from "axios";
import { API_URL, friendlyError } from "../api";
import ColdStart from "../components/ColdStart";
import { createTurnController } from "../interviewTurn";
import { liveAudioTracks } from "../recordingStream";
import { calibrateThreshold, createVadController, levelPercent, MAX_ANSWER_MS } from "../vad";

const MAX_UPLOAD_BYTES = 4.5 * 1024 * 1024;
const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";
const AUDIO_CONSTRAINTS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

function chooseMime() {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return "";
  }
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function rmsFrom(analyser, buffer) {
  analyser.getByteTimeDomainData(buffer);
  let sum = 0;
  for (let index = 0; index < buffer.length; index += 1) {
    const sample = (buffer[index] - 128) / 128;
    sum += sample * sample;
  }
  return Math.sqrt(sum / buffer.length);
}

export default function InterviewPage() {
  const { id } = useParams();
  const [session, setSession] = useState(null);
  const [phase, setPhase] = useState("loading");
  const [error, setError] = useState("");
  const [level, setLevel] = useState(0);
  const [countdown, setCountdown] = useState(null);
  const [calibrated, setCalibrated] = useState(false);
  const [hasVideo, setHasVideo] = useState(false);
  const [cameraNote, setCameraNote] = useState("");
  const [playbackBlocked, setPlaybackBlocked] = useState(false);

  const previewRef = useRef(null);
  const streamRef = useRef(null);
  const audioContextRef = useRef(null);
  const meterRef = useRef(null);
  const playerRef = useRef(null);
  const playGenerationRef = useRef(0);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const vadRef = useRef(null);
  const turnRef = useRef(null);
  const listenTimerRef = useRef(0);
  const thresholdRef = useRef(0.03);
  const phaseRef = useRef(phase);
  const mimeRef = useRef("");
  const listenEpochRef = useRef(0);
  const calibrateRunRef = useRef(0);

  function move(next) {
    phaseRef.current = next;
    setPhase(next);
  }

  const attachPreview = useCallback((node) => {
    previewRef.current = node;
    const stream = streamRef.current;
    if (!node || !stream) return;
    if (node.srcObject !== stream) node.srcObject = stream;
    const pending = node.play();
    if (pending && pending.catch) {
      pending.catch((playError) => {
        if (!playError || playError.name === "AbortError") return;
      });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await axios.get(`${API_URL}/interview/${id}/session`, { timeout: 90000 });
        if (cancelled) return;
        setSession(response.data);
        if (response.data.status === "completed") move("goodbye");
        else if (!response.data.ready) move("unavailable");
        else move("device-check");
      } catch (requestError) {
        if (cancelled) return;
        setError(friendlyError(requestError, "This interview could not be opened."));
        move("unavailable");
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    return () => {
      window.clearInterval(listenTimerRef.current);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (audioContextRef.current) audioContextRef.current.close();
      if (playerRef.current) {
        playerRef.current.pause();
        playerRef.current.src = "";
      }
    };
  }, []);

  async function ensureContext() {
    if (!audioContextRef.current || audioContextRef.current.state === "closed") {
      audioContextRef.current = new AudioContext();
    }
    if (audioContextRef.current.state === "suspended") await audioContextRef.current.resume();
    return audioContextRef.current;
  }

  function wireMeter(context, stream) {
    if (meterRef.current) return meterRef.current;
    const analyser = context.createAnalyser();
    analyser.fftSize = 2048;
    const source = context.createMediaStreamSource(stream);
    const gain = context.createGain();
    gain.gain.value = 0;
    source.connect(analyser);
    analyser.connect(gain);
    gain.connect(context.destination);
    meterRef.current = { analyser, buffer: new Uint8Array(analyser.fftSize) };
    return meterRef.current;
  }

  useEffect(() => {
    if (phase !== "device-check") return undefined;
    const run = calibrateRunRef.current + 1;
    calibrateRunRef.current = run;
    let timer = 0;
    const stale = () => calibrateRunRef.current !== run;
    async function calibrate() {
      setCalibrated(false);
      let stream = streamRef.current;
      const reusable = liveAudioTracks(stream).length > 0;
      if (!reusable) {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ audio: AUDIO_CONSTRAINTS, video: true });
        } catch (requestError) {
          try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: AUDIO_CONSTRAINTS });
            if (!stale()) {
              setCameraNote("The camera is unavailable. You can still continue, because only audio is used.");
            }
          } catch (audioError) {
            if (!stale()) {
              setError("The microphone is blocked. Allow microphone access in the browser, then try again.");
            }
            return;
          }
        }
      }
      if (stale()) {
        if (stream && stream !== streamRef.current) {
          stream.getTracks().forEach((track) => track.stop());
        }
        return;
      }
      streamRef.current = stream;
      const videoLive = stream.getVideoTracks().some((track) => track.readyState === "live");
      setHasVideo(videoLive);
      if (videoLive) setCameraNote("");
      const context = await ensureContext();
      if (stale()) return;
      const meter = wireMeter(context, stream);
      const started = Date.now();
      const samples = [];
      timer = window.setInterval(() => {
        if (stale()) {
          window.clearInterval(timer);
          return;
        }
        const value = rmsFrom(meter.analyser, meter.buffer);
        samples.push(value);
        setLevel(levelPercent(value));
        if (Date.now() - started >= 1200) {
          window.clearInterval(timer);
          thresholdRef.current = calibrateThreshold(samples);
          setCalibrated(true);
        }
      }, 100);
    }
    calibrate();
    return () => {
      calibrateRunRef.current += 1;
      window.clearInterval(timer);
    };
  }, [phase]);

  function unlockPlayer() {
    const audio = playerRef.current || new Audio();
    playerRef.current = audio;
    audio.setAttribute("playsinline", "true");
    audio.src = SILENT_WAV;
    const pending = audio.play();
    if (pending && pending.catch) pending.catch(() => {});
    return audio;
  }

  function playUrl(url) {
    const audio = playerRef.current || unlockPlayer();
    playerRef.current = audio;
    const generation = playGenerationRef.current + 1;
    playGenerationRef.current = generation;
    setPlaybackBlocked(false);
    move("speaking");
    return new Promise((resolve) => {
      let settled = false;
      let started = false;
      const finish = (ok) => {
        if (settled || generation !== playGenerationRef.current) return;
        settled = true;
        audio.onended = null;
        audio.onerror = null;
        resolve(ok);
      };
      audio.pause();
      audio.onended = () => {
        if (started) finish(true);
      };
      audio.onerror = () => finish(false);
      audio.src = url;
      const pending = audio.play();
      if (pending && pending.then) {
        pending.then(() => {
          started = true;
          if (audio.ended) finish(true);
        });
        pending.catch(() => {
          setPlaybackBlocked(true);
          finish(false);
        });
      } else {
        started = true;
      }
    });
  }

  async function speakCurrent() {
    const response = await axios.post(`${API_URL}/interview/${id}/speak`, undefined, {
      responseType: "arraybuffer",
      timeout: 90000,
    });
    const url = URL.createObjectURL(new Blob([response.data], { type: "audio/mpeg" }));
    const played = await playUrl(url);
    URL.revokeObjectURL(url);
    return played;
  }

  function stopRecorder() {
    window.clearInterval(listenTimerRef.current);
    listenTimerRef.current = 0;
    const recorder = recorderRef.current;
    return new Promise((resolve) => {
      const finish = () => {
        recorderRef.current = null;
        const blob = new Blob(chunksRef.current, { type: mimeRef.current || "audio/webm" });
        resolve(blob);
      };
      if (!recorder || recorder.state === "inactive") {
        finish();
        return;
      }
      recorder.onstop = finish;
      try {
        recorder.stop();
      } catch (error) {
        finish();
      }
    });
  }

  async function uploadAnswer(blob, noSpeech) {
    move("thinking");
    setCountdown(null);
    setLevel(0);
    const form = new FormData();
    form.append("interview_id", id);
    if (noSpeech) {
      form.append("no_speech", "true");
    } else {
      const extension = blob.type.includes("mp4") ? "m4a" : "webm";
      form.append("file", blob, `answer.${extension}`);
    }
    const response = await axios.post(`${API_URL}/talk-video`, form, {
      responseType: "arraybuffer",
      timeout: 120000,
    });
    const status = response.headers["x-interview-status"];
    const next = await axios.get(`${API_URL}/interview/${id}/session`, { timeout: 90000 });
    setSession(next.data);
    const completed = status === "completed" || next.data.status === "completed" || !next.data.current_question;
    const action = turnRef.current.uploaded({
      nextKey: next.data.current_question?.id || "",
      completed,
    });
    if (action === "listen") {
      move("listening");
      startListening();
      return;
    }
    const url = URL.createObjectURL(new Blob([response.data], { type: "audio/mpeg" }));
    const played = await playUrl(url);
    URL.revokeObjectURL(url);
    if (action === "goodbye" || completed) {
      move("goodbye");
      return;
    }
    if (played && turnRef.current.playbackEnded() === "listen") startListening();
    else if (!played) move("listening");
  }

  function failMicrophone(message) {
    setError(message);
    move("mic-error");
  }

  function startListening() {
    const stream = streamRef.current;
    const meter = meterRef.current;
    const tracks = liveAudioTracks(stream);
    if (!tracks.length || !meter) {
      failMicrophone(
        "The microphone stopped before recording could start. Check the microphone, then begin again."
      );
      return;
    }
    const epoch = listenEpochRef.current + 1;
    listenEpochRef.current = epoch;
    setCountdown(null);
    vadRef.current = createVadController({ threshold: thresholdRef.current });
    const mime = chooseMime();
    mimeRef.current = mime;
    let recorder;
    chunksRef.current = [];
    let bytes = 0;
    try {
      if (!tracks.every((track) => track.readyState === "live")) {
        throw new Error("ended");
      }
      // Chrome refuses to start an audio-only recorder on a stream that still has a camera track.
      const recording = new MediaStream(tracks);
      recorder = mime ? new MediaRecorder(recording, { mimeType: mime }) : new MediaRecorder(recording);
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size) {
          chunksRef.current.push(event.data);
          bytes += event.data.size;
        }
      };
      recorder.onerror = () => {
        if (recorderRef.current !== recorder || recorder.state !== "recording") return;
        failMicrophone("Recording stopped unexpectedly. Check the microphone, then begin again.");
      };
      recorderRef.current = recorder;
      recorder.start(250);
    } catch (error) {
      recorderRef.current = null;
      failMicrophone(
        "The microphone could not start recording. Check the microphone, then begin again."
      );
      return;
    }
    setError("");
    move("listening");
    const started = Date.now();
    window.clearInterval(listenTimerRef.current);
    listenTimerRef.current = window.setInterval(() => {
      if (listenEpochRef.current !== epoch || phaseRef.current !== "listening") return;
      const player = playerRef.current;
      if (player && !player.paused && !player.ended) return;
      const value = rmsFrom(meter.analyser, meter.buffer);
      setLevel(levelPercent(value));
      const decision = vadRef.current.step(value, Date.now());
      setCountdown(decision.countdown);
      const tooLong = bytes > MAX_UPLOAD_BYTES || Date.now() - started >= MAX_ANSWER_MS;
      const action = turnRef.current.vad(tooLong ? "max" : decision.event);
      if (action === "wait" || action === "ignore") return;
      window.clearInterval(listenTimerRef.current);
      handleTurn(action, epoch);
    }, 100);
  }

  async function handleTurn(action, epoch) {
    if (listenEpochRef.current !== epoch) return;
    listenEpochRef.current += 1;
    const blob = await stopRecorder();
    try {
      if (action === "replay") {
        const played = await speakCurrent();
        if (played && turnRef.current.playbackEnded() === "listen") startListening();
        return;
      }
      const silent = action === "upload-silent" || !blob || blob.size < 400;
      await uploadAnswer(silent ? null : blob, silent);
    } catch (requestError) {
      const message = friendlyError(requestError, "Your answer could not be submitted. Please try again.");
      if (/already completed/i.test(message)) {
        move("goodbye");
        return;
      }
      setError(message);
      if (turnRef.current.mode === "uploading") {
        turnRef.current.uploaded({ nextKey: session?.current_question?.id || "retry", completed: false });
      }
      move("listening");
      if (turnRef.current.playbackEnded() === "listen" || turnRef.current.mode === "listening") startListening();
    }
  }

  async function beginInterview() {
    setError("");
    unlockPlayer();
    const context = await ensureContext();
    const stream = streamRef.current;
    if (!liveAudioTracks(stream).length) {
      setError("The microphone is blocked. Allow microphone access in the browser, then try again.");
      return;
    }
    wireMeter(context, stream);
    turnRef.current = createTurnController();
    turnRef.current.startPlayback(session?.current_question?.id || "question");
    move("speaking");
    try {
      const played = await speakCurrent();
      if (played && turnRef.current.playbackEnded() === "listen") startListening();
    } catch (requestError) {
      setError(friendlyError(requestError, "The question audio could not be played."));
      move("mic-error");
    }
  }

  async function hearQuestion() {
    try {
      turnRef.current?.startPlayback(session?.current_question?.id || "question");
      const played = await speakCurrent();
      if (played && turnRef.current.playbackEnded() === "listen") startListening();
    } catch (requestError) {
      setError(friendlyError(requestError, "The question audio could not be played."));
    }
  }

  const question = session?.current_question;
  const inConversation =
    phase === "speaking" || phase === "listening" || phase === "thinking" || phase === "mic-error";
  const statusText =
    phase === "speaking"
      ? "Interviewer is speaking…"
      : phase === "listening"
        ? "Listening…"
        : phase === "thinking"
          ? "Got it — thinking about your answer…"
          : "";

  return (
    <div className="page">
      <ColdStart active={phase === "loading" || phase === "thinking"} />

      {error ? <div className="alert alert-error">{error}</div> : null}

      {phase === "unavailable" && (
        <section className="card">
          <h2>This interview cannot start</h2>
          <p>{error || "This interview is not ready yet. The recruiter still needs to confirm the questions."}</p>
        </section>
      )}

      {phase === "device-check" && (
        <section className="card">
          <h2>Check your camera and microphone</h2>
          <p>
            Only your audio is recorded and transcribed. The video stays in the browser so you can frame
            yourself. It is not uploaded. After you begin, the interviewer listens on its own.
          </p>
          <div className="stage">
            {hasVideo ? (
              <video ref={attachPreview} className="camera" autoPlay playsInline muted />
            ) : (
              <div className="stage-placeholder">Camera preview appears when the check finishes.</div>
            )}
          </div>
          {cameraNote ? <p className="muted">{cameraNote}</p> : null}
          <div className="meter" aria-hidden="true">
            <span style={{ width: `${level}%` }} />
          </div>
          <p className="muted">
            {calibrated
              ? "Room noise is measured. Begin when you are ready."
              : "Listening to the room for a moment so silence is judged fairly."}
          </p>
          <button type="button" className="btn btn-primary" onClick={beginInterview} disabled={!calibrated}>
            Begin interview
          </button>
          {!session?.is_mock ? (
            <p className="fallback-row">
              <Link className="text-link" to="/candidate#practice">
                Want to warm up first?
              </Link>
            </p>
          ) : null}
        </section>
      )}

      {inConversation && (
        <section className="card question-stage">
          {question ? (
            <>
              <p className="progress">{question.progress_label || `Question ${question.sequence_number}`}</p>
              <h2 className="question-text">{question.question_text}</h2>
            </>
          ) : null}
          <p className="status-line" role="status" aria-live="polite">
            {phase === "listening" ? <span className="rec-dot" aria-hidden="true" /> : null}
            {phase === "thinking" ? <span className="spinner" aria-hidden="true" /> : null}
            {statusText}
          </p>
          {phase === "listening" && (
            <>
              <div className="meter" aria-label="Microphone level">
                <span style={{ width: `${level}%` }} />
              </div>
              {countdown ? (
                <p className="countdown" role="status">
                  Moving on in {countdown}…
                </p>
              ) : null}
            </>
          )}
          {playbackBlocked ? (
            <p className="warn">
              The browser held the audio.{" "}
              <button type="button" className="text-button" onClick={hearQuestion}>
                Hear the question
              </button>
            </p>
          ) : null}
          {phase === "mic-error" ? (
            <button type="button" className="btn btn-primary" onClick={() => move("device-check")}>
              Check microphone again
            </button>
          ) : null}
          {hasVideo ? (
            <div className="stage">
              <video ref={attachPreview} className="camera" autoPlay playsInline muted />
            </div>
          ) : null}
        </section>
      )}

      {phase === "goodbye" && (
        <section className="card">
          <Link className="btn btn-primary" to="/candidate">
            Go back
          </Link>
        </section>
      )}
    </div>
  );
}
