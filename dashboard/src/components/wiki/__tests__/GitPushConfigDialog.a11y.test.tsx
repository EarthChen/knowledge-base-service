import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import GitPushConfigDialog from "../GitPushConfigDialog";
import { renderWithI18n } from "../../../test/renderWithI18n";

describe("GitPushConfigDialog a11y", () => {
  it("exposes role=dialog, aria-modal, and aria-labelledby to the title", () => {
    renderWithI18n(
      <GitPushConfigDialog open onClose={vi.fn()} onConfirm={vi.fn()} />,
    );
    const dialog = screen.getByRole("dialog", { name: /git push configuration/i });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const title = screen.getByText(/git/i, { selector: "h3" });
    const titleId = title.getAttribute("id");
    expect(titleId).toBeTruthy();
    expect(dialog).toHaveAttribute("aria-labelledby", titleId);
  });
});
