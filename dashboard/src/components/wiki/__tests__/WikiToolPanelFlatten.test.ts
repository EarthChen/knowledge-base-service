import { describe, it, expect } from "vitest";
import { flattenDomainTree } from "../WikiToolPanel";
import type { TopicTreeNode } from "../../../hooks/useWikiDomainTree";

describe("flattenDomainTree", () => {
  it("flattens nested tree with children IDs", () => {
    const tree: TopicTreeNode[] = [
      {
        name: "auth",
        page_type: "domain_overview",
        path: "/wiki/auth",
        module_count: 5,
        architecture_layers: { api: 2, service: 3 },
        children: [
          {
            name: "auth-login",
            page_type: "topic",
            path: "/wiki/auth/login",
            module_count: 2,
            children: [],
          },
        ],
      },
      {
        name: "data",
        page_type: "domain_overview",
        path: "/wiki/data",
        children: [],
      },
    ];

    const result = flattenDomainTree(tree);
    expect(result).toHaveLength(3); // auth, auth-login, data
    expect(result[0]).toEqual({
      id: "auth",
      label: "auth",
      children: ["auth-login"],
      moduleCount: 5,
      architectureLayers: { api: 2, service: 3 },
    });
    expect(result[1]).toEqual({
      id: "auth-login",
      label: "auth-login",
      children: [],
      moduleCount: 2,
      architectureLayers: undefined,
    });
  });

  it("returns empty array for empty tree", () => {
    expect(flattenDomainTree([])).toEqual([]);
  });
});
