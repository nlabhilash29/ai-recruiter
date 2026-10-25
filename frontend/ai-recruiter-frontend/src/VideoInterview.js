import React, { useState, useRef } from 'react';
import Webcam from 'react-webcam';
import axios from 'axios';
import './VideoInterview.css';
import { API_URL, apiErrorMessage, decodeAssistantText } from './api';

function VideoInterview() {
  const [isRecording, setIsRecording] = useState(false);
  const [interviewId, setInterviewId] = useState('');
  const [isValidated, setIsValidated] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [currentQuestion, setCurrentQuestion] = useState(0); // 0 for intro
  const [isInterviewComplete, setIsInterviewComplete] = useState(false);
  const [error, setError] = useState(null);
  const [totalQuestions, setTotalQuestions] = useState(5);
  const [promptText, setPromptText] = useState('Please introduce yourself. Your recording is not scored.');
  const webcamRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);

  // Validate interview ID
  const validateInterviewId = async () => {
    if (!interviewId.trim()) {
      setError('Please enter an Interview ID');
      return;
    }

    setIsValidating(true);
    setError(null);

    try {
      const response = await axios.get(
        `${API_URL}/interview/validate/${interviewId.trim()}`
      );

      if (response.data.valid) {
        setIsValidated(true);
        setError(null);
        setTotalQuestions(response.data.total_questions || 5);
        setCurrentQuestion(response.data.current_question || 0);
        if ((response.data.current_question || 0) > 0) {
          setPromptText('Continue the interview. Record your answer to the current question.');
        }
      } else {
        setError(response.data.message || 'Invalid Interview ID');
        setIsValidated(false);
      }
    } catch (error) {
      console.error('Validation error:', error.response || error);
      
      const errorMessage = error.response?.status === 404
        ? 'Interview ID not found'
        : apiErrorMessage(error, 'Error validating Interview ID');
      setError(errorMessage);
      setIsValidated(false);
    } finally {
      setIsValidating(false);
    }
  };

  const uploadRecording = async (blob) => {
    const extension = blob.type.includes('mp4') ? 'mp4' : blob.type.includes('wav') ? 'wav' : 'webm';
    const formData = new FormData();
    formData.append('file', blob, `answer.${extension}`);
    formData.append('interview_id', interviewId);

    const response = await axios.post(
      `${API_URL}/talk-video`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        responseType: 'arraybuffer'
      }
    );

    const interviewStatus = response.headers['x-interview-status'];
    const current = parseInt(response.headers['x-current-question'] || response.headers['x-answered-questions'] || '0', 10);
    const totalQs = parseInt(response.headers['x-total-questions'] || '5', 10);
    const assistantText = decodeAssistantText(response.headers['x-assistant-text']);

    setTotalQuestions(totalQs);
    setCurrentQuestion(Number.isNaN(current) ? 0 : current);
    if (assistantText) {
      setPromptText(assistantText);
    }
    if (interviewStatus === 'completed') {
      setIsInterviewComplete(true);
    }

    const contentType = (response.headers['content-type'] || 'audio/mpeg').split(';')[0];
    const audioBlob = new Blob([response.data], { type: contentType });
    const audioUrl = URL.createObjectURL(audioBlob);
    const audio = new Audio(audioUrl);
    audio.onended = () => URL.revokeObjectURL(audioUrl);
    try {
      await audio.play();
    } catch (playError) {
      console.error('Audio playback failed:', playError);
    }
  };

  const startRecording = async () => {
    setError(null);
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      setError('This browser cannot record audio. Try a current version of Chrome, Edge, or Firefox.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferred = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
      const mimeType = preferred.find((type) => MediaRecorder.isTypeSupported(type)) || '';
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        try {
          await uploadRecording(blob);
        } catch (error) {
          console.error('Recording error:', error.response || error);
          setError('Error processing response: ' + apiErrorMessage(error, 'Request failed'));
        }
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
    } catch (error) {
      console.error('Microphone error:', error);
      setError('Microphone access is required to record an answer.');
    }
  };

  const stopRecording = () => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop();
    }
    setIsRecording(false);
  };

  // Get question number display
  const getQuestionText = () => {
    if (currentQuestion === 0) {
      return "Please introduce yourself";
    } else if (!isInterviewComplete) {
      return `Question ${currentQuestion} of ${totalQuestions}`;
    } else {
      return "Interview Complete";
    }
  };

  return (
    <div className="video-interview">
      <h2>Video Interview</h2>

      {/* Interview ID Validation Section */}
      {!isValidated && (
        <div className="validation-section">
          <div className="input-group">
            <label>Interview ID:</label>
            <input
              type="text"
              value={interviewId}
              onChange={(e) => {
                setInterviewId(e.target.value);
                setError(null);
              }}
              placeholder="Enter Interview ID"
              disabled={isValidating}
              className={error ? 'error' : ''}
            />
          </div>
          {error && (
            <div className="error-message">
              {error}
              {error === 'Interview ID not found' && (
                <p className="error-help">Please check if the ID was copied correctly</p>
              )}
            </div>
          )}
          <button
            onClick={validateInterviewId}
            disabled={isValidating || !interviewId.trim()}
            className="validate-button"
          >
            {isValidating ? 'Validating...' : 'Start Interview'}
          </button>
        </div>
      )}

      {/* Video Interview Section - Only show after validation */}
      {isValidated && (
        <>
          <div className="interview-status">
            <h3>{getQuestionText()}</h3>
            {promptText && <p className="prompt-text">{promptText}</p>}
            {error && <div className="error-message">{error}</div>}
          </div>

          <div className="video-section">
            <Webcam
              ref={webcamRef}
              audio={false}
              width={640}
              height={480}
              screenshotFormat="image/jpeg"
            />
          </div>

          {!isInterviewComplete && (
            <div className="audio-section">
              <div className="controls">
                <button 
                  onClick={startRecording} 
                  disabled={isRecording || isInterviewComplete}
                  className="record-button"
                >
                  Start Recording
                </button>
                <button 
                  onClick={stopRecording} 
                  disabled={!isRecording || isInterviewComplete}
                  className="stop-button"
                >
                  Stop Recording
                </button>
              </div>
            </div>
          )}

          {isInterviewComplete && (
            <div className="completion-message">
              <h3>Thank you for completing the interview!</h3>
              <p>Your responses have been recorded. The recruiter will review them shortly.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default VideoInterview;