import { describe, it, expect, vi } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IndexingUploadPanel } from "../IndexingUploadPanel";
import { IndexingTaskList } from "../IndexingTaskList";
import { IndexingEnrichModal } from "../IndexingEnrichModal";
import { TestI18nProvider } from "../../../i18n/context";
import type { IndexTask } from "../../../api/types";

function wrap(ui: ReactNode) {
  return render(<TestI18nProvider>{ui}</TestI18nProvider>);
}

describe("IndexingUploadPanel", () => {
  it("renders upload drop zone", () => {
    wrap(
      <IndexingUploadPanel
        queuedFiles={[]}
        dragActive={false}
        uploadPhase="idle"
        uploadMessage={null}
        readProgress={{ done: 0, total: 0 }}
        noBusinessAvailable={false}
        isPending={false}
        onAddFiles={vi.fn()}
        onRemoveQueued={vi.fn()}
        onSubmit={vi.fn()}
        onDragActiveChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/drop files here/i)).toBeInTheDocument();
  });
});

describe("IndexingTaskList", () => {
  const task: IndexTask = {
    task_id: "t-1",
    status: "completed",
    mode: "full",
    directory: "/src",
    repository: "demo",
    created_at: "2026-01-01T00:00:00.000Z",
    progress: { phase: "completed", total_files: 1, processed_files: 1, stats: {} },
  };

  it("renders recent tasks", () => {
    wrap(
      <IndexingTaskList
        tasks={[task]}
        activeTaskId={null}
        onViewDetails={vi.fn()}
      />,
    );
    expect(screen.getByText(/recent tasks/i)).toBeInTheDocument();
    expect(screen.getByText(/demo/)).toBeInTheDocument();
  });
});

describe("IndexingEnrichModal", () => {
  it("associates enrich repository label with input", async () => {
    const user = userEvent.setup();
    wrap(
      <IndexingEnrichModal
        open
        repositories={[]}
        enrichRepository=""
        enrichForce={false}
        isPending={false}
        onRepositoryChange={vi.fn()}
        onForceChange={vi.fn()}
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/repository/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/repository/i), "my-repo");
  });
});
