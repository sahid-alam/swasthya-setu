import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  Cell,
  Chip,
  Eyebrow,
  Kinetic,
  Panel,
  Row,
  TableShell,
} from "../components/ui";
import { fetchDepartments, fetchQueue } from "../lib/command";

/** Queue view with predicted waits — PRD §M4. The prediction is per queue position,
 *  which is the question a patient actually asks: how long from now. */
export default function Queues() {
  const [dept, setDept] = useState<string>("");

  const { data: departments = [] } = useQuery({
    queryKey: ["departments"],
    queryFn: fetchDepartments,
    refetchInterval: 15_000,
  });

  useEffect(() => {
    if (!dept && departments.length) {
      const busiest = [...departments].sort((a, b) => b.waiting - a.waiting)[0];
      setDept(busiest.id);
    }
  }, [departments, dept]);

  const { data: queue = [], isLoading } = useQuery({
    queryKey: ["queue", dept],
    queryFn: () => fetchQueue(dept),
    enabled: Boolean(dept),
    refetchInterval: 15_000,
  });

  const current = departments.find((d) => d.id === dept);
  const longest = queue.reduce(
    (max, e) => Math.max(max, e.predicted_wait_minutes ?? 0),
    0,
  );

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="fade-up">
        <Eyebrow dash>Command Center</Eyebrow>
        <h1 className="mt-3 text-[34px] leading-[0.98] tracking-[-0.04em] sm:text-[44px]">
          <Kinetic lead="Live" accent="queues" />
        </h1>
      </header>

      <section className="fade-up mt-6 flex flex-wrap items-center gap-3">
        {/* min-w-0 + max-w-full: a select sizes itself to its longest option, and
            "General Medicine — Indira Gandhi Medical College (12)" was dragging the
            whole document 199px sideways on a phone. */}
        <label className="flex w-full min-w-0 flex-col gap-1.5 sm:w-auto sm:flex-row sm:items-center sm:gap-3">
          <Eyebrow>Department</Eyebrow>
          <select
            value={dept}
            onChange={(e) => setDept(e.target.value)}
            className="min-h-[40px] w-full min-w-0 max-w-full truncate rounded-sm border border-line bg-surface px-3 text-[15px] sm:w-auto"
          >
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} — {d.hospital} ({d.waiting})
              </option>
            ))}
          </select>
        </label>
        {longest > 0 && (
          <Chip
            tone={longest > 60 ? "danger" : longest > 30 ? "warn" : "success"}
          >
            <span className="live-state">Longest wait {longest} min</span>
          </Chip>
        )}
      </section>

      <section className="fade-up mt-4 flex flex-wrap gap-2">
        <Panel className="px-4 py-3">
          <Eyebrow>Waiting</Eyebrow>
          <div className="tnum mt-1 text-[20px]">{queue.length}</div>
        </Panel>
        <Panel className="px-4 py-3">
          <Eyebrow>Likely no-shows</Eyebrow>
          <div className="tnum mt-1 text-[20px]">
            {queue.filter((e) => (e.noshow_prob ?? 0) >= 0.5).length}
          </div>
        </Panel>
        <Panel className="px-4 py-3">
          <Eyebrow>Hospital</Eyebrow>
          <div className="mt-1 text-[15px]">{current?.hospital ?? "—"}</div>
        </Panel>
      </section>

      <section
        className="fade-up mt-6"
        style={{ ["--delay" as string]: "80ms" }}
      >
        <TableShell
          columns={[
            "#",
            "Patient",
            "Doctor",
            "Scheduled",
            "Predicted wait",
            "No-show",
          ]}
          footer={
            isLoading
              ? "loading…"
              : `${queue.length} waiting · predictions from the committed model`
          }
        >
          {queue.map((e) => {
            const wait = e.predicted_wait_minutes ?? 0;
            return (
              <Row key={e.appointment_id}>
                <Cell mono>{e.position + 1}</Cell>
                <Cell>{e.patient_name}</Cell>
                <Cell>{e.doctor_name}</Cell>
                <Cell mono>
                  {new Date(e.scheduled_for).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </Cell>
                <Cell>
                  {/* never colour alone — the number is always spelled out (§9a) */}
                  <Chip
                    tone={wait > 60 ? "danger" : wait > 30 ? "warn" : "success"}
                  >
                    <span className="live-state">{wait} min</span>
                  </Chip>
                </Cell>
                <Cell>
                  {e.noshow_prob === null ? (
                    <span className="text-muted">—</span>
                  ) : (
                    <span className="tnum">
                      {Math.round(e.noshow_prob * 100)}%
                      {e.noshow_prob >= 0.5 && (
                        <span className="ml-2 font-mono text-[10px] uppercase tracking-[0.1em] text-warn">
                          overbookable
                        </span>
                      )}
                    </span>
                  )}
                </Cell>
              </Row>
            );
          })}
        </TableShell>
        {!isLoading && queue.length === 0 && (
          <Panel className="mt-3 p-6 text-[15px] text-muted">
            Nobody waiting in this department.
          </Panel>
        )}
      </section>
    </main>
  );
}
