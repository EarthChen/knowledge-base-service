import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../../hooks/useWikiTour", () => ({
  useWikiTour: vi.fn(),
}));

import WikiGuidedTour from "../WikiGuidedTour";
import { useWikiTour } from "../../../hooks/useWikiTour";
import { TestI18nProvider } from "../../../i18n/context";

const tourData = {
  total_pages: 3,
  steps: [
    {
      order: 1,
      layer_name: "api",
      layer_display: "API Entry Layer",
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
      layer_display: "Business Service Layer",
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
};

function renderTour(locale: "en" | "zh" = "en", currentPath = "") {
  return render(
    <TestI18nProvider locale={locale}>
      <WikiGuidedTour businessId="test" currentPath={currentPath} />
    </TestI18nProvider>,
  );
}

describe("WikiGuidedTour", () => {
  it("renders tour steps grouped by layer (English)", () => {
    (useWikiTour as ReturnType<typeof vi.fn>).mockReturnValue({
      data: tourData,
      isLoading: false,
    });
    renderTour("en");
    expect(screen.getByText("API Entry Layer")).toBeTruthy();
    expect(screen.getByText("Business Service Layer")).toBeTruthy();
    expect(screen.getByText("Controller")).toBeTruthy();
  });

  it("renders tour steps grouped by layer (Chinese)", () => {
    (useWikiTour as ReturnType<typeof vi.fn>).mockReturnValue({
      data: tourData,
      isLoading: false,
    });
    renderTour("zh");
    expect(screen.getByText("API 入口层")).toBeTruthy();
    expect(screen.getByText("业务服务层")).toBeTruthy();
  });

  it("shows loading state", () => {
    (useWikiTour as ReturnType<typeof vi.fn>).mockReturnValue({ data: null, isLoading: true });
    renderTour();
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
            layer_display: "API Entry Layer",
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
    renderTour("en", "api/ctrl.md");
    const current = screen.getByText("Controller").closest("[data-current]");
    expect(current?.getAttribute("data-current")).toBe("true");
  });
});
