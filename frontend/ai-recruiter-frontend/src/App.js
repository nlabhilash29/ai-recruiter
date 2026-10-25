import { useState } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { prefersReducedMotion } from "./api";
import ColdStart from "./components/ColdStart";
import IntroAnimation from "./components/IntroAnimation";
import ParticlesBackground from "./ParticlesBackground";
import HomePage from "./pages/HomePage";
import InterviewPage from "./pages/InterviewPage";
import PracticeResultsPage from "./pages/PracticeResultsPage";
import RecruiterPage from "./pages/RecruiterPage";
import ReportPage from "./pages/ReportPage";

function Shell({ variant, children }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        {variant === "candidate" ? (
          <span className="brand">AI Recruiter</span>
        ) : (
          <Link className="brand" to="/">
            AI Recruiter
          </Link>
        )}
        {variant === "app" && (
          <nav className="nav" aria-label="Primary">
            <Link to="/">Practice</Link>
            <Link to="/recruiter">Recruiter</Link>
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
  const skipIntro = process.env.NODE_ENV === "test" || prefersReducedMotion();
  const [showIntro, setShowIntro] = useState(!skipIntro);

  return (
    <>
      <ColdStart />
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
                  <HomePage />
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
