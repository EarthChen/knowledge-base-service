import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../../hooks/useWikiTour", () => ({
  useWikiTour: vi.fn(),
}));

import WikiGuidedTour from "../WikiGuidedTour";
import { useWikiTour } from "../../../hooks/useWikiTour";

describe("WikiGuidedTour", () => {
  it("renders tour steps grouped by layer", () => {
    (useWikiTour as ReturnType<typeof vi.fn>).mockReturnValue({
      data: {
        total_pages: 3,
        steps: [
          {
            order: 1,
            layer_name: "api",
            layer_display: "API 入口层",
            pages: [
              {
                path: "api/ctrl.md",
                title: "Controller",
                reading_order: 1,
                architecture_layer: "api",
              },
            ],
          },
          {
            order: 2,
            layer_name: "service",
            layer_display: "业务服务层",
            pages: [
              {
                path: "svc/svc.md",
                title: "Service",
                reading_order: 2,
                architecture_layer: "service",
              },
            ],
          },
        ],
      },
      isLoading: false,
    });
    render(<WikiGuidedTour businessId="test" currentPath="" />);
    expect(screen.getByText("API 入口层")).toBeTruthy();
    expect(screen.getByText("业务服务层")).toBeTruthy();
    expect(screen.getByText("Controller")).toBeTruthy();
  });

  it("shows loading state", () => {
    (useWikiTour as ReturnType<typeof vi.fn>).mockReturnValue({ data: null, isLoading: true });
    render(<WikiGuidedTour businessId="test" currentPath="" />);
    expect(screen.getByTestId("tour-loading")).toBeTruthy();
  });

  it("highlights current page", () => {
    (useWikiTour as ReturnType<typeof vi.fn>).mockReturnValue({
      data: {
        total_pages: 1,
        steps: [
          {
            order: 1,
            layer_name: "api",
            layer_display: "API",
            pages: [
              {
                path: "api/ctrl.md",
                title: "Controller",
                reading_order: 1,
                architecture_layer: "api",
              },
            ],
          },
        ],
      },
      isLoading: false,
    });
    render(<WikiGuidedTour businessId="test" currentPath="api/ctrl.md" />);
    const current = screen.getByText("Controller").closest("[data-current]");
    expect(current?.getAttribute("data-current")).toBe("true");
  });
});
