import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import EntityCardsPanel from "../EntityCardsPanel";
import { renderWithI18n } from "../../../test/renderWithI18n";

vi.mock("../../../hooks/useWikiEntities", () => ({
  useWikiEntities: () => ({
    data: {
      entities: [
        {
          name: "AuthService",
          entity_type: "class",
          file_path: "auth/service.py",
          repository: "demo",
          start_line: 10,
          signature: "class AuthService",
        },
      ],
    },
    isLoading: false,
    error: null,
  }),
}));

describe("EntityCardsPanel", () => {
  it("renders related entity cards when expanded", async () => {
    const user = userEvent.setup();
    renderWithI18n(<EntityCardsPanel businessId="default" pagePath="/auth" />);
    await user.click(screen.getByRole("button"));
    expect(screen.getByText("AuthService")).toBeInTheDocument();
  });
});
