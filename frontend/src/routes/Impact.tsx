import { useQuery } from "@tanstack/react-query";

import { Chip, Eyebrow, Panel, SimulatedChip } from "../components/ui";
import { fetchFcfs, fetchImpact, type FcfsScenario } from "../lib/facilities";

/** The evidence screen — DESIGN.md §9a.
 *
 *  The problem statement names *reduced waiting time* twice as the benefit, and until
 *  now the only proof of it lived in a JSON file you had to `cat` in a terminal. This
 *  is that proof, on a screen, with the uncomfortable half included.
 *
 *  Two things it deliberately does NOT do: it does not claim everyone waits less
 *  (they do not), and it does not convert notice into "hours of travel saved" (we
 *  cannot know that). Both would be easy, bigger numbers and worse answers. */

const SERIES = {
  cpsat: "var(--color-series-2)",
  fcfs: "var(--color-series-1)",
};

function Bar({
  label,
  cpsat,
  fcfs,
  max,
  unit = "min",
  lowerIsBetter = true,
}: {
  label: string;
  cpsat: number;
  fcfs: number;
  max: number;
  unit?: string;
  lowerIsBetter?: boolean;
}) {
  const better = lowerIsBetter ? cpsat < fcfs : cpsat > fcfs;
  return (
    <div className="grid grid-cols-[1fr] gap-1.5 sm:grid-cols-[180px_1fr] sm:items-center sm:gap-4">
      <span className="text-[14px] text-muted">{label}</span>
      <div className="grid gap-1">
        {(
          [
            ["Ours", cpsat, SERIES.cpsat],
            ["FCFS", fcfs, SERIES.fcfs],
          ] as const
        ).map(([name, value, colour]) => (
          <div key={name} className="flex items-center gap-2">
            <span className="w-10 shrink-0 text-[12px] text-muted-2">
              {name}
            </span>
            <span
              className="h-4 min-w-[2px] rounded-xs"
              style={{
                width: `${max ? Math.max((value / max) * 100, 1) : 1}%`,
                background: colour,
              }}
              aria-hidden
            />
            <span className="tnum shrink-0 text-[13px]">
              {value}
              {unit}
            </span>
          </div>
        ))}
      </div>
      <span className="sr-only">
        {label}: ours {cpsat}
        {unit}, first-come-first-served {fcfs}
        {unit}. {better ? "Ours is better." : "Ours is not better."}
      </span>
    </div>
  );
}

function Scenario({ scenario }: { scenario: FcfsScenario }) {
  const { cpsat, fcfs, priority_mean_displacement: prio } = scenario;
  const maxDisp = Math.max(
    cpsat.mean_displacement_min,
    fcfs.mean_displacement_min,
  );
  const maxWait = Math.max(
    cpsat.experienced_wait_min,
    fcfs.experienced_wait_min,
  );
  const classes = [
    ...new Set([...Object.keys(prio.cpsat), ...Object.keys(prio.fcfs)]),
  ];
  const maxPrio = Math.max(
    ...classes.map((c) => Math.max(prio.cpsat[c] ?? 0, prio.fcfs[c] ?? 0)),
  );

  return (
    <Panel className="p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-[17px] font-semibold capitalize tracking-[-0.01em]">
          {scenario.name}
        </h3>
        <Chip tone="neutral">
          <span className="live-state tnum">
            {scenario.seats_for_40_patients} seats for 40
          </span>
        </Chip>
      </div>

      <div className="mt-5 grid gap-4">
        <Bar
          label="Appointment moved by"
          cpsat={cpsat.mean_displacement_min}
          fcfs={fcfs.mean_displacement_min}
          max={maxDisp}
        />
        <Bar
          label="Wait in the clinic"
          cpsat={cpsat.experienced_wait_min}
          fcfs={fcfs.experienced_wait_min}
          max={maxWait}
        />
      </div>

      <div className="mt-6 border-t border-line-2 pt-5">
        <Eyebrow>Who waits, by clinical priority</Eyebrow>
        <div className="mt-3 grid gap-4">
          {classes.map((c) => (
            <Bar
              key={c}
              label={c.toLowerCase()}
              cpsat={prio.cpsat[c] ?? 0}
              fcfs={prio.fcfs[c] ?? 0}
              max={maxPrio}
            />
          ))}
        </div>
      </div>

      {(cpsat.unplaced > 0 || fcfs.unplaced > 0) && (
        <p className="mt-5 border-t border-line-2 pt-4 text-[14px] text-muted">
          Both policies had to turn away{" "}
          <span className="tnum">
            {Math.max(cpsat.unplaced, fcfs.unplaced)}
          </span>{" "}
          of 40. First-come-first-served picks them by list order and drops
          referred patients entirely; ours drops the lowest clinical priority
          and seats every referred patient first.
        </p>
      )}
    </Panel>
  );
}

