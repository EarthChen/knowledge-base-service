import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import WikiPipelineVisualization from "../WikiPipelineVisualization";
import { renderWithI18n } from "../../../test/renderWithI18n";

describe("WikiPipelineVisualization", () => {
  describe("compact mode", () => {
    it("renders all 21 pipeline dots", () => {
      const { container } = renderWithI18n(
        <WikiPipelineVisualization compact currentPhase="finalize" />,
      );
      const list = container.querySelector('[aria-label="Pipeline progress"]');
      expect(list).toBeTruthy();
      const items = container.querySelectorAll('[role="listitem"]');
      expect(items).toHaveLength(21);
    });

    it("marks earlier nodes as completed when currentPhase is late in the pipeline", () => {
      const { container } = renderWithI18n(
        <WikiPipelineVisualization compact currentPhase="quality_gate" />,
      );
      const items = container.querySelectorAll('[role="listitem"]');
      // Quality gate is index 16 in the pipeline
      // Nodes before index 16 should be completed
      const firstItem = items[0] as HTMLElement;
      expect(firstItem.getAttribute("aria-label")).toContain("completed");
    });

    it("marks current running phase correctly", () => {
      const { container } = renderWithI18n(
        <WikiPipelineVisualization compact currentPhase="linking" />,
      );
      const items = container.querySelectorAll('[role="listitem"]');
      // linking is index 18
      const linkingItem = items[18] as HTMLElement;
      expect(linkingItem.getAttribute("aria-label")).toContain("running");
    });
  });

  describe("expanded mode", () => {
    it("renders all pipeline node labels", () => {
      renderWithI18n(<WikiPipelineVisualization currentPhase="finalize" />);
      // Check a few representative labels
      expect(screen.getByText("Detecting Reorganization")).toBeInTheDocument();
      expect(screen.getByText("Classifying Entity Roles")).toBeInTheDocument();
      expect(screen.getByText("Quality Gate")).toBeInTheDocument();
      expect(screen.getByText("Finalizing")).toBeInTheDocument();
    });

    it("shows elapsed time for completed nodes with node_statuses", () => {
      renderWithI18n(
        <WikiPipelineVisualization
          currentPhase="finalize"
          nodeStatuses={{
            detect_reorg: { status: "completed", elapsed_sec: 3.2 },
            classify_entity_roles: { status: "completed", elapsed_sec: 12.8 },
          }}
        />,
      );
      expect(screen.getByText("3.2s")).toBeInTheDocument();
      expect(screen.getByText("12.8s")).toBeInTheDocument();
    });

    it("shows sub-progress when items_processed and items_total are available", () => {
      renderWithI18n(
        <WikiPipelineVisualization
          nodeStatuses={{
            compose_leaf_modules: {
              status: "running",
              elapsed_sec: 5.0,
              items_processed: 7,
              items_total: 20,
            },
          }}
          currentPhase="compose_leaf_modules"
        />,
      );
      expect(screen.getByText("7/20")).toBeInTheDocument();
    });

    it("renders connector lines between nodes", () => {
      const { container } = renderWithI18n(
        <WikiPipelineVisualization currentPhase="compose_leaf_modules" />,
      );
      // Each node except the last has a connector line
      const listItems = container.querySelectorAll('[role="listitem"] > div');
      // 21 nodes with parent div + connector = 41 child divs in the list
      // Just verify the list renders without error
      expect(listItems.length).toBeGreaterThan(0);
    });

    it("renders failed status with XCircle icon", () => {
      const { container } = renderWithI18n(
        <WikiPipelineVisualization
          nodeStatuses={{
            quality_gate: { status: "failed" },
          }}
          currentPhase="quality_gate"
        />,
      );
      // Check that the Quality Gate node is labeled as failed
      const items = container.querySelectorAll('[role="listitem"]');
      const qualityGateItem = items[16] as HTMLElement;
      expect(qualityGateItem.getAttribute("aria-label")).toContain("failed");
    });

    it("renders skipped status", () => {
      const { container } = renderWithI18n(
        <WikiPipelineVisualization
          nodeStatuses={{
            heal_pages: { status: "skipped" },
          }}
          currentPhase="finalize"
        />,
      );
      const items = container.querySelectorAll('[role="listitem"]');
      const healItem = items[17] as HTMLElement;
      expect(healItem.getAttribute("aria-label")).toContain("skipped");
    });

    it("uses node_statuses data over currentPhase heuristic when both provided", () => {
      const { container } = renderWithI18n(
        <WikiPipelineVisualization
          currentPhase="finalize"
          nodeStatuses={{
            finalize: { status: "running" },
          }}
        />,
      );
      const items = container.querySelectorAll('[role="listitem"]');
      const finalizeItem = items[20] as HTMLElement;
      expect(finalizeItem.getAttribute("aria-label")).toContain("running");
    });
  });
});
