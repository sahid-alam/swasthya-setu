import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

/* Tests run against a known env, never the developer's. CLAUDE.md already applies
   this rule to the backend (conftest forces every *_MOCK_MODE true); the frontend
   needs it too, because vite.config.ts sets envDir to the repo root, so filling in
   VITE_VAPI_* in .env for a live demo would otherwise flip VoiceCall's branch and
   fail the suite by configuration rather than by code. Vars are read at module
   scope, and setupFiles run before test modules import — so stub here, not in a
   test body. */
vi.stubEnv("VITE_VAPI_PUBLIC_KEY", "");
vi.stubEnv("VITE_VAPI_ASSISTANT_ID", "");

/* jsdom here does not provide localStorage, and the offline outbox is built on it.
   A Map-backed stand-in is enough: the outbox only ever gets, sets, removes and
   clears, and testing against the real thing would mean a browser runner. */
if (typeof globalThis.localStorage === "undefined") {
  const store = new Map<string, string>();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, String(v)),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
      key: (i: number) => [...store.keys()][i] ?? null,
      get length() {
        return store.size;
      },
    },
  });
}
