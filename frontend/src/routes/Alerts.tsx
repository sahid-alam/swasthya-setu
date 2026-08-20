import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { Chip, Eyebrow, Panel } from "../components/ui";
import { dashboardSocket } from "../lib/api";
import { fetchAlerts, SEVERITY_TONE, type Alert } from "../lib/command";

/** Alerts — PRD §M4. Roster-vs-presence mismatch is the one this product is named
 *  for: the paperwork says one thing and the building says another. */
export default function Alerts() {
  const qc = useQueryClient();
  const { data: alerts = [], isLoading } = useQuery({
    queryKey: ["alerts"],
    queryFn: fetchAlerts,
    refetchInterval: 20_000,
  });

  // anything that changes the world re-reads the board; no refresh button (§M4)
  useEffect(() => {
    const ws = dashboardSocket();
    ws.onmessage = (m) => {
      const topic = JSON.parse(m.data).topic;
      if (topic === "presence.changed" || topic === "appointments.replanned") {
        qc.invalidateQueries({ queryKey: ["alerts"] });
      }
    };
    return () => ws.close();
  }, [qc]);

  const bySeverity = (s: Alert["severity"]) =>
    alerts.filter((a) => a.severity === s);

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <header className="fade-up flex flex-wrap items-end justify-between gap-4">
        <div>
          <Eyebrow dash>Command Center</Eyebrow>
          <h1 className="mt-3 text-[44px] leading-[0.98] tracking-[-0.04em]">
            What needs{" "}
            <span className="font-normal italic text-primary">attention</span>
          </h1>
        </div>
        <div className="flex gap-2">
          {(["critical", "warn", "info"] as const).map((s) =>
            bySeverity(s).length ? (
              <Chip key={s} tone={SEVERITY_TONE[s]} pulse={s === "critical"}>
                <span className="live-state">
                  {bySeverity(s).length} {s}
                </span>
              </Chip>
            ) : null,
          )}
        </div>
      </header>

      {alerts.length === 0 && !isLoading && (
        <Panel className="fade-up mt-8 p-8 text-center">
          <p className="text-[17px]">Nothing needs attention.</p>
          <p className="mt-1 text-[15px] text-muted">
            Every rostered doctor has been seen, and no queue is running long.
          </p>
        </Panel>
      )}

      <ul className="mt-8 grid gap-3">
        {alerts.map((a, i) => (
          <li key={`${a.kind}-${i}`}>
            <Panel
              className="fade-up flex flex-wrap items-start justify-between gap-4 p-5"
              style={{ ["--delay" as string]: `${Math.min(i, 8) * 40}ms` }}
            >
              <div className="min-w-[280px] flex-1">
                <div className="flex items-center gap-3">
                  <Chip
                    tone={SEVERITY_TONE[a.severity]}
                    pulse={a.severity === "critical"}
                  >
                    <span className="live-state">{a.severity}</span>
                  </Chip>
                  <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
                    {a.kind.replace(/_/g, " ")}
                  </span>
                </div>
                <h2 className="mt-2 text-[17px] font-semibold">{a.title}</h2>
                <p className="mt-1 text-[15px] text-muted">{a.detail}</p>
              </div>
              <div className="text-right text-[13px] text-muted">
                <div>{a.hospital}</div>
                {a.department && (
                  <div className="text-muted-2">{a.department}</div>
                )}
              </div>
            </Panel>
          </li>
        ))}
      </ul>
    </main>
  );
}
