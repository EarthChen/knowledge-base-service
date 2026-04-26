import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import WikiEditButton from "../WikiEditButton";
import { renderWithI18n } from "../../../test/renderWithI18n";

describe("WikiEditButton", () => {
  it("renders nothing without gitRemoteUrl", () => {
    const { container } = renderWithI18n(<WikiEditButton />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing without exportPath", () => {
    const { container } = renderWithI18n(<WikiEditButton gitRemoteUrl="https://github.com/org/repo.git" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders link with correct URL", () => {
    renderWithI18n(
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
    renderWithI18n(
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
