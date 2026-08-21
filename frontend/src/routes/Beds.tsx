import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  BED_TONE,
  Cell,
  Chip,
  Eyebrow,
  Panel,
  Row,
  TableShell,
} from "../components/ui";
import { fetchOccupancy, type Ward } from "../lib/facilities";

/** Bed occupancy — PRD §M5, DESIGN.md §9a (command centre: density is fine here).
 *  Counts come straight from `beds.state`, so this and the Golden Hour ranking can
 *  never disagree about how many beds are free. */

type CountKey = "free" | "occupied" | "reserved" | "cleaning" | "ooo";

const STATES: Array<[CountKey, string]> = [
  ["free", "FREE"],
  ["occupied", "OCCUPIED"],
  ["reserved", "RESERVED"],
  ["cleaning", "CLEANING"],
  ["ooo", "OOO"],
];

/** A ward's mix as one bar. Proportion is the thing a bed manager reads first, and
 *  §9d already fixes what each state's colour means — so the bar carries no new
 *  vocabulary, and every segment is still labelled in the row beside it. */
function OccupancyBar({ ward }: { ward: Ward }) {
  return (
    <span
      className="flex h-2 w-[120px] overflow-hidden rounded-full bg-line-2"
      aria-hidden
    >
      {STATES.map(([key, state]) => {
        const n = ward[key];
        if (!n) return null;
        return (
          <span
            key={state}
            className="h-full"
            style={{
              width: `${(n / ward.total) * 100}%`,
              background: `var(--chip-${BED_TONE[state]}-fg)`,
            }}
          />
        );
      })}
    </span>
  );
}

export default function Beds() {
  const { data: wards = [], isLoading } = useQuery({
    queryKey: ["beds"],
    queryFn: fetchOccupancy,
    refetchInterval: 20_000,
  });

  const totals = useMemo(() => {
    const t = {
      free: 0,
      occupied: 0,
      reserved: 0,
      cleaning: 0,
      ooo: 0,
      total: 0,
    };
    for (const w of wards) {
      t.free += w.free;
      t.occupied += w.occupied;
      t.reserved += w.reserved;
      t.cleaning += w.cleaning;
      t.ooo += w.ooo;
      t.total += w.total;
    }
    return t;
  }, [wards]);

  const byHospital = useMemo(() => {
    const groups = new Map<string, Ward[]>();
    for (const w of wards)
      groups.set(w.hospital, [...(groups.get(w.hospital) ?? []), w]);
    return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [wards]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="fade-up flex flex-wrap items-end justify-between gap-4">
        <div>
          <Eyebrow dash>Command Center</Eyebrow>
          <h1 className="mt-3 text-[34px] leading-[0.98] tracking-[-0.04em] sm:text-[44px]">
            Bed{" "}
            <span className="font-normal italic text-primary">occupancy</span>
          </h1>
        </div>
        <Chip tone={totals.free > 0 ? "success" : "danger"}>
          <span className="live-state">
            {totals.free} of {totals.total} free
          </span>
        </Chip>
      </header>

      <section className="fade-up mt-7 flex flex-wrap gap-2">
        {STATES.map(([key, state]) => (
          <Panel key={state} className="px-4 py-3">
            <Eyebrow>{state}</Eyebrow>
            <div className="tnum mt-1 text-[20px] tracking-[-0.02em]">
              {totals[key]}
            </div>
          </Panel>
        ))}
      </section>

      {byHospital.map(([hospital, list], i) => (
        <section
          key={hospital}
          className="fade-up mt-8"
          style={{ ["--delay" as string]: `${80 * (i + 1)}ms` }}
        >
          <Eyebrow dash>{hospital}</Eyebrow>

          {/* Below md the table becomes a card stack: five state columns will not fit a
              phone, and a horizontally scrolled table hides exactly the number
              (free beds) someone opened this screen to find. */}
          <div className="mt-3 grid gap-2 md:hidden">
            {list.map((w) => (
              <Panel key={`${w.ward}-${w.kind}`} className="p-4">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[15px] font-medium">{w.ward}</span>
                  <span className="tnum text-[13px] text-muted">{w.kind}</span>
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <Chip tone={w.free ? "success" : "danger"}>
                    <span className="live-state">{w.free} free</span>
                  </Chip>
                  <span className="tnum text-[13px] text-muted">
                    of {w.total}
                  </span>
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <OccupancyBar ward={w} />
                </div>
              </Panel>
            ))}
          </div>

          <div className="mt-3 hidden md:block">
            <TableShell
              columns={[
                "Ward",
                "Kind",
                "Mix",
                "Free",
                "Occupied",
                "Reserved",
                "Cleaning",
                "Out",
              ]}
              footer={`${list.length} wards${isLoading ? " · loading" : ""}`}
            >
              {list.map((w) => (
                <Row key={`${w.ward}-${w.kind}`}>
                  <Cell>{w.ward}</Cell>
                  <Cell mono>{w.kind}</Cell>
                  <Cell>
                    <OccupancyBar ward={w} />
                  </Cell>
                  <Cell>
                    <Chip tone={w.free ? "success" : "danger"}>
                      <span className="live-state">{w.free}</span>
                    </Chip>
                  </Cell>
                  <Cell mono>{w.occupied}</Cell>
                  <Cell mono>{w.reserved}</Cell>
                  <Cell mono>{w.cleaning}</Cell>
                  <Cell mono>{w.ooo}</Cell>
                </Row>
              ))}
            </TableShell>
          </div>
        </section>
      ))}

      {!isLoading && wards.length === 0 && (
        <Panel className="mt-8 p-8 text-center text-[15px] text-muted">
          No beds are seeded yet — run{" "}
          <span className="tnum">make seed-facilities</span>.
        </Panel>
      )}
    </main>
  );
}
