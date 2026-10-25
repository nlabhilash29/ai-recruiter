import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders the interview tab with a practice section", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: /^interview$/i })).toBeInTheDocument();
  expect(
    screen.getByText("Want to warm up? Practice with a sample interview before the real one.")
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Recruiter" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Practice" })).not.toBeInTheDocument();
});
