import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WikiTierSelector } from "../WikiTierSelector";

describe("WikiTierSelector", () => {
  it("renders combobox with options", () => {
    render(<WikiTierSelector value={null} onChange={() => {}} />);
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("calls onChange with selected value", () => {
    const onChange = vi.fn();
    render(<WikiTierSelector value={null} onChange={onChange} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "standard" } });
    expect(onChange).toHaveBeenCalledWith("standard");
  });

  it("calls onChange with null for empty value", () => {
    const onChange = vi.fn();
    render(<WikiTierSelector value="standard" onChange={onChange} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
