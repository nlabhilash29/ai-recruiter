import { useState } from "react";
import { BrowserRouter, Link, Route, Routes, useLocation } from "react-router-dom";
import { prefersReducedMotion } from "./api";
import { MissingApiNotice } from "./components/ColdStart";
import IntroAnimation from "./components/IntroAnimation";
import ParticlesBackground from "./ParticlesBackground";
import HomePage from "./pages/HomePage";
import InterviewPage from "./pages/InterviewPage";
import LandingPage from "./pages/LandingPage";
import PracticeResultsPage from "./pages/PracticeResultsPage";
import RecruiterPage from "./pages/RecruiterPage";
import ReportPage from "./pages/ReportPage";

function Shell({ variant, children }) {
  const location = useLocation();
  const recruiterOn = location.pathname === "/recruiter" || location.pathname.startsWith("/recruiter/");
  const candidateOn = location.pathname.startsWith("/candidate");
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          AI Recruiter
        </Link>
        {variant === "app" && (
          <nav className="nav" aria-label="Primary">
            <Link to="/recruiter" aria-current={recruiterOn ? "page" : undefined}>
              Recruiter
            </Link>
            <Link to="/candidate" aria-current={candidateOn ? "page" : undefined}>
              Candidate
            </Link>
          </nav>
        )}
        <a
          className="github-link"
          href="https://github.com/nlabhilash29/ai-recruiter"
          target="_blank"
          rel="noopener noreferrer"
        >
          <img
            src="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png"
            alt="GitHub repository"
          />
        </a>
      </header>
      <main>{children}</main>
    </div>
  );
}

export default function App() {
  const path = window.location.pathname;
  const skipIntro =
    process.env.NODE_ENV === "test" ||
    prefersReducedMotion() ||
    path === "/" ||
    path.startsWith("/recruiter") ||
    path.startsWith("/interview");
  const [showIntro, setShowIntro] = useState(!skipIntro);

  return (
    <>
      <MissingApiNotice />
      {showIntro ? (
        <IntroAnimation onComplete={() => setShowIntro(false)} />
      ) : (
        <BrowserRouter>
          <ParticlesBackground />
          <Routes>
            <Route
              path="/"
              element={
                <Shell variant="app">
                  <LandingPage />
                </Shell>
              }
            />
            <Route
              path="/recruiter"
              element={
                <Shell variant="app">
                  <RecruiterPage />
                </Shell>
              }
            />
            <Route
              path="/candidate"
              element={
                <Shell variant="app">
                  <HomePage />
                </Shell>
              }
            />
            <Route
              path="/recruiter/interviews/:id"
              element={
                <Shell variant="app">
                  <ReportPage />
                </Shell>
              }
            />
            <Route
              path="/interview/:id"
              element={
                <Shell variant="candidate">
                  <InterviewPage />
                </Shell>
              }
            />
            <Route
              path="/interview/:id/results"
              element={
                <Shell variant="candidate">
                  <PracticeResultsPage />
                </Shell>
              }
            />
          </Routes>
        </BrowserRouter>
      )}
    </>
  );
}
