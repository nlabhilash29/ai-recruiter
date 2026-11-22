import { render, screen } from "@testing-library/react";
import ResultsView from "./ResultsView";

const rubric = {
  dimensions: [
    { id: "problem_solving", label: "Problem solving", weight: 30, descriptor: "How they frame problems." },
    { id: "ownership", label: "Ownership", weight: 20, descriptor: "What they personally delivered." },
  ],
};

test("an interview with no assessable answers says Not assessed, never 0.0", () => {
  render(
    <ResultsView
      report={{
        candidate: { name: "Sam Silent" },
        job_description: { title: "Customer Success Manager" },
        interview_summary: { overall_recommendation: "Not enough evidence to recommend yet" },
        scoring: {
          overall_score: null,
          technical_score: null,
          communication_score: null,
          cultural_fit_score: null,
          dimension_scores: { problem_solving: null, ownership: null },
          rubric,
          legacy: false,
        },
        questions: [],
      }}
    />
  );
  expect(screen.queryByText("0.0")).not.toBeInTheDocument();
  expect(screen.queryByText("/10")).not.toBeInTheDocument();
  expect(screen.getAllByText("Not assessed").length).toBeGreaterThanOrEqual(3);
});

test("a scored interview still shows the number out of 10", () => {
  render(
    <ResultsView
      report={{
        scoring: {
          overall_score: 7.46,
          dimension_scores: { problem_solving: 8, ownership: 7 },
          rubric,
          legacy: false,
        },
        questions: [],
      }}
    />
  );
  expect(screen.getByText("7.5")).toBeInTheDocument();
  expect(screen.getByText("8.0/10")).toBeInTheDocument();
});
