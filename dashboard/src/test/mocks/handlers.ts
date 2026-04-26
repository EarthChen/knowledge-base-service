import { http, HttpResponse } from "msw";
import type { SettingsResponse } from "../../hooks/settingsTypes";

/** Minimal valid settings payload; panels merge missing keys client-side. */
export const mockSettingsResponse: SettingsResponse = {
  categories: {},
};

/** Default handlers; extend per test with server.use(...). */
export const handlers = [
  http.get("/api/health", () => HttpResponse.json({ ok: true })),
  http.get("/api/v1/settings", () => HttpResponse.json(mockSettingsResponse)),
  http.put("/api/v1/settings", async () =>
    HttpResponse.json({ status: "ok", updated: "1" }),
  ),
  http.post("/api/v1/settings/test-connection", async () =>
    HttpResponse.json({
      status: "ok",
      target: "falkordb",
      message: "ok",
    }),
  ),
];
