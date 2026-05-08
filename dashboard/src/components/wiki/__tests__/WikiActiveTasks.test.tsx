import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { WikiAsyncTask } from "../../../api/types";
import WikiActiveTasks from "../WikiActiveTasks";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { ToastProvider } from "../../Toast";

const toastSpy = vi.hoisted(() => vi.fn());
const apiMocks = vi.hoisted(() => ({
  tasks: [] as WikiAsyncTask[],
  cancelMock: vi.fn(),
}));

const listActiveWikiTasksMock = vi.hoisted(() =>
  vi.fn(async () => ({ tasks: [...apiMocks.tasks] })),
);

vi.mock("../../Toast", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../Toast")>();
  return {
    ...mod,
    useToast: () => ({ toast: toastSpy }),
  };
});

vi.mock("../../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/client")>();
  return {
    ...actual,
    listActiveWikiTasks: () => listActiveWikiTasksMock(),
    cancelWikiTask: (id: string) => apiMocks.cancelMock(id),
  };
});

describe("WikiActiveTasks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.tasks = [];
    apiMocks.cancelMock.mockResolvedValue(undefined);
    listActiveWikiTasksMock.mockImplementation(async () => ({
      tasks: [...apiMocks.tasks],
    }));
  });

  function renderTasks(businessId = "biz-one") {
    return renderWithI18n(
      <ToastProvider>
        <WikiActiveTasks businessId={businessId} />
      </ToastProvider>,
    );
  }

  it("renders nothing when there are no active tasks", async () => {
    renderTasks();
    await waitFor(() => expect(listActiveWikiTasksMock).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText(/Indexing in progress/i)).not.toBeInTheDocument());
  });

  it("renders task card when a relevant running task exists", async () => {
    apiMocks.tasks = [
      {
        task_id: "task-abcd-full-id-xxxx",
        status: "running",
        business_id: "biz-one",
        current_repo: "acme/repo",
        progress_pct: 35,
      },
    ];
    renderTasks("biz-one");
    await screen.findByText(/Indexing in progress/i);
    expect(screen.getByText(/task-abcd-full-/i)).toBeInTheDocument();
    expect(screen.getByText(/acme\/repo/i)).toBeInTheDocument();
  });

  it("shows progress bar with aria-valuenow when progress_pct > 0", async () => {
    apiMocks.tasks = [
      {
        task_id: "tid-progress",
        status: "running",
        business_id: "biz-one",
        progress_pct: 42,
        current_repo: "r1",
      },
    ];
    renderTasks();
    const bar = await screen.findByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "42");
  });

  it("shows localized phase label for known pipeline phase keys", async () => {
    apiMocks.tasks = [
      {
        task_id: "tid-phase",
        status: "running",
        business_id: "biz-one",
        progress_pct: 0,
        phase: "leaf_compose",
      },
    ];
    renderTasks();
    expect(await screen.findByText(/Composing leaf pages/i)).toBeInTheDocument();
  });

  it("confirming cancel invokes cancelWikiTask", async () => {
    apiMocks.tasks = [
      {
        task_id: "tid-cancel-me",
        status: "running",
        business_id: "biz-one",
        progress_pct: 5,
      },
    ];
    const user = userEvent.setup();
    renderTasks();
    await screen.findByText(/Indexing in progress/i);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: /yes, cancel/i }));
    await waitFor(() => expect(apiMocks.cancelMock).toHaveBeenCalledWith("tid-cancel-me"));
    expect(toastSpy).toHaveBeenCalledWith("success", expect.any(String));
  });
});
