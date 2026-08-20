import { beforeEach, describe, expect, it } from "vitest";

import { enqueue, flush, pending, remove } from "./outbox";

const intent = {
  patient_id: "p1",
  slot_id: "s1",
  channel: "PWA",
  label: "Dr. X",
};

const ok = () => new Response(null, { status: 201 });
const conflict = () => new Response(null, { status: 409 });
const serverError = () => new Response(null, { status: 503 });

describe("offline booking outbox", () => {
  beforeEach(() => localStorage.clear());

  it("keeps a booking made with no connection", () => {
    enqueue(intent);
    expect(pending()).toHaveLength(1);
    expect(pending()[0].intent_id).toBeTruthy();
  });

  it("drains what the server accepts", async () => {
    enqueue(intent);
    enqueue({ ...intent, slot_id: "s2" });
    const { sent } = await flush(async () => ok());
    expect(sent).toBe(2);
    expect(pending()).toHaveLength(0);
  });

  it("drops a booking whose slot went while we were offline, and says which", async () => {
    // never silently book a taken slot — ARCHITECTURE §Offline strategy
    enqueue(intent);
    const { sent, rejected } = await flush(async () => conflict());
    expect(sent).toBe(0);
    expect(rejected).toHaveLength(1);
    expect(pending()).toHaveLength(0);
  });

  it("keeps a booking queued when the server is having a bad day", async () => {
    enqueue(intent);
    const { sent } = await flush(async () => serverError());
    expect(sent).toBe(0);
    expect(pending()).toHaveLength(1);
  });

  it("stops on a network error rather than spinning through the queue", async () => {
    enqueue(intent);
    enqueue({ ...intent, slot_id: "s2" });
    await flush(async () => {
      throw new TypeError("Failed to fetch");
    });
    expect(pending()).toHaveLength(2);
  });

  it("survives corrupt storage instead of bricking booking", () => {
    localStorage.setItem("setu.outbox", "{not json");
    expect(pending()).toEqual([]);
  });

  it("removes a single intent by id", () => {
    const a = enqueue(intent);
    enqueue({ ...intent, slot_id: "s2" });
    remove(a.intent_id);
    expect(pending()).toHaveLength(1);
  });
});
