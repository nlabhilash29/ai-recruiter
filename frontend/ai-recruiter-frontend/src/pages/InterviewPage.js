import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import axios from "axios";
import Webcam from "react-webcam";
import { API_URL, candidateLink, friendlyError } from "../api";
import CopyButton from "../components/CopyButton";
import { calibrateThreshold, createVadController, levelPercent, MAX_ANSWER_MS } from "../vad";

const MAX_UPLOAD_BYTES = 4.5 * 1024 * 1024;
const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";

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
  const [previewStream, setPreviewStream] = useState(null);

  const previewRef = useRef(null);
  const previewStreamRef = useRef(null);
  const audioContextRef = useRef(null);
  const playerRef = useRef(null);
  const recorderRef = useRef(null);
  const recordStreamRef = useRef(null);
  const chunksRef = useRef([]);
  const vadRef = useRef(null);
  const listenTimerRef = useRef(0);
  const thresholdRef = useRef(0.03);
  const phaseRef = useRef(phase);
  const turnRef = useRef(0);
  const mimeRef = useRef("");
  const closingRef = useRef(false);

  function move(next) {
    phaseRef.current = next;
    setPhase(next);
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await axios.get(`${API_URL}/interview/${id}/session`, { timeout: 90000 });
        if (cancelled) return;
        setSession(response.data);
        if (response.data.status === "completed") move("complete");
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
    const video = previewRef.current;
    if (!video || !previewStream) return undefined;
    video.srcObject = previewStream;
    video.play().catch(() => {
      setCameraNote("The camera preview could not start. You can still continue, because only audio is used.");
    });
    return undefined;
  }, [previewStream, hasVideo]);

  useEffect(() => {
    return () => {
      window.clearInterval(listenTimerRef.current);
      previewStreamRef.current?.getTracks().forEach((track) => track.stop());
      recordStreamRef.current?.getTracks().forEach((track) => track.stop());
      if (audioContextRef.current) audioContextRef.current.close();
      if (playerRef.current) {
        playerRef.current.pause();
        playerRef.current.src = "";
      }
    };
  }, []);

  function stopPreview() {
    previewStreamRef.current?.getTracks().forEach((track) => track.stop());
    previewStreamRef.current = null;
    setPreviewStream(null);
  }

  async function ensureContext() {
    if (!audioContextRef.current || audioContextRef.current.state === "closed") {
      audioContextRef.current = new AudioContext();
    }
    if (audioContextRef.current.state === "suspended") await audioContextRef.current.resume();
    return audioContextRef.current;
  }

  useEffect(() => {
    if (phase !== "device-check") return undefined;
    let cancelled = false;
    let timer = 0;
    async function calibrate() {
      setError("");
      setCameraNote("");
      setCalibrated(false);
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
      } catch (requestError) {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          if (!cancelled) {
            setCameraNote("The camera is unavailable. You can still continue, because only audio is used.");
          }
        } catch (audioError) {
          if (!cancelled) {
            setError("The microphone is blocked. Allow microphone access in the browser, then try again.");
          }
          return;
        }
      }
      if (cancelled) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      previewStreamRef.current = stream;
      setHasVideo(stream.getVideoTracks().length > 0);
      setPreviewStream(stream);
      const context = await ensureContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      context.createMediaStreamSource(stream).connect(analyser);
      const buffer = new Uint8Array(analyser.fftSize);
      const samples = [];
      const started = Date.now();
      timer = window.setInterval(() => {
        const value = rmsFrom(analyser, buffer);
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
      cancelled = true;
      window.clearInterval(timer);
      stopPreview();
    };
  }, [phase]);

  function armPlayer() {
    const audio = playerRef.current || new Audio();
    playerRef.current = audio;
    audio.setAttribute("playsinline", "true");
    if (!audio.src) audio.src = SILENT_WAV;
    const pending = audio.play();
    if (pending && pending.catch) pending.catch(() => {});
    return audio;
  }

  function playUrl(url) {
    const audio = armPlayer();
    setPlaybackBlocked(false);
    move("speaking");
    return new Promise((resolve) => {
      const finish = (blocked) => {
        audio.onended = null;
        audio.onerror = null;
        resolve(!blocked);
      };
      audio.onended = () => finish(false);
      audio.onerror = () => finish(false);
      audio.src = url;
      const pending = audio.play();
      if (pending && pending.catch) {
        pending.catch(() => {
          setPlaybackBlocked(true);
          finish(true);
        });
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
    const stream = recordStreamRef.current;
    return new Promise((resolve) => {
      const finish = () => {
        stream?.getTracks().forEach((track) => track.stop());
        recordStreamRef.current = null;
        recorderRef.current = null;
        const blob = new Blob(chunksRef.current, { type: mimeRef.current || "audio/webm" });
        resolve(blob);
      };
      if (!recorder || recorder.state === "inactive") {
        finish();
        return;
      }
      recorder.onstop = finish;
      recorder.stop();
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
    const url = URL.createObjectURL(new Blob([response.data], { type: "audio/mpeg" }));
    const played = await playUrl(url);
    URL.revokeObjectURL(url);
    if (!played) return;
    if (status === "completed" || next.data.status === "completed" || !next.data.current_question) {
      move("complete");
      return;
    }
    await startListening();
  }

  async function startListening() {
    if (playerRef.current && !playerRef.current.paused && !playerRef.current.ended) return;
    const turn = turnRef.current + 1;
    turnRef.current = turn;
    setError("");
    setCountdown(null);
    move("listening");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (turnRef.current !== turn) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      recordStreamRef.current = stream;
      const mime = chooseMime();
      mimeRef.current = mime;
      const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      chunksRef.current = [];
      let bytes = 0;
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size) {
          chunksRef.current.push(event.data);
          bytes += event.data.size;
        }
      };
      recorderRef.current = recorder;
      recorder.start(250);
      const context = await ensureContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      const source = context.createMediaStreamSource(stream);
      source.connect(analyser);
      const buffer = new Uint8Array(analyser.fftSize);
      const started = Date.now();
      if (!vadRef.current) vadRef.current = createVadController({ threshold: thresholdRef.current });
      window.clearInterval(listenTimerRef.current);
      listenTimerRef.current = window.setInterval(() => {
        if (turnRef.current !== turn || phaseRef.current !== "listening") return;
        if (playerRef.current && !playerRef.current.paused && !playerRef.current.ended) return;
        const value = rmsFrom(analyser, buffer);
        setLevel(levelPercent(value));
        const decision = vadRef.current.step(value, Date.now());
        setCountdown(decision.countdown);
        if (bytes > MAX_UPLOAD_BYTES || Date.now() - started >= MAX_ANSWER_MS) {
          closeTurn("max");
          return;
        }
        if (decision.event === "silence" || decision.event === "max") closeTurn("answer");
        else if (decision.event === "reprompt") closeTurn("reprompt");
        else if (decision.event === "no-speech") closeTurn("no-speech");
      }, 100);
    } catch (requestError) {
      setError("The microphone is blocked. Allow microphone access, then use Begin interview again.");
      move("device-check");
    }
  }

  async function closeTurn(reason) {
    if (closingRef.current) return;
    closingRef.current = true;
    const turn = turnRef.current;
    turnRef.current += 1;
    window.clearInterval(listenTimerRef.current);
    const heardSpeech = Boolean(vadRef.current && vadRef.current.speechStarted);
    const blob = await stopRecorder();
    try {
      if (turnRef.current !== turn + 1) return;
      if (reason === "reprompt") {
        vadRef.current?.markReprompted();
        const played = await speakCurrent();
        if (played) await startListening();
        return;
      }
      if (reason === "no-speech" || (reason === "manual" && !heardSpeech)) {
        vadRef.current = createVadController({ threshold: thresholdRef.current });
        await uploadAnswer(null, true);
        return;
      }
      if (!blob || blob.size < 400) {
        vadRef.current = createVadController({ threshold: thresholdRef.current });
        await uploadAnswer(null, true);
        return;
      }
      vadRef.current = createVadController({ threshold: thresholdRef.current });
      await uploadAnswer(blob, false);
    } catch (requestError) {
      const message = friendlyError(requestError, "Your answer could not be submitted. Please try again.");
      if (/already completed/i.test(message)) {
        move("complete");
        return;
      }
      setError(message);
      move("listening");
      await startListening();
    } finally {
      closingRef.current = false;
    }
  }

  async function beginInterview() {
    setError("");
    armPlayer();
    move("speaking");
    stopPreview();
    vadRef.current = createVadController({ threshold: thresholdRef.current });
    try {
      const played = await speakCurrent();
      if (played) await startListening();
    } catch (requestError) {
      setError(friendlyError(requestError, "The question audio could not be played."));
      move("device-check");
    }
  }

  async function hearQuestion() {
    try {
      const played = await speakCurrent();
      if (played && phaseRef.current !== "complete") await startListening();
    } catch (requestError) {
      setError(friendlyError(requestError, "The question audio could not be played."));
    }
  }

  async function replayQuestion() {
    turnRef.current += 1;
    window.clearInterval(listenTimerRef.current);
    await stopRecorder();
    vadRef.current?.restart();
    setCountdown(null);
    try {
      const played = await speakCurrent();
      if (played) await startListening();
    } catch (requestError) {
      setError(friendlyError(requestError, "The question audio could not be played."));
    }
  }

  const link = candidateLink(id);
  const question = session?.current_question;
  const inConversation = phase === "speaking" || phase === "listening" || phase === "thinking";
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
      <div className="interview-top">
        <div>
          <p className="eyebrow">{session?.job_title || "Interview"}</p>
          <h1>{session?.is_mock ? "Practice interview" : "Interview"}</h1>
        </div>
        <div className="id-row">
          <CopyButton text={link} label="Copy link" />
        </div>
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}

      {phase === "loading" && <p className="card">Opening the interview…</p>}

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
              <video ref={previewRef} className="camera" autoPlay playsInline muted />
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
              <Link className="text-link" to="/#practice">
                Want to warm up first?
              </Link>
            </p>
          ) : null}
        </section>
      )}

      {inConversation && question && (
        <section className="card question-stage">
          <p className="progress">{question.progress_label || `Question ${question.sequence_number}`}</p>
          <h2 className="question-text">{question.question_text}</h2>
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
              ) : (
                <p className="muted">Speak naturally. A short pause ends the answer.</p>
              )}
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
          <div className="stage">
            <Webcam audio={false} mirrored className="camera" videoConstraints={{ facingMode: "user" }} />
          </div>
          <p className="muted">Video is only for framing. It is not recorded.</p>
          {phase === "listening" && (
            <p className="fallback-row">
              <button type="button" className="text-button" onClick={replayQuestion}>
                Replay question
              </button>
              <button type="button" className="text-button" onClick={() => closeTurn("manual")}>
                I'm done answering
              </button>
            </p>
          )}
        </section>
      )}

      {phase === "complete" && (
        <section className="card">
          <h2>Interview complete</h2>
          <p>Thank you. Your answers were recorded.</p>
          <Link className="btn btn-primary" to={`/interview/${id}/results`}>
            See the results
          </Link>
        </section>
      )}
    </div>
  );
}
