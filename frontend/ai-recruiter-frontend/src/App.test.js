import { fireEvent, render, screen, within } from "@testing-library/react";
import axios from "axios";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import HomePage from "./pages/HomePage";

beforeEach(() => {
  axios.get.mockResolvedValue({ data: [] });
  axios.post.mockResolvedValue({ data: {} });
});

test("opens on the landing page, then the recruiter and candidate tabs", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: /standardize your interviews and save time/i })).toBeInTheDocument();
  expect(screen.getByText(/scores every answer against a clear rubric/i)).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /how it works/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /create an interview/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /take it or practice/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /review the report/i })).toBeInTheDocument();
  const nav = screen.getByRole("navigation", { name: "Primary" });
  const tabs = within(nav).getAllByRole("link");
  expect(tabs.map((tab) => tab.textContent)).toEqual(["Recruiter", "Candidate"]);
  expect(tabs[0]).not.toHaveAttribute("aria-current");
  expect(screen.queryByRole("heading", { name: /^interviews$/i })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("link", { name: /get started/i }));
  expect(screen.getByRole("heading", { name: /^interviews$/i })).toBeInTheDocument();
  expect(within(screen.getByRole("navigation", { name: "Primary" })).getByRole("link", { name: "Recruiter" })).toHaveAttribute("aria-current", "page");
  expect(screen.queryByRole("link", { name: "Interview" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Candidates" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/role family/i)).not.toBeInTheDocument();
  expect(document.querySelector('input[type="file"]')).toBeNull();
  const create = screen.getByRole("button", { name: /create interview/i });
  expect(create).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/job description/i), { target: { value: "Build APIs" } });
  expect(create).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/^resume$/i), { target: { value: "Jane Doe" } });
  expect(create).toBeEnabled();

  fireEvent.click(screen.getByRole("link", { name: "AI Recruiter" }));
  expect(screen.getByRole("heading", { name: /standardize your interviews and save time/i })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: /go to candidate/i }));
  expect(screen.getByRole("heading", { name: /take an interview or practice/i })).toBeInTheDocument();
  expect(within(screen.getByRole("navigation", { name: "Primary" })).getByRole("link", { name: "Candidate" })).toHaveAttribute("aria-current", "page");
});

test("candidate tab stacks the interview link and expands practice", () => {
  render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>
  );
  expect(screen.getByRole("heading", { name: /take an interview or practice/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /start an interview/i })).toBeInTheDocument();
  expect(screen.queryByLabelText(/^role$/i)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/job description/i)).not.toBeInTheDocument();
  const open = screen.getByRole("button", { name: /^start$/i });
  expect(open).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/your name/i), { target: { value: "Ada" } });
  expect(open).toBeDisabled();
  fireEvent.click(screen.getByRole("link", { name: /do you want to practice first\? click here\./i }));
  const start = screen.getByRole("button", { name: /start practice/i });
  expect(start).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/job description/i), { target: { value: "Build APIs" } });
  expect(start).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/^resume$/i), { target: { value: "Jane Doe" } });
  expect(start).toBeEnabled();
});
