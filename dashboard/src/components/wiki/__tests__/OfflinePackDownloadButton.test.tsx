import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OfflinePackDownloadButton } from "../OfflinePackDownloadButton";

describe("OfflinePackDownloadButton", () => {
  it("renders download button", () => {
    render(<OfflinePackDownloadButton repository="test-repo" businessId="b1" />);
    expect(screen.getByRole("button")).toBeInTheDocument();
    expect(screen.getByText(/download/i)).toBeInTheDocument();
  });
});
