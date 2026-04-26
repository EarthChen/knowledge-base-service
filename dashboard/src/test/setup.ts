import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./mocks/server";

const storage: Record<string, string> = {};

const localStorageMock: Storage = {
  getItem: (key: string) => (key in storage ? storage[key] : null),
  setItem: (key: string, value: string) => {
    storage[key] = value;
  },
  removeItem: (key: string) => {
    delete storage[key];
  },
  clear: () => {
    for (const k of Object.keys(storage)) delete storage[k];
  },
  key: (index: number) => Object.keys(storage)[index] ?? null,
  get length() {
    return Object.keys(storage).length;
  },
};

Object.defineProperty(globalThis, "localStorage", {
  value: localStorageMock,
  writable: true,
});

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  localStorageMock.clear();
});

afterAll(() => {
  server.close();
});
