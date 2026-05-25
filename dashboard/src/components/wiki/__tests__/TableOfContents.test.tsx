import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import TableOfContents from "../TableOfContents";
import { renderWithI18n } from "../../../test/renderWithI18n";

describe("TableOfContents", () => {
  it("renders heading links from markdown content", () => {
    renderWithI18n(
      <TableOfContents content={"# Intro\n\n## Details\n\nParagraph"} />,
    );
    expect(screen.getByRole("button", { name: "Intro" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Details" })).toBeInTheDocument();
  });
});
