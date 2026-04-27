import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import HighlightText from "./HighlightText";

describe("HighlightText", () => {
  it("wraps each keyword in a mark in result text", () => {
    const { container } = render(
      <HighlightText text="The quick brown Fox jumps" query="quick fox" />,
    );
    const marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(2);
    expect(marks[0].textContent).toBe("quick");
    expect(marks[1].textContent).toBe("Fox");
  });

  it("highlights CJK terms without breaking the query into single characters", () => {
    const { container } = render(
      <HighlightText text="文档：项目配置与部署说明" query="项目配置" />,
    );
    const marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(1);
    expect(marks[0].textContent).toBe("项目配置");
  });

  it("treats regex metacharacters in the query as literal matches", () => {
    const { container } = render(
      <HighlightText text="see (test)+ value" query="(test)+" />,
    );
    const marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(1);
    expect(marks[0].textContent).toBe("(test)+");
  });

  it("renders plain text when query is empty", () => {
    render(<HighlightText text="no highlights here" query="   " />);
    expect(screen.getByText("no highlights here", { exact: true })).toBeInTheDocument();
    expect(document.querySelector("mark")).toBeNull();
  });

  it("prefers longer term when a shorter term is a prefix", () => {
    const { container } = render(<HighlightText text="xabxyz" query="a ab" />);
    const markEl = container.querySelectorAll("mark");
    expect(markEl).toHaveLength(1);
    expect(markEl[0].textContent).toBe("ab");
  });
});
