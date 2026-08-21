import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  Cell,
  Chip,
  Eyebrow,
  Panel,
  PresenceChip,
  Row,
  TableShell,
} from "../components/ui";
import { dashboardSocket } from "../lib/api";
import {
  fetchPresence,
  fetchTransitions,
  STATE_LABEL,
  type PresenceRow,
} from "../lib/presence";

/** Command centre presence board (PRD §M4, DESIGN.md §9a).
 *  WebSocket-driven: there is no refresh button anywhere. */
export default function PresenceBoard() {
  const qc = useQueryClient();
  const [live, setLive] = useState(false);
  const [flashed, setFlashed] = useState<Record<string, number>>({});
  const [openDoctor, setOpenDoctor] = useState<string | null>(null);

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ["presence"],
    queryFn: fetchPresence,
  });

  useEffect(() => {
    const ws = dashboardSocket();
    ws.onclose = () => setLive(false);
    ws.onmessage = (m) => {
      const event = JSON.parse(m.data);
      if (event.topic === "ws.ready") return setLive(true);
      if (event.topic !== "presence.changed") return;
      // a state actually flipped, so pull the board again and mark the row
      qc.invalidateQueries({ queryKey: ["presence"] });
      const id = event.payload.doctor_id as string;
      setFlashed((f) => ({ ...f, [id]: Date.now() }));
    };
    return () => ws.close();
  }, [qc]);

  const byHospital = useMemo(() => {
    const groups = new Map<string, PresenceRow[]>();
    for (const row of rows) {
      groups.set(row.hospital, [...(groups.get(row.hospital) ?? []), row]);
    }
    for (const list of groups.values()) {
      list.sort((a, b) => a.department.localeCompare(b.department));
    }
    return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [rows]);

  const counts = useMemo(() => {
    const tally: Record<string, number> = {};
    for (const r of rows) tally[r.state] = (tally[r.state] ?? 0) + 1;
    return tally;
  }, [rows]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="fade-up flex flex-wrap items-end justify-between gap-4">
        <div>
          <Eyebrow dash>Command Center</Eyebrow>
          <h1 className="mt-3 text-[34px] leading-[0.98] tracking-[-0.04em] sm:text-[44px]">
            Doctor{" "}
            <span className="font-normal italic text-primary">presence</span>
          </h1>
        </div>
        <Chip tone={live ? "success" : "neutral"} pulse={live}>
          <span className="live-state">{live ? "Live" : "Reconnecting…"}</span>
        </Chip>
      </header>

      <section className="fade-up mt-7 flex flex-wrap gap-2">
        {Object.entries(STATE_LABEL).map(([state, label]) =>
          counts[state] ? (
            <Panel key={state} className="px-4 py-3">
              <Eyebrow>{label}</Eyebrow>
              <div className="tnum mt-1 text-[20px] tracking-[-0.02em]">
                {counts[state]}
              </div>
            </Panel>
          ) : null,
        )}
      </section>

      {byHospital.map(([hospital, list], i) => (
        <section
          key={hospital}
          className="fade-up mt-8"
          style={{ ["--delay" as string]: `${80 * (i + 1)}ms` }}
        >
          <Eyebrow dash>{hospital}</Eyebrow>
          <div className="mt-3">
            <TableShell
              columns={["Doctor", "Department", "State", "Zone", "Why"]}
              footer={`${list.length} doctors${isLoading ? " · loading" : ""}`}
            >
              {list.map((row) => (
                <Row key={row.doctor_id}>
                  <Cell>
                    <span className="flex items-center gap-2">
                      {row.doctor_name}
                      {Date.now() - (flashed[row.doctor_id] ?? 0) < 6000 && (
                        <Chip tone="info">
                          <span className="live-state">just changed</span>
                        </Chip>
                      )}
                    </span>
                  </Cell>
                  <Cell>{row.department}</Cell>
                  <Cell>
                    <PresenceChip
                      state={row.state}
                      confidence={row.confidence}
                      degraded={row.evidence.degraded_to_roster}
                    />
                  </Cell>
                  <Cell mono>{row.zone_code ?? "—"}</Cell>
                  <Cell>
                    <button
                      className="-mx-2 min-h-[40px] rounded-sm px-2 text-[13px] text-primary underline"
                      onClick={() =>
                        setOpenDoctor(
                          openDoctor === row.doctor_id ? null : row.doctor_id,
                        )
                      }
                    >
                      evidence
                    </button>
                  </Cell>
                </Row>
              ))}
            </TableShell>
          </div>
        </section>
      ))}

      {openDoctor && (
        <EvidenceDrawer
          doctorId={openDoctor}
          row={rows.find((r) => r.doctor_id === openDoctor)}
          onClose={() => setOpenDoctor(null)}
        />
      )}
    </main>
  );
}

