import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import WikiEditButton from "../WikiEditButton";

describe("WikiEditButton", () => {
  it("renders nothing without gitRemoteUrl", () => {
    const { container } = render(<WikiEditButton />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing without exportPath", () => {
    const { container } = render(<WikiEditButton gitRemoteUrl="https://github.com/org/repo.git" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders link with correct URL", () => {
    render(
      <WikiEditButton
        gitRemoteUrl="https://github.com/org/repo.git"
        branch="main"
        exportPath="docs/wiki/auth.md"
      />,
    );
    const link = screen.getByText(/edit on git/i).closest("a");
    expect(link).toHaveAttribute("href", "https://github.com/org/repo/blob/main/docs/wiki/auth.md");
  });

  it("handles git@ URLs", () => {
    render(
      <WikiEditButton
        gitRemoteUrl="git@github.com:org/repo.git"
        branch="dev"
        exportPath="auth.md"
      />,
    );
    const link = screen.getByText(/edit on git/i).closest("a");
    expect(link).toHaveAttribute("href", "https://github.com/org/repo/blob/dev/auth.md");
  });
});
