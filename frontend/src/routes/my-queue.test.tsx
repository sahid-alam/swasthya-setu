import { describe, expect, it } from "vitest";

import { queueState, type QueueEntry } from "./MyQueue";

const base: QueueEntry = {
  appointment_id: "a1",
  doctor_name: "Dr Sharma",
  hospital: "IGMC Shimla",
  scheduled_for: "2026-08-21T09:00:00Z",
  token_number: 14,
  position: 3,
  predicted_wait_minutes: 25,
  status: "BOOKED",
};

describe("queueState", () => {
  it("waits when the backend gives a position", () => {
    expect(queueState(base)).toBe("waiting");
  });

  it("is the patient's turn once the backend nulls the position", () => {
    // starts_at has passed, so position and wait come back null together —
    // the screen must never render "you are number null".
    expect(
      queueState({ ...base, position: null, predicted_wait_minutes: null }),
    ).toBe("now");
  });

  it("shows a reschedule as being moved, not as a place in line", () => {
    expect(queueState({ ...base, status: "RESCHEDULE_PENDING" })).toBe(
      "moving",
    );
  });

  it("keeps a checked-in patient in the queue", () => {
    expect(queueState({ ...base, status: "CHECKED_IN" })).toBe("waiting");
  });

  it("prefers the reschedule notice over the front of the queue", () => {
    expect(
      queueState({ ...base, status: "RESCHEDULE_PENDING", position: null }),
    ).toBe("moving");
  });
});
