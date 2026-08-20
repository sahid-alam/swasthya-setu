/* The presenter's remote control (signal-simulator SKILL.md).

   These call the same public endpoints simulators/scenario.py calls, from the browser
   — the panel is just another external client. Nothing here writes to the database or
   reaches into a service, because a scenario button that cheated would make the whole
   demo a lie. */

import { api } from "./api";

export type SimDoctor = {
  doctor_id: string;
  name: string;
  badge_id: string;
  hospital_code: string;
  department: string;
  face_enrolled: boolean;
};
export type SimZone = {
  code: string;
  kind: string;
  hospital_code: string;
  department: string | null;
};
export type Roster = { doctors: SimDoctor[]; zones: SimZone[] };

export const fetchRoster = () => api<Roster>("/simulation/roster");

const signal = (
  badge_id: string,
  source: string,
  zone_code: string | null,
  raw = {},
) =>
  api("/signals", {
    method: "POST",
    body: JSON.stringify({ source, badge_id, zone_code, raw }),
  });

const zoneFor = (roster: Roster, doc: SimDoctor, kind: string) => {
  const inHospital = roster.zones.filter(
    (z) => z.hospital_code === doc.hospital_code,
  );
  return (
    inHospital.find((z) => z.kind === kind && z.department === doc.department)
      ?.code ??
    inHospital.find((z) => z.kind === kind)?.code ??
    null
  );
};

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export type Scenario = {
  id: string;
  label: string;
  blurb: string;
  danger?: boolean;
  run: (roster: Roster, doc: SimDoctor) => Promise<string>;
};

export const SCENARIOS: Scenario[] = [
  {
    id: "arrives",
    label: "Doctor arrives",
    blurb:
      "Gate tap, then badge pings in their own OPD. Watch the row turn green.",
    async run(roster, doc) {
      await signal(doc.badge_id, "RFID", zoneFor(roster, doc, "GATE"));
      await wait(400);
      await signal(doc.badge_id, "BLE", zoneFor(roster, doc, "OPD"), {
        rssi: -62,
      });
      await wait(400);
      await signal(doc.badge_id, "BLE", zoneFor(roster, doc, "OPD"), {
        rssi: -58,
      });
      return `${doc.name} arrived`;
    },
  },
  {
    id: "walk_to_surgery",
    label: "Walk to surgery",
    blurb:
      "OPD pings, then the theatre-door reader. One high-trust tap flips it.",
    async run(roster, doc) {
      await signal(doc.badge_id, "BLE", zoneFor(roster, doc, "OPD"), {
        rssi: -64,
      });
      await wait(400);
      await signal(doc.badge_id, "RFID", zoneFor(roster, doc, "OT"), {
        reader: "ot-door",
      });
      return `${doc.name} is in theatre`;
    },
  },
  {
    id: "beacon_dead",
    label: "Beacon battery dies",
    blurb:
      "One last ping, then silence. Confidence decays to a labelled roster guess.",
    async run(roster, doc) {
      await signal(doc.badge_id, "BLE", zoneFor(roster, doc, "OPD"), {
        rssi: -61,
        battery: "low",
      });
      return `${doc.name}'s beacon has gone quiet — watch it decay`;
    },
  },
  {
    id: "doctor_absent",
    label: "Calls in sick",
    danger: true,
    blurb: "Admin override. The clinic list is redistributed automatically.",
    async run(_roster, doc) {
      await api(`/presence/${doc.doctor_id}/override`, {
        method: "POST",
        body: JSON.stringify({
          state: "ON_LEAVE",
          reason: "Called in sick (scenario panel)",
        }),
      });
      return `${doc.name} marked on leave — replan fired`;
    },
  },
  {
    id: "stale_roster",
    label: "Roster is wrong",
    blurb: "HMIS says on leave; the badge says otherwise. Presence wins.",
    async run(roster, doc) {
      await api("/roster/shift", {
        method: "PUT",
        body: JSON.stringify({ badge_id: doc.badge_id, kind: "LEAVE" }),
      });
      await wait(300);
      await signal(doc.badge_id, "BLE", zoneFor(roster, doc, "OPD"), {
        rssi: -60,
      });
      await wait(300);
      await signal(doc.badge_id, "BLE", zoneFor(roster, doc, "OPD"), {
        rssi: -57,
      });
      return `Roster says leave; ${doc.name} is in the building`;
    },
  },
];