/** The judge answer to "how do you know?" — every contributing observation. */
function EvidenceDrawer({
  doctorId,
  row,
  onClose,
}: {
  doctorId: string;
  row?: PresenceRow;
  onClose: () => void;
}) {
  const { data: trail = [] } = useQuery({
    queryKey: ["transitions", doctorId],
    queryFn: () => fetchTransitions(doctorId),
  });

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-[rgba(10,14,20,0.48)]"
      onClick={onClose}
    >
      <Panel
        className="modal-in h-full w-full max-w-[520px] overflow-y-auto rounded-none p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <Eyebrow dash>Evidence trail</Eyebrow>
        <h2 className="mt-2 text-[24px] tracking-[-0.02em]">
          {row?.doctor_name}
        </h2>
        {row && (
          <p className="mt-1 text-[13px] text-muted">
            Roster says{" "}
            {STATE_LABEL[row.evidence.roster_state ?? "UNKNOWN"] ?? "—"}
            {row.evidence.degraded_to_roster &&
              " · no live signal strong enough, falling back to the roster"}
            {row.evidence.manual_override && " · set by an administrator"}
          </p>
        )}

        <h3 className="mt-6 text-[15px] font-semibold">
          What we can see right now
        </h3>
        <div className="mt-2 grid gap-1.5">
          {(row?.evidence.contributors ?? []).map((c, i) => (
            <div
              key={i}
              className="flex items-center justify-between border-b border-line-2 pb-1.5 text-[13px]"
            >
              <span className="font-mono text-[12px]">{c.source}</span>
              <span className="text-muted">{c.zone_code ?? "no zone"}</span>
              <span>{STATE_LABEL[c.state] ?? c.state}</span>
              <span className="tnum text-muted">
                {c.score.toFixed(2)} · {Math.round(c.age_seconds)}s ago
              </span>
            </div>
          ))}
        </div>

        <h3 className="mt-6 text-[15px] font-semibold">Recent state changes</h3>
        <div className="mt-2 grid gap-2">
          {trail.map((t, i) => (
            <div
              key={i}
              className="rounded-sm border border-line-2 p-2.5 text-[13px]"
            >
              <div className="flex items-center gap-2">
                <span className="text-muted">
                  {STATE_LABEL[t.from_state] ?? t.from_state}
                </span>
                <span aria-hidden>→</span>
                <strong>{STATE_LABEL[t.to_state] ?? t.to_state}</strong>
                <span className="tnum ml-auto text-[11px] text-muted">
                  {new Date(t.at).toLocaleTimeString()}
                </span>
              </div>
              {t.evidence.contributors?.[0] && (
                <div className="mt-1 text-[12px] text-muted">
                  because {t.evidence.contributors[0].source} saw them at{" "}
                  {t.evidence.contributors[0].zone_code ?? "an unknown zone"}{" "}
                  (score {t.evidence.contributors[0].score.toFixed(2)})
                </div>
              )}
            </div>
          ))}
          {trail.length === 0 && (
            <p className="text-[13px] text-muted">
              No state changes recorded yet.
            </p>
          )}
        </div>
      </Panel>
    </div>
  );
}
