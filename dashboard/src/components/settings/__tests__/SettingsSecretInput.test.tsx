import type { ReactElement } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TestI18nProvider } from "../../../i18n/context";
import SettingsSecretInput from "../SettingsSecretInput";

function renderSecretInput(ui: ReactElement) {
  return render(<TestI18nProvider>{ui}</TestI18nProvider>);
}

describe("SettingsSecretInput", () => {
  it("renders with password type by default", () => {
    const onChange = vi.fn();
    renderSecretInput(
      <SettingsSecretInput label="API key" value="secret123" onChange={onChange} />,
    );

    expect(screen.getByText("API key")).toBeInTheDocument();
    const input = screen.getByDisplayValue("secret123");
    expect(input).toHaveAttribute("type", "password");
  });

  it("toggles visibility on eye icon click", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderSecretInput(<SettingsSecretInput label="Token" value="x" onChange={onChange} />);

    const input = screen.getByDisplayValue("x");
    expect(input).toHaveAttribute("type", "password");

    const toggle = screen.getByRole("button");
    await user.click(toggle);

    expect(input).toHaveAttribute("type", "text");

    await user.click(toggle);
    expect(input).toHaveAttribute("type", "password");
  });

  it("calls onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { container } = renderSecretInput(
      <SettingsSecretInput label="Secret" value="" onChange={onChange} />,
    );

    const input = container.querySelector("input");
    expect(input).not.toBeNull();
    await user.type(input!, "abc");
    expect(onChange).toHaveBeenCalled();
    const joined = onChange.mock.calls.map((c) => c[0]).join("");
    expect(joined).toBe("abc");
  });
});
