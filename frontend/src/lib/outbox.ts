/* Offline booking outbox.

   PLAN.md says PouchDB. It is not used: without CouchDB replication (see the note in
   ARCHITECTURE D6) PouchDB is a ~150 KB document store with a vulnerable `uuid`
   dependency, doing what the few lines below do. The interface is deliberately the
   same shape, so swapping PouchDB back in means replacing this file and nothing else.

   ponytail: localStorage caps at ~5 MB. A booking intent is ~200 bytes, so that is
   thousands of pending bookings — far past the point where a patient has other
   problems. Move to IndexedDB if the outbox ever holds documents. */

export type Intent = {
  intent_id: string;
  patient_id: string;
  slot_id: string;
  channel: string;
  created_at: string;
  /** what to show the patient while it waits */
  label: string;
};

const KEY = "setu.outbox";

function read(): Intent[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return []; // corrupt storage must not brick booking
  }
}

function write(items: Intent[]) {
  localStorage.setItem(KEY, JSON.stringify(items));
}

export const pending = (): Intent[] => read();

export function enqueue(
  item: Omit<Intent, "intent_id" | "created_at">,
): Intent {
  const full: Intent = {
    ...item,
    intent_id: crypto.randomUUID(),
    created_at: new Date().toISOString(),
  };
  write([...read(), full]);
  return full;
}

export function remove(intentId: string) {
  write(read().filter((i) => i.intent_id !== intentId));
}

/** Replay the queue. Returns how many were accepted.
 *  A 409 means the slot went while we were offline — that intent is dropped rather
 *  than retried forever, and the caller tells the patient to pick again. */
export async function flush(
  send: (i: Intent) => Promise<Response>,
): Promise<{ sent: number; rejected: Intent[] }> {
  let sent = 0;
  const rejected: Intent[] = [];
  for (const item of read()) {
    try {
      const res = await send(item);
      if (res.ok) {
        remove(item.intent_id);
        sent += 1;
      } else if (res.status === 409 || res.status === 404) {
        remove(item.intent_id);
        rejected.push(item);
      }
      // anything else (5xx, network) stays queued for the next attempt
    } catch {
      break; // still offline; stop and keep the rest queued
    }
  }
  return { sent, rejected };
}
