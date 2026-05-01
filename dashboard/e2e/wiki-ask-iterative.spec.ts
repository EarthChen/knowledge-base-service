import { test } from "@playwright/test";

test.describe("Wiki Ask Iterative RAG", () => {
  test.skip("should show RAG timeline when iterative mode enabled", async () => {
    // Requires running backend with WIKI__ITERATIVE_RAG_ENABLED=true
    // and a seeded repository. Placeholder for CI pipeline integration.
  });

  test.skip("should display confidence score in answer", async () => {
    // Placeholder
  });
});
