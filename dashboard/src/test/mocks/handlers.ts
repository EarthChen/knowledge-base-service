import { http, HttpResponse } from "msw";

/** Default handlers; extend per test with server.use(...). */
export const handlers = [
  http.get("/api/health", () => HttpResponse.json({ ok: true })),
];
