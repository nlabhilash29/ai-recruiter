import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders the practice interview page", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: /practice interview/i })).toBeInTheDocument();
});
