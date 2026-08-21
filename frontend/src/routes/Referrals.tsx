import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  Button,
  Cell,
  Chip,
  Eyebrow,
  Panel,
  REFERRAL_TONE,
  Row,
  StatusChip,
  TableShell,
} from "../components/ui";
import { fetchNetwork } from "../lib/command";
import {
  cancelReferral,
  confirmReferral,
  createReferral,
  fetchReferrals,
  searchPatients,
  timeLeft,
  type Referral,
} from "../lib/facilities";

/** Referral reservations — PRD §M5, DESIGN.md §9a.
 *
 *  The countdown is the point of the screen. A hold that silently expires while a
 *  receiving hospital keeps a bed marked RESERVED is the exact failure M5 exists to
 *  prevent, so the time remaining is on the row, ticking, and it turns warn as it runs
 *  out. The backend sweeper is what actually releases it — this only shows the truth. */

const URGENCY_TONE = {
  EMERGENCY: "danger",
  URGENT: "warn",
  ROUTINE: "neutral",
} as const;

function Countdown({ referral }: { referral: Referral }) {
  // One second is the honest resolution for something a bed depends on.
  const [, tick] = useState(0);
  useEffect(() => {
    if (referral.status !== "RESERVED") return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [referral.status]);

  if (referral.status !== "RESERVED")
    return <span className="text-muted-2">—</span>;
  const left = timeLeft(referral.expires_at);
  if (!left) {
    // Elapsed on screen but the sweeper has not run yet. Say that, rather than showing
    // a confident "RESERVED" for a bed that is already going back into the pool.
    return (
      <Chip tone="warn">
        <span className="live-state">releasing…</span>
      </Chip>
    );
  }
  const minutes =
    (new Date(referral.expires_at!).getTime() - Date.now()) / 60_000;
  return (
    <Chip tone={minutes < 30 ? "warn" : "info"}>
      <span className="live-state whitespace-nowrap">{left}</span>
    </Chip>
  );
}

const SPECIALTIES = [
  "General Surgery",
  "Orthopaedics",
  "General Medicine",
  "Paediatrics",
  "Obstetrics & Gynaecology",
];

/** Placing a referral. The runbook walks this on stage, so it lives on the screen
 *  rather than only in the API — a demo beat you can only perform with curl is not a
 *  demo beat. */
function PlaceReferral({ onPlaced }: { onPlaced: () => void }) {
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [patient, setPatient] = useState("");
  const [specialty, setSpecialty] = useState(SPECIALTIES[0]);
  const [urgency, setUrgency] = useState("EMERGENCY");
  const [error, setError] = useState("");

  const { data: facilities = [] } = useQuery({
    queryKey: ["network"],
    queryFn: fetchNetwork,
  });
  const { data: patients = [] } = useQuery({
    queryKey: ["patients-pick"],
    queryFn: () => searchPatients(""),
  });

  useEffect(() => {
    if (facilities.length < 2) return;
    // Default to the shape the runbook describes: a smaller facility sending upward.
    if (!from) setFrom(facilities[facilities.length - 1].hospital_id);
    if (!to) setTo(facilities[0].hospital_id);
  }, [facilities, from, to]);

  useEffect(() => {
    if (!patient && patients.length) setPatient(patients[0].id);
  }, [patients, patient]);

  const place = useMutation({
    mutationFn: () =>
      createReferral({
        from_hospital_id: from,
        to_hospital_id: to,
        patient_id: patient,
        specialty,
        urgency,
      }),
    onSuccess: () => {
      setError("");
      setOpen(false);
      onPlaced();
    },
    onError: (e: Error) => setError(e.message),
  });

  if (!open) {
    return (
      <Button variant="accent" size="lg" onClick={() => setOpen(true)}>
        Place a referral
      </Button>
    );
  }

  return (
    <Panel raised className="modal-in w-full p-4 sm:p-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5">
          <Eyebrow>From</Eyebrow>
          <select
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className="min-h-[40px] w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-[14px]"
          >
            {facilities.map((f) => (
              <option key={f.hospital_id} value={f.hospital_id}>
                {f.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <Eyebrow>To</Eyebrow>
          <select
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="min-h-[40px] w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-[14px]"
          >
            {facilities.map((f) => (
              <option key={f.hospital_id} value={f.hospital_id}>
                {f.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <Eyebrow>Patient</Eyebrow>
          <select
            value={patient}
            onChange={(e) => setPatient(e.target.value)}
            className="min-h-[40px] w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-[14px]"
          >
            {patients.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <Eyebrow>Specialty</Eyebrow>
          <select
            value={specialty}
            onChange={(e) => setSpecialty(e.target.value)}
            className="min-h-[40px] w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-[14px]"
          >
            {SPECIALTIES.map((sp) => (
              <option key={sp}>{sp}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <Eyebrow>Urgency</Eyebrow>
          <select
            value={urgency}
            onChange={(e) => setUrgency(e.target.value)}
            className="min-h-[40px] w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-[14px]"
          >
            {["EMERGENCY", "URGENT", "ROUTINE"].map((u) => (
              <option key={u}>{u}</option>
            ))}
          </select>
        </label>
      </div>

      {/* Trauma maps to an ICU bed, obstetrics to maternity — said out loud, because a
          wrong ward is not a cosmetic mistake. */}
      <p className="mt-3 text-[13px] text-muted">
        The destination holds a bed of the ward this specialty needs, for a
        window set by the urgency — 2h emergency, 6h urgent, 24h routine.
      </p>

      {error && <p className="mt-3 text-[14px] text-danger">{error}</p>}

      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          variant="accent"
          size="lg"
          onClick={() => place.mutate()}
          disabled={place.isPending || !from || !to || !patient}
        >
          {place.isPending ? "Holding a bed…" : "Reserve a bed"}
        </Button>
        <Button size="lg" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </Panel>
  );
}

/** §6 toolbar: segmented pill filters, active segment is ink on white. */
function Segmented({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Array<[string, string]>;
}) {
  return (
    <div className="inline-flex max-w-full items-center gap-0.5 overflow-x-auto rounded-full border border-line bg-surface-2 p-0.5">
      {options.map(([key, text]) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={
            "min-h-[36px] whitespace-nowrap rounded-full px-4 text-[13px] font-medium transition-colors " +
            (value === key ? "bg-ink text-white" : "text-muted hover:text-ink")
          }
        >
          {text}
        </button>
      ))}
    </div>
  );
}

const ACTIVE: string[] = ["REQUESTED", "RESERVED", "CONFIRMED", "ARRIVED"];

export default function Referrals() {
  const qc = useQueryClient();
  // Active by default. Every demo-check run leaves a cancelled row behind, and a
  // presenter opening this screen should see live holds, not a history of them.
  const [filter, setFilter] = useState<"active" | "all">("active");
  const { data: referrals = [], isLoading } = useQuery({
    queryKey: ["referrals"],
    queryFn: fetchReferrals,
    // The sweeper releases holds on its own timer, so the screen has to re-read rather
    // than trust what it rendered a minute ago.
    refetchInterval: 15_000,
  });
  const [note, setNote] = useState("");

  const act = useMutation({
    mutationFn: ({
      id,
      action,
    }: {
      id: string;
      action: "confirm" | "cancel";
    }) => (action === "confirm" ? confirmReferral(id) : cancelReferral(id)),
    onSuccess: () => {
      setNote("");
      qc.invalidateQueries({ queryKey: ["referrals"] });
      qc.invalidateQueries({ queryKey: ["beds"] });
    },
    // A confirm that lost the race to the sweeper is a real answer, not a glitch.
    onError: (e: Error) => setNote(e.message),
  });

  const holding = referrals.filter((r) => r.status === "RESERVED").length;
  const shown =
    filter === "active"
      ? referrals.filter((r) => ACTIVE.includes(r.status))
      : referrals;

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="fade-up flex flex-wrap items-end justify-between gap-4">
        <div>
          <Eyebrow dash>Command Center</Eyebrow>
          <h1 className="mt-3 text-[34px] leading-[0.98] tracking-[-0.04em] sm:text-[44px]">
            Referral{" "}
            <span className="font-normal italic text-primary">
              reservations
            </span>
          </h1>
        </div>
        <Chip tone={holding ? "info" : "neutral"}>
          <span className="live-state">{holding} bed(s) held</span>
        </Chip>
      </header>

      <section className="fade-up mt-6 flex flex-wrap items-center gap-3">
        <Segmented
          value={filter}
          onChange={(v) => setFilter(v as "active" | "all")}
          options={[
            [
              "active",
              `Active (${referrals.filter((r) => ACTIVE.includes(r.status)).length})`,
            ],
            ["all", `All (${referrals.length})`],
          ]}
        />
        <PlaceReferral
          onPlaced={() => {
            qc.invalidateQueries({ queryKey: ["referrals"] });
            qc.invalidateQueries({ queryKey: ["beds"] });
          }}
        />
      </section>

      {note && (
        <Panel className="fade-up mt-6 border-warn p-4 text-[15px]">
          {note}
        </Panel>
      )}

      {/* Card stack on phones; the eight-column table only earns its keep on a desk. */}
      <div className="fade-up mt-7 grid gap-2 md:hidden">
        {shown.map((r) => (
          <Panel key={r.id} className="p-4">
            <div className="flex flex-wrap items-center gap-2">
              <StatusChip state={r.status} tones={REFERRAL_TONE} />
              <Countdown referral={r} />
            </div>
            <p className="mt-3 text-[15px] font-medium">{r.patient_name}</p>
            <p className="text-[14px] text-muted">
              {r.from_hospital} → {r.to_hospital}
            </p>
            <p className="mt-1 text-[14px] text-muted">
              {r.specialty} · {r.bed ?? "no bed held"}
            </p>
            {r.status === "RESERVED" && (
              <div className="mt-4 flex gap-2">
                <Button
                  size="sm"
                  variant="accent"
                  onClick={() => act.mutate({ id: r.id, action: "confirm" })}
                >
                  Confirm
                </Button>
                <Button
                  size="sm"
                  onClick={() => act.mutate({ id: r.id, action: "cancel" })}
                >
                  Cancel
                </Button>
              </div>
            )}
          </Panel>
        ))}
      </div>

      <div className="fade-up mt-7 hidden md:block">
        <TableShell
          columns={[
            "Patient",
            "From → To",
            "Specialty",
            "Urgency",
            "Status",
            "Bed",
            "Expires",
            "",
          ]}
          footer={`${shown.length} referral(s)${isLoading ? " · loading" : ""}`}
        >
          {shown.map((r) => (
            <Row key={r.id}>
              <Cell>{r.patient_name}</Cell>
              <Cell>
                {r.from_hospital} → {r.to_hospital}
              </Cell>
              <Cell>{r.specialty}</Cell>
              <Cell>
                <Chip tone={URGENCY_TONE[r.urgency]}>
                  <span className="live-state">{r.urgency.toLowerCase()}</span>
                </Chip>
              </Cell>
              <Cell>
                <StatusChip state={r.status} tones={REFERRAL_TONE} />
              </Cell>
              <Cell mono>{r.bed ?? "—"}</Cell>
              <Cell>
                <Countdown referral={r} />
              </Cell>
              <Cell>
                {r.status === "RESERVED" && (
                  <span className="flex gap-2">
                    <Button
                      size="sm"
                      variant="accent"
                      onClick={() =>
                        act.mutate({ id: r.id, action: "confirm" })
                      }
                    >
                      Confirm
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => act.mutate({ id: r.id, action: "cancel" })}
                    >
                      Cancel
                    </Button>
                  </span>
                )}
              </Cell>
            </Row>
          ))}
        </TableShell>
      </div>

      {!isLoading && shown.length === 0 && (
        <Panel className="mt-8 p-8 text-center text-[15px] text-muted">
          No referrals yet. Rank an emergency on the Golden Hour screen and
          refer from there.
        </Panel>
      )}
    </main>
  );
}