export default function Impact() {
  const { data: impact } = useQuery({
    queryKey: ["impact"],
    queryFn: fetchImpact,
    refetchInterval: 20_000,
  });
  const { data: fcfs, isError } = useQuery({
    queryKey: ["fcfs"],
    queryFn: fetchFcfs,
  });

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="fade-up">
        <Eyebrow dash>Command Center</Eyebrow>
        <h1 className="mt-3 text-[34px] leading-[0.98] tracking-[-0.04em] sm:text-[44px]">
          Waiting{" "}
          <span className="font-normal italic text-primary">avoided</span>
        </h1>
      </header>

      {/* The headline. Notice given, not travel time invented — see services/impact.py. */}
      <section className="fade-up mt-7 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Panel className="px-4 py-4">
          <Eyebrow>Told before their slot</Eyebrow>
          <div className="num-hero mt-1 text-[40px] font-medium">
            {impact?.told_in_time ?? "—"}
          </div>
          <p className="mt-1 text-[13px] text-muted">
            of {impact?.patients_told ?? 0} messaged (
            {impact?.told_in_time_pct ?? 0}%)
          </p>
        </Panel>
        <Panel className="px-4 py-4">
          <Eyebrow>Median notice</Eyebrow>
          <div className="num-hero mt-1 text-[40px] font-medium">
            {impact?.median_notice_minutes != null
              ? `${Math.round(impact.median_notice_minutes / 60)}h`
              : "—"}
          </div>
          <p className="mt-1 text-[13px] text-muted">
            before they would have travelled
          </p>
        </Panel>
        <Panel className="px-4 py-4">
          <Eyebrow>Replans</Eyebrow>
          <div className="num-hero mt-1 text-[40px] font-medium">
            {impact?.replans ?? "—"}
          </div>
          <p className="mt-1 text-[13px] text-muted">
            {impact?.fastest_replan_ms ?? "—"}–
            {impact?.slowest_replan_ms ?? "—"} ms, budget 5000
          </p>
        </Panel>
        {/* The counterweight sits beside the headline, not in a footnote. */}
        <Panel className="px-4 py-4">
          <Eyebrow>Still owed a seat</Eyebrow>
          <div className="num-hero mt-1 text-[40px] font-medium">
            {impact?.still_pending ?? "—"}
          </div>
          <p className="mt-1 text-[13px] text-muted">
            {impact?.told_too_late ?? 0} were told after their slot
          </p>
        </Panel>
      </section>

      <Panel className="fade-up mt-4 p-4 text-[14px] text-muted sm:p-5">
        The saving is not minutes shaved off a queue — it is a journey not made.
        A patient who travels hours to a clinic with no doctor loses a day, and
        the only reason we can warn them is that presence is detected rather
        than assumed. So this counts{" "}
        <strong className="font-medium text-ink">notice given</strong>, which
        the database can prove, rather than hours of travel saved, which it
        cannot.
      </Panel>

      <section
        className="fade-up mt-9"
        style={{ ["--delay" as string]: "80ms" }}
      >
        <Eyebrow dash>Ours vs first-come-first-served</Eyebrow>
        <h2 className="mt-2 text-[20px] font-semibold tracking-[-0.01em]">
          {fcfs
            ? `${fcfs.runs_per_scenario} runs per scenario, identical demand`
            : ""}
        </h2>

        {isError && (
          <Panel className="mt-3 p-5 text-[15px] text-muted">
            No comparison artifact yet — run{" "}
            <span className="tnum">python ml/compare_fcfs.py</span>.
          </Panel>
        )}

        {fcfs && (
          <>
            {/* The honest reading ships WITH the numbers rather than being left to a
                presenter to remember. It is the strongest thing on this screen. */}
            <Panel raised className="mt-4 border-warn p-4 sm:p-5">
              <div className="flex items-center gap-2">
                <SimulatedChip label="Read this before quoting the chart" />
              </div>
              <p className="mt-3 text-[15px] leading-relaxed">
                {fcfs.honest_reading}
              </p>
            </Panel>

            <div className="mt-4 grid gap-4">
              {fcfs.scenarios.map((s) => (
                <Scenario key={s.name} scenario={s} />
              ))}
            </div>
          </>
        )}
      </section>
    </main>
  );
}
