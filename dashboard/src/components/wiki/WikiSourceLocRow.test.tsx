import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import WikiSourceLocRow from "./WikiSourceLocRow";
import { renderWithI18n } from "../../test/renderWithI18n";
import type { WikiSourceLocation } from "../../hooks/wikiTypes";

describe("WikiSourceLocRow", () => {
  it("renders file path and line range for one location", () => {
    const loc: WikiSourceLocation = {
      fqn: "com.example.C",
      file_path: "src/a.ts",
      start_line: 10,
      end_line: 20,
      repository: "repo-1",
    };
    renderWithI18n(<WikiSourceLocRow repository="repo-1" sourceLocations={[loc]} />);
    expect(screen.getByText(/src\/a\.ts:10–20/)).toBeInTheDocument();
  });
});
