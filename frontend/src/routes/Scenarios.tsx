import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Chip, Eyebrow, Panel, SimulatedChip } from "../components/ui";
import { fetchRoster, SCENARIOS, type SimDoctor } from "../lib/scenarios";

/** Scenario triggers — PRD §M4, signal-simulator SKILL.md. Admin-only in practice
 *  (every endpoint behind these buttons enforces its own role). */
export default function Scenarios() {
  const [badge, setBadge] = useState("HP-DOC-1001");
  const [log, setLog] = useState<{ at: string; text: string; bad?: boolean }[]>(
    [],
  );
  const [busy, setBusy] = useState<string | null>(null);

  const { data: roster } = useQuery({
    queryKey: ["roster"],
    queryFn: fetchRoster,
  });
  const doctors = roster?.doctors ?? [];
  const doctor: SimDoctor | undefined =
    doctors.find((d) => d.badge_id === badge) ?? doctors[0];

  async function run(id: string) {
    if (!roster || !doctor) return;
    const scenario = SCENARIOS.find((s) => s.id === id)!;
    setBusy(id);
    try {
      const message = await scenario.run(roster, doctor);
      setLog((l) =>
        [{ at: new Date().toLocaleTimeString(), text: message }, ...l].slice(
          0,
          12,
        ),
      );
    } catch (err) {
      setLog((l) =>
        [
          {
            at: new Date().toLocaleTimeString(),
            text: `${scenario.label} failed: ${(err as Error).message}`,
            bad: true,
          },
          ...l,
        ].slice(0, 12),
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <header className="fade-up flex flex-wrap items-end justify-between gap-4">
        <div>
          <Eyebrow dash>Command Center</Eyebrow>
          <h1 className="mt-3 text-[44px] leading-[0.98] tracking-[-0.04em]">
            Scenario{" "}
            <span className="font-normal italic text-primary">triggers</span>
          </h1>
        </div>
        <SimulatedChip />
      </header>

      <p className="fade-up mt-4 max-w-[62ch] text-[15px] text-muted">
        These post to the same public{" "}
        <code className="font-mono text-[13px]">/api/v1/signals</code> endpoint
        real hardware uses. Nothing here writes to the database directly — a
        scenario button that cheated would make the demo a lie.
      </p>

      <Panel className="fade-up mt-6 flex flex-wrap items-center gap-3 p-5">
        <Eyebrow>Doctor</Eyebrow>
        <select
          value={doctor?.badge_id ?? ""}
          onChange={(e) => setBadge(e.target.value)}
          className="min-h-[40px] min-w-[320px] rounded-sm border border-line bg-surface px-3 text-[15px]"
        >
          {doctors.map((d) => (
            <option key={d.badge_id} value={d.badge_id}>
              {d.name} — {d.department} ({d.badge_id})
            </option>
          ))}
        </select>
        {doctor && (
          <Chip tone="neutral">
            <span className="live-state">{doctor.hospital_code}</span>
          </Chip>
        )}
      </Panel>

      <section className="mt-6 grid gap-3 sm:grid-cols-2">
        {SCENARIOS.map((s, i) => (
          <Panel
            key={s.id}
            className="fade-up flex flex-col justify-between gap-4 p-5"
            style={{ ["--delay" as string]: `${i * 50}ms` }}
          >
            <div>
              <h2 className="text-[17px] font-semibold">{s.label}</h2>
              <p className="mt-1 text-[14px] text-muted">{s.blurb}</p>
            </div>
            <Button
              variant={s.danger ? "danger" : "primary"}
              size="lg"
              disabled={busy !== null || !doctor}
              onClick={() => void run(s.id)}
            >
              {busy === s.id ? "Running…" : "Trigger"}
            </Button>
          </Panel>
        ))}
      </section>

      {log.length > 0 && (
        <Panel className="mt-6 p-5">
          <Eyebrow>What just happened</Eyebrow>
          <ul className="mt-3 grid gap-1.5">
            {log.map((entry, i) => (
              <li key={i} className="flex gap-3 text-[15px]">
                <span className="tnum text-[12px] text-muted-2">
                  {entry.at}
                </span>
                <span className={entry.bad ? "text-danger" : ""}>
                  {entry.text}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </main>
  );
}
