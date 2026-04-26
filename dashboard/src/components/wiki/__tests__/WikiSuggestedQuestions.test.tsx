import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WikiSuggestedQuestions from "../WikiSuggestedQuestions";

describe("WikiSuggestedQuestions", () => {
  it("renders nothing with empty questions", () => {
    const { container } = render(<WikiSuggestedQuestions questions={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows questions after expanding", async () => {
    const user = userEvent.setup();
    render(<WikiSuggestedQuestions questions={["Q1?", "Q2?"]} />);
    await user.click(screen.getByRole("button", { name: /explore further/i }));
    expect(screen.getByText("Q1?")).toBeInTheDocument();
    expect(screen.getByText("Q2?")).toBeInTheDocument();
  });

  it("calls onAskQuestion when clicked", async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    render(<WikiSuggestedQuestions questions={["Q1?"]} onAskQuestion={handler} />);
    await user.click(screen.getByRole("button", { name: /explore further/i }));
    await user.click(screen.getByRole("button", { name: "Q1?" }));
    expect(handler).toHaveBeenCalledWith("Q1?");
  });
});
