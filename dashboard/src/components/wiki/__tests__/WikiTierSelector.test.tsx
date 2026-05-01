import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { WikiTierSelector } from "../WikiTierSelector";
import { renderWithI18n } from "../../../test/renderWithI18n";

describe("WikiTierSelector", () => {
  it("renders select with options", () => {
    renderWithI18n(<WikiTierSelector value={null} onChange={() => {}} />);
    expect(screen.getByLabelText("Wiki tier filter")).toBeInTheDocument();
  });

  it("calls onChange with selected value", () => {
    const onChange = vi.fn();
    renderWithI18n(<WikiTierSelector value={null} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Wiki tier filter"), { target: { value: "standard" } });
    expect(onChange).toHaveBeenCalledWith("standard");
  });

  it("calls onChange with null for empty value", () => {
    const onChange = vi.fn();
    renderWithI18n(<WikiTierSelector value="standard" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Wiki tier filter"), { target: { value: "" } });
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
