import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithI18n } from "../../../../test/renderWithI18n";
import MoveDialog from "../MoveDialog";
import CreateSubdomainDialog from "../CreateSubdomainDialog";
import RenameDialog from "../RenameDialog";
import DeleteDialog from "../DeleteDialog";
import MergeDialog from "../MergeDialog";

const treeData = [
  { uid: "root", title: "Root", children: [{ uid: "child", title: "Child" }] },
];

function expectDialogA11y(titlePattern: RegExp) {
  const dialog = screen.getByRole("dialog", { name: titlePattern });
  expect(dialog).toHaveAttribute("aria-modal", "true");
  const title = screen.getByText(titlePattern, { selector: "h3" });
  const titleId = title.getAttribute("id");
  expect(titleId).toBeTruthy();
  expect(dialog).toHaveAttribute("aria-labelledby", titleId);
  return dialog;
}

describe("wiki domain dialog a11y", () => {
  it("MoveDialog exposes dialog ARIA and closes on Escape", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(
      <MoveDialog currentUid="x" treeData={treeData} onConfirm={vi.fn()} onCancel={onCancel} />,
    );
    expectDialogA11y(/move domain/i);
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("CreateSubdomainDialog exposes dialog ARIA and closes on Escape", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(<CreateSubdomainDialog onConfirm={vi.fn()} onCancel={onCancel} />);
    expectDialogA11y(/create subdomain/i);
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("RenameDialog exposes dialog ARIA and closes on Escape", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(
      <RenameDialog currentTitle="Old Name" onConfirm={vi.fn()} onCancel={onCancel} />,
    );
    expectDialogA11y(/rename domain/i);
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("DeleteDialog exposes dialog ARIA and closes on Escape", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(
      <DeleteDialog domainTitle="My Domain" onConfirm={vi.fn()} onCancel={onCancel} />,
    );
    expectDialogA11y(/delete domain/i);
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("MergeDialog exposes dialog ARIA and closes on Escape", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(
      <MergeDialog
        sourceUid="src"
        sourceTitle="Source"
        treeData={treeData}
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    expectDialogA11y(/merge domain/i);
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("RenameDialog associates labels with inputs", () => {
    renderWithI18n(
      <RenameDialog currentTitle="Old Name" onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    const nameLabel = screen.getByText(/domain name/i, { selector: "label" });
    const descLabel = screen.getByText(/^description$/i, { selector: "label" });
    expect(nameLabel).toHaveAttribute("for");
    expect(descLabel).toHaveAttribute("for");
    const nameInput = document.getElementById(nameLabel.getAttribute("for")!);
    const descInput = document.getElementById(descLabel.getAttribute("for")!);
    expect(nameInput).toBeInstanceOf(HTMLInputElement);
    expect(descInput).toBeInstanceOf(HTMLTextAreaElement);
  });

  it("CreateSubdomainDialog associates labels with inputs", () => {
    renderWithI18n(<CreateSubdomainDialog onConfirm={vi.fn()} onCancel={vi.fn()} />);
    const nameLabel = screen.getByText(/domain name/i, { selector: "label" });
    const descLabel = screen.getByText(/^description$/i, { selector: "label" });
    expect(nameLabel.getAttribute("for")).toBeTruthy();
    expect(descLabel.getAttribute("for")).toBeTruthy();
    expect(document.getElementById(nameLabel.getAttribute("for")!)).toBeInstanceOf(HTMLInputElement);
    expect(document.getElementById(descLabel.getAttribute("for")!)).toBeInstanceOf(HTMLTextAreaElement);
  });

  it("DeleteDialog groups delete options in fieldset with legend", () => {
    renderWithI18n(
      <DeleteDialog domainTitle="My Domain" onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    const fieldset = screen.getByRole("group", { name: /delete options/i });
    expect(fieldset.tagName).toBe("FIELDSET");
    expect(fieldset.querySelector("legend")).toHaveTextContent(/delete options/i);
  });
});
