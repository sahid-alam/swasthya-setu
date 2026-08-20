import "@testing-library/jest-dom/vitest";

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
