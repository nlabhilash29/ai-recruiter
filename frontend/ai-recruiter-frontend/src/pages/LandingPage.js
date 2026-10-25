import { Link } from "react-router-dom";

const STEPS = [
  {
    who: "Recruiter",
    title: "Create an interview",
    body: "Paste the JD and resume. AI writes 5 questions tailored to the role and resume.",
  },
  {
    who: "Candidate",
    title: "Take it or practice",
    body: "Open the interview link and answer out loud. The interviewer moves on when you finish, or practice first with your own JD and resume.",
  },
  {
    who: "Recruiter",
    title: "Review the report",
    body: "Scores on problem solving, communication, role knowledge, ownership and collaboration, with feedback on every answer.",
  },
];

export default function LandingPage() {
  return (
    <div className="page landing">
      <section className="landing-hero">
        <h1>Standardize your interviews and save time</h1>
        <p className="lede">
          An AI recruiter that runs role-specific voice interviews and scores every answer against a clear rubric.
        </p>
        <Link className="btn btn-primary" to="/recruiter">
          Get Started
        </Link>
        <p className="landing-note">
          Have an interview link?{" "}
          <Link className="plain-link" to="/candidate">
            Go to Candidate
          </Link>
        </p>
      </section>
      <section className="landing-how" aria-labelledby="how-it-works">
        <h2 id="how-it-works">How it works</h2>
        <ol className="landing-steps">
          {STEPS.map((step, index) => (
            <li className="card" key={step.title}>
              <span className="step-index">{index + 1}</span>
              <p className="step-who">{step.who}</p>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
