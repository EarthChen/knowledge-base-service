import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SettingsToggle from "../SettingsToggle";

describe("SettingsToggle", () => {
  it("renders label and checkbox", () => {
    const onChange = vi.fn();
    render(
      <SettingsToggle label="Feature flag" checked={false} onChange={onChange} />,
    );

    expect(screen.getByText("Feature flag")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /feature flag/i })).not.toBeChecked();
  });

  it("calls onChange when toggled", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SettingsToggle label="Toggle me" checked={false} onChange={onChange} />);

    await user.click(screen.getByRole("checkbox", { name: /toggle me/i }));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("shows source badge", () => {
    render(<SettingsToggle label="With source" checked onChange={vi.fn()} source="db" />);
    expect(screen.getByText("db")).toBeInTheDocument();
  });
});
