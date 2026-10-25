import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders the interview tab as two choices", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: /^interview$/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /i have an interview link/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /practice first/i })).toBeInTheDocument();
  expect(
    screen.getByText("Try a 5-question sample interview to get comfortable. It isn't shared with anyone.")
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Recruiter" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Practice" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/role family/i)).not.toBeInTheDocument();
});
