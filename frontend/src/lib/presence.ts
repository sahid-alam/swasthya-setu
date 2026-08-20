import { api, getToken } from "./api";

export type PresenceRow = {
  doctor_id: string;
  doctor_name: string;
  badge_id: string;
  department: string;
  hospital: string;
  state: string;
  confidence: number;
  zone_code: string | null;
  since: string;
  evidence: {
    candidates?: Record<string, number>;
    contributors?: {
      source: string;
      state: string;
      zone_code: string | null;
      score: number;
      age_seconds: number;
    }[];
    roster_state?: string | null;
    degraded_to_roster?: boolean;
    manual_override?: boolean;
    top_score?: number;
  };
};

export const fetchPresence = () => api<PresenceRow[]>("/presence");

export type Transition = {
  at: string;
  from_state: string;
  to_state: string;
  confidence: number;
  evidence: PresenceRow["evidence"];
};

export const fetchTransitions = (doctorId: string) =>
  api<Transition[]>(`/presence/${doctorId}/transitions?limit=8`);

export const STATE_LABEL: Record<string, string> = {
  PRESENT_IN_DEPT: "In department",
  PRESENT_ELSEWHERE: "Elsewhere on site",
  ON_ROUNDS: "On rounds",
  IN_SURGERY: "In surgery",
  ON_LEAVE: "On leave",
  OFF_SHIFT: "Off shift",
  UNKNOWN: "Unknown",
};

/** Admin-only scenario triggers — the presenter's remote control (PRD §M4). */
export async function trigger(path: string, body: unknown) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

export const isStaff = () => Boolean(getToken());
