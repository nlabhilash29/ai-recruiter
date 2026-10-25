import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import axios from "axios";
import Webcam from "react-webcam";
import { API_URL, candidateLink, friendlyError } from "../api";
import CopyButton from "../components/CopyButton";

const RECORD_LIMIT_SECONDS = 165;
const RECORD_WARN_SECONDS = 150;
const MAX_UPLOAD_BYTES = 4.5 * 1024 * 1024;

function formatClock(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function chooseMime() {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return "";
  }
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function playAudio(url) {
  const audio = new Audio(url);
  return audio.play().then(
    () => true,
    () => false
  );
}

export default function InterviewPage() {
  const { id } = useParams();
  const [session, setSession] = useState(null);
  const [phase, setPhase] = useState("loading");
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [warnLimit, setWarnLimit] = useState(false);
  const [blob, setBlob] = useState(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [tooBig, setTooBig] = useState(false);
  const [playbackBlocked, setPlaybackBlocked] = useState(false);
  const [replayError, setReplayError] = useState("");
  const [micReady, setMicReady] = useState(false);
  const [hasVideo, setHasVideo] = useState(false);
  const [cameraNote, setCameraNote] = useState("");
  const [level, setLevel] = useState(0);
  const [previewStream, setPreviewStream] = useState(null);

  const previewRef = useRef(null);
  const previewStreamRef = useRef(null);
  const audioContextRef = useRef(null);
  const recorderRef = useRef(null);
  const recordStreamRef = useRef(null);
  const chunksRef = useRef([]);
  const submittingRef = useRef(false);
  const skipSpeakRef = useRef(false);
  const levelFrameRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await axios.get(`${API_URL}/interview/${id}/session`, { timeout: 90000 });
        if (cancelled) return;
        setSession(response.data);
        if (response.data.status === "completed") setPhase("complete");
        else if (!response.data.ready) setPhase("unavailable");
        else setPhase("device-check");
      } catch (requestError) {
        if (cancelled) return;
        setError(friendlyError(requestError, "This interview could not be opened."));
        setPhase("unavailable");
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (!blob) {
      setPreviewUrl("");
      return undefined;
    }
    const url = URL.createObjectURL(blob);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [blob]);

  useEffect(() => {
    return () => {
      previewStreamRef.current?.getTracks().forEach((track) => track.stop());
      recordStreamRef.current?.getTracks().forEach((track) => track.stop());
      if (audioContextRef.current) audioContextRef.current.close();
      cancelAnimationFrame(levelFrameRef.current);
    };
  }, []);

  useEffect(() => {
    if (phase !== "recording") return undefined;
    const started = Date.now();
    const timer = window.setInterval(() => {
      const seconds = Math.floor((Date.now() - started) / 1000);
      setElapsed(seconds);
      if (seconds >= RECORD_WARN_SECONDS) setWarnLimit(true);
      if (seconds >= RECORD_LIMIT_SECONDS && recorderRef.current?.state === "recording") {
        recorderRef.current.stop();
      }
    }, 250);
    return () => window.clearInterval(timer);
  }, [phase]);

  const questionNumber = session?.current_question?.sequence_number;

  useEffect(() => {
    if (phase !== "question" || !questionNumber) return undefined;
    if (skipSpeakRef.current) {
      skipSpeakRef.current = false;
      return undefined;
    }
    let cancelled = false;
    async function speak() {
      try {
        const response = await axios.post(`${API_URL}/interview/${id}/speak`, undefined, {
          responseType: "arraybuffer",
          timeout: 90000,
        });
        if (cancelled) return;
        const url = URL.createObjectURL(new Blob([response.data], { type: "audio/mpeg" }));
        const played = await playAudio(url);
        if (!cancelled) setPlaybackBlocked(!played);
      } catch (requestError) {
        if (!cancelled) setReplayError(friendlyError(requestError, "The question audio could not be played."));
      }
    }
    speak();
    return () => {
      cancelled = true;
    };
  }, [phase, questionNumber, id]);

  useEffect(() => {
    const video = previewRef.current;
    if (!video || !previewStream) return undefined;
    video.srcObject = previewStream;
    video.play().catch(() => {
      setCameraNote("The camera preview could not start. You can still continue, because only audio is used.");
    });
    return undefined;
  }, [previewStream, hasVideo]);

  function stopPreview() {
    previewStreamRef.current?.getTracks().forEach((track) => track.stop());
    previewStreamRef.current = null;
    setPreviewStream(null);
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    cancelAnimationFrame(levelFrameRef.current);
  }

  async function checkDevices() {
    setError("");
    setCameraNote("");
    stopPreview();
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    } catch (requestError) {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        setCameraNote("The camera is unavailable. You can still continue, because only audio is used.");
      } catch (audioError) {
        setError("The microphone is blocked. Allow microphone access in the browser, then try the check again.");
        setMicReady(false);
        return;
      }
    }
    previewStreamRef.current = stream;
    const videoTracks = stream.getVideoTracks();
    setHasVideo(videoTracks.length > 0);
    setPreviewStream(stream);
    const context = new AudioContext();
    if (context.state === "suspended") await context.resume();
    audioContextRef.current = context;
    const analyser = context.createAnalyser();
    analyser.fftSize = 256;
    context.createMediaStreamSource(stream).connect(analyser);
    const samples = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteFrequencyData(samples);
      const average = samples.reduce((sum, value) => sum + value, 0) / samples.length;
      setLevel(Math.min(100, Math.round(average * 1.4)));
      levelFrameRef.current = requestAnimationFrame(tick);
    };
    tick();
    setMicReady(true);
  }

  function continueToQuestion() {
    stopPreview();
    setPhase("question");
  }

  function acceptRecording(nextBlob) {
    if (!nextBlob || nextBlob.size < 800) {
      setBlob(null);
      setTooBig(false);
      setError("That recording was too short. Please try again.");
      setPhase("question");
      return;
    }
    setBlob(nextBlob);
    const oversized = nextBlob.size > MAX_UPLOAD_BYTES;
    setTooBig(oversized);
    setError(oversized ? "That recording is too large to upload. Please re-record a shorter answer." : "");
    setPhase("review");
  }

  async function startRecording() {
    setError("");
    setReplayError("");
    setPlaybackBlocked(false);
    setWarnLimit(false);
    setElapsed(0);
    setBlob(null);
    setTooBig(false);
    stopPreview();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recordStreamRef.current = stream;
      const mime = chooseMime();
      const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const recorded = new Blob(chunksRef.current, { type: recorder.mimeType || mime || "audio/webm" });
        stream.getTracks().forEach((track) => track.stop());
        recordStreamRef.current = null;
        acceptRecording(recorded);
      };
      recorderRef.current = recorder;
      recorder.start(250);
      setPhase("recording");
    } catch (requestError) {
      setError("The microphone is blocked. Allow microphone access, then start again.");
      setPhase("question");
    }
  }

  function stopRecording() {
    if (recorderRef.current && recorderRef.current.state === "recording") {
      recorderRef.current.stop();
    }
  }

  function reRecord() {
    setBlob(null);
    setTooBig(false);
    setError("");
    startRecording();
  }

  async function refreshSession() {
    const response = await axios.get(`${API_URL}/interview/${id}/session`, { timeout: 90000 });
    setSession(response.data);
    return response.data;
  }

  async function submitAnswer() {
    if (!blob || tooBig || submittingRef.current) return;
    submittingRef.current = true;
    setPhase("processing");
    setError("");
    try {
      const form = new FormData();
      const extension = blob.type.includes("mp4") ? "m4a" : "webm";
      // Video from the webcam is not attached. Only this audio blob is uploaded.
      form.append("file", blob, `answer.${extension}`);
      form.append("interview_id", id);
      const response = await axios.post(`${API_URL}/talk-video`, form, {
        responseType: "arraybuffer",
        timeout: 120000,
      });
      const status = response.headers["x-interview-status"];
      const audioUrl = URL.createObjectURL(new Blob([response.data], { type: "audio/mpeg" }));
      const played = await playAudio(audioUrl);
      setPlaybackBlocked(!played);
      const next = await refreshSession();
      setBlob(null);
      if (status === "completed" || next.status === "completed" || !next.current_question) {
        setPhase("complete");
      } else {
        skipSpeakRef.current = true;
        setPhase("question");
      }
    } catch (requestError) {
      setError(friendlyError(requestError, "Your answer could not be submitted. Please try again."));
      setPhase("review");
    } finally {
      submittingRef.current = false;
    }
  }

  async function replayQuestion() {
    setReplayError("");
    try {
      const response = await axios.post(`${API_URL}/interview/${id}/speak`, undefined, {
        responseType: "arraybuffer",
        timeout: 90000,
      });
      const url = URL.createObjectURL(new Blob([response.data], { type: "audio/mpeg" }));
      const played = await playAudio(url);
      setPlaybackBlocked(!played);
      if (!played) {
        setReplayError("Your browser blocked playback. Allow sound for this site, then press Replay question again.");
      }
    } catch (requestError) {
      setReplayError(friendlyError(requestError, "The question audio could not be played."));
    }
  }

  const link = candidateLink(id);
  const question = session?.current_question;

  return (
    <div className="page">
      <div className="interview-top">
        <div>
          <p className="eyebrow">{session?.job_title || "Interview"}</p>
          <h1>{session?.is_mock ? "Practice interview" : "Video interview"}</h1>
        </div>
        <div className="id-row">
          <code>{id}</code>
          <CopyButton text={id} label="Copy ID" />
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
            yourself. It is not uploaded.
          </p>
          <div className="stage">
            {hasVideo ? (
              <video ref={previewRef} className="camera" autoPlay playsInline muted />
            ) : (
              <div className="stage-placeholder">Camera preview appears after the check.</div>
            )}
          </div>
          {cameraNote ? <p className="muted">{cameraNote}</p> : null}
          <div className="meter" aria-hidden="true">
            <span style={{ width: `${level}%` }} />
          </div>
          <p className="muted">{micReady ? "Speak to see the microphone level move." : "Microphone level appears after the check."}</p>
          <div className="controls">
            <button type="button" className="btn btn-secondary" onClick={checkDevices}>
              {micReady ? "Check again" : "Check camera and microphone"}
            </button>
            <button type="button" className="btn btn-primary" onClick={continueToQuestion} disabled={!micReady}>
              {session?.answered_questions ? "Continue interview" : "Start interview"}
            </button>
          </div>
        </section>
      )}

      {(phase === "question" || phase === "recording" || phase === "review" || phase === "processing") && question && (
        <section className="card question-stage">
          <p className="progress">
            Question {question.sequence_number} of {session.total_questions}
          </p>
          <h2 className="question-text">{question.question_text}</h2>
          <div className="controls">
            <button type="button" className="btn btn-secondary" onClick={replayQuestion} disabled={phase === "processing" || phase === "recording"}>
              Replay question
            </button>
          </div>
          {playbackBlocked ? (
            <p className="warn">Your browser blocked autoplay. Use Replay question to hear it.</p>
          ) : null}
          {replayError ? <p className="warn">{replayError}</p> : null}

          <div className="stage">
            <Webcam
              audio={false}
              mirrored
              className="camera"
              videoConstraints={{ facingMode: "user" }}
            />
          </div>
          <p className="muted">Video is only for framing. It is not recorded.</p>

          {phase === "recording" && (
            <div className="recording-status" role="status">
              <span className="rec-dot" aria-hidden="true" />
              <span>Recording {formatClock(elapsed)}</span>
            </div>
          )}
          {phase === "recording" && warnLimit && (
            <p className="warn" role="status">
              Recording will stop at {formatClock(RECORD_LIMIT_SECONDS)} so the audio stays under the 5 MB upload limit.
            </p>
          )}

          {phase === "processing" && (
            <div className="processing" role="status" aria-live="polite">
              <span className="spinner" aria-hidden="true" />
              <p>Transcribing and scoring your answer…</p>
            </div>
          )}

          {phase === "review" && previewUrl && (
            <div className="review">
              <h3>Review your answer</h3>
              <audio controls src={previewUrl} />
              <div className="controls">
                <button type="button" className="btn btn-primary" onClick={submitAnswer} disabled={tooBig}>
                  Submit answer
                </button>
                <button type="button" className="btn btn-secondary" onClick={reRecord}>
                  Re-record
                </button>
              </div>
            </div>
          )}

          <div className="controls">
            <button type="button" className="btn btn-primary" onClick={startRecording} disabled={phase !== "question"}>
              Start recording
            </button>
            <button type="button" className="btn btn-danger" onClick={stopRecording} disabled={phase !== "recording"}>
              Stop recording
            </button>
          </div>
        </section>
      )}

      {phase === "complete" && (
        <section className="card">
          <h2>Interview complete</h2>
          <p>Thank you. Your answers were recorded.</p>
          {session?.is_mock ? (
            <Link className="btn btn-primary" to={`/interview/${id}/results`}>
              See your feedback
            </Link>
          ) : (
            <p>The recruiter will review your interview. You can close this page.</p>
          )}
        </section>
      )}
    </div>
  );
}
