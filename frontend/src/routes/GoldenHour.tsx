import { useMutation } from "@tanstack/react-query";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";

import {
  Button,
  Chip,
  Eyebrow,
  Kinetic,
  Panel,
  SimulatedChip,
} from "../components/ui";
import { rankEmergency, type Ranked, type Ranking } from "../lib/facilities";

/** Golden Hour Router — PRD §M8, DESIGN.md §9a.
 *
 *  **Decision support, not dispatch.** CLAUDE.md bans live 108 integration and fleet
 *  tracking; this ranks hospitals for a location and shows its reasoning. Nothing here
 *  moves a vehicle, and the screen says so out loud rather than in a comment.
 *
 *  The reasoning is the deliverable. Every facility is listed — including the ones
 *  ruled out — with the sentences behind its score, because a ranking that silently
 *  drops a hospital cannot be questioned. */

// The PRD's own example: an accident on NH-5 near Rampur.
const RAMPUR: [number, number] = [31.45, 77.63];

const SPECIALTIES = [
  "General Surgery",
  "Orthopaedics",
  "General Medicine",
  "Paediatrics",
  "Obstetrics & Gynaecology",
  "Neurosurgery",
];

const GROUPS = [
  "O_NEG",
  "O_POS",
  "A_POS",
  "A_NEG",
  "B_POS",
  "B_NEG",
  "AB_POS",
  "AB_NEG",
];
const label = (g: string) => g.replace("_POS", "+").replace("_NEG", "−");

function incidentIcon(): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<span style="display:grid;place-items:center;width:30px;height:30px;border-radius:999px;
      background:var(--danger);color:var(--surface);font:600 15px/1 var(--f-sans);
      box-shadow:0 4px 12px rgba(10,30,70,.35);border:2px solid var(--surface)">!</span>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

function facilityIcon(r: Ranked): L.DivIcon {
  // Rank is the information, so the marker carries the number. Ruled-out facilities go
  // grey rather than disappearing — §9d: never hide a state behind an optimistic colour.
  const bg = r.viable ? "var(--accent)" : "var(--muted-2)";
  return L.divIcon({
    className: "",
    html: `<span style="display:grid;place-items:center;width:32px;height:32px;border-radius:999px;
      background:${bg};color:var(--ink);font:600 14px/1 var(--f-sans);
      box-shadow:0 4px 12px rgba(10,30,70,.35);border:2px solid var(--surface)">${r.rank}</span>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });
}

export default function GoldenHour() {
  const holder = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);

  const [tilesOffline, setTilesOffline] = useState(false);
  const [at, setAt] = useState<[number, number]>(RAMPUR);
  const [specialty, setSpecialty] = useState(SPECIALTIES[0]);
  const [group, setGroup] = useState(GROUPS[0]);
  const [result, setResult] = useState<Ranking | null>(null);

  const rank = useMutation({
    mutationFn: () =>
      rankEmergency({
        lat: at[0],
        lng: at[1],
        specialty,
        blood_group: group,
        description: `Emergency at ${at[0].toFixed(4)}, ${at[1].toFixed(4)}`,
      }),
    onSuccess: setResult,
  });

  useEffect(() => {
    if (!holder.current || map.current) return;
    map.current = L.map(holder.current, { scrollWheelZoom: false }).setView(
      [31.6, 77.1],
      8,
    );
    // Iron Rule 4: tiles are the one thing here that needs internet, so their absence
    // is labelled rather than left as a blank rectangle — every marker still places and
    // every number below is real.
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap",
      maxZoom: 17,
    })
      .on("tileerror", () => setTilesOffline(true))
      .on("tileload", () => setTilesOffline(false))
      .addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    // Clicking the map is how you say "the accident is here".
    map.current.on("click", (e: L.LeafletMouseEvent) =>
      setAt([e.latlng.lat, e.latlng.lng]),
    );
    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    if (!map.current || !layer.current) return;
    layer.current.clearLayers();
    L.marker(at, { icon: incidentIcon() })
      .bindPopup("<strong>Incident</strong><br/>Click the map to move it")
      .addTo(layer.current);

    for (const r of result?.ranked ?? []) {
      L.marker([r.lat, r.lng], { icon: facilityIcon(r) })
        .bindPopup(
          `<strong>${r.rank}. ${r.hospital}</strong><br/>${r.drive_minutes} min · ${r.km} km` +
            `<br/>${r.viable ? "" : "<b>Ruled out</b><br/>"}${r.why.join("<br/>")}`,
        )
        .addTo(layer.current);
      // A straight line, not a route geometry: the offline estimator has no road
      // shape to draw, and inventing one would be the map lying about its own method.
      L.polyline([at, [r.lat, r.lng]], {
        color: r.viable ? "var(--accent)" : "var(--muted-2)",
        weight: r.rank === 1 ? 3 : 1.5,
        opacity: r.viable ? 0.75 : 0.35,
        dashArray: "5 6",
      }).addTo(layer.current);
    }

    // Only refit once there is something to fit to. Fitting a single point zooms to
    // street level, which loses the valley the whole ranking is about.
    if (result?.ranked.length) {
      const points: [number, number][] = [
        at,
        ...result.ranked.map((r) => [r.lat, r.lng] as [number, number]),
      ];
      map.current.fitBounds(L.latLngBounds(points).pad(0.3));
    }
  }, [at, result]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="fade-up flex flex-wrap items-end justify-between gap-4">
        <div>
          <Eyebrow dash>Command Center</Eyebrow>
          <h1 className="mt-3 text-[34px] leading-[0.98] tracking-[-0.04em] sm:text-[44px]">
            <Kinetic lead="Golden" accent="hour" />
          </h1>
        </div>
        {/* Said on the screen, not just in the code: this is not a dispatch system. */}
        <SimulatedChip label="Decision support — not 108 dispatch" />
      </header>

      <Panel className="fade-up mt-6 p-4 sm:p-5">
        {/* Stacks on a phone, one row from sm up — the kakion-ops pattern. */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="flex flex-1 flex-col gap-1.5">
            <Eyebrow>Specialty needed</Eyebrow>
            <select
              value={specialty}
              onChange={(e) => setSpecialty(e.target.value)}
              className="min-h-[40px] rounded-sm border border-line bg-surface px-3 text-[14px]"
            >
              {SPECIALTIES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5 sm:w-40">
            <Eyebrow>Blood group</Eyebrow>
            <select
              value={group}
              onChange={(e) => setGroup(e.target.value)}
              className="min-h-[40px] rounded-sm border border-line bg-surface px-3 text-[14px]"
            >
              {GROUPS.map((g) => (
                <option key={g} value={g}>
                  {label(g)}
                </option>
              ))}
            </select>
          </label>
          <Button
            variant="accent"
            size="lg"
            className="sm:flex-none"
            onClick={() => rank.mutate()}
            disabled={rank.isPending}
          >
            {rank.isPending ? "Ranking…" : "Rank facilities"}
          </Button>
        </div>
        <p className="mt-3 text-[13px] text-muted">
          Incident at{" "}
          <span className="tnum">
            {at[0].toFixed(4)}, {at[1].toFixed(4)}
          </span>{" "}
          — click the map to move it.
          {result && (
            <>
              {" "}
              Ranked in <span className="tnum">{result.duration_ms} ms</span>.
            </>
          )}
        </p>
      </Panel>

      <Panel className="fade-up relative mt-6 overflow-hidden p-0">
        {tilesOffline && (
          <div className="absolute right-3 top-3 z-[500]">
            <SimulatedChip label="Basemap offline — positions are real" />
          </div>
        )}
        <div
          ref={holder}
          className="h-[320px] w-full bg-surface-2 sm:h-[420px]"
        />
      </Panel>

      {result && (
        <section
          className="fade-up mt-6"
          style={{ ["--delay" as string]: "80ms" }}
        >
          <Eyebrow dash>Ranked facilities</Eyebrow>
          <div className="mt-3 grid gap-3">
            {result.ranked.map((r) => (
              <Panel key={r.hospital_id} className="p-4 sm:p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="flex items-center gap-3">
                    <span className="num-hero text-[24px] font-medium text-muted">
                      {r.rank}
                    </span>
                    <span className="text-[17px] font-semibold tracking-[-0.01em]">
                      {r.hospital}
                    </span>
                  </span>
                  <span className="flex flex-wrap items-center gap-2">
                    <Chip tone={r.viable ? "success" : "neutral"}>
                      <span className="live-state">
                        {r.viable ? "Can take this case" : "Ruled out"}
                      </span>
                    </Chip>
                    <Chip tone="info">
                      <span className="live-state tnum">
                        {r.drive_minutes} min
                      </span>
                    </Chip>
                  </span>
                </div>

                <p className="mt-2 text-[14px] text-muted">
                  <span className="tnum">{r.km} km</span> by road ·{" "}
                  <span className="tnum">{r.free_beds}</span> free bed(s) ·{" "}
                  <span className="tnum">{r.blood_units}</span> unit(s){" "}
                  {label(group)}
                </p>

                {/* The acceptance criterion, rendered: why this one, why not that one. */}
                <ul className="mt-3 grid gap-1 border-t border-line-2 pt-3">
                  {r.why.map((w) => (
                    <li key={w} className="text-[14px] text-muted">
                      — {w}
                    </li>
                  ))}
                </ul>

                {r.route_is_estimated && (
                  <div className="mt-3">
                    <SimulatedChip label="Drive time estimated — no OSRM" />
                  </div>
                )}
              </Panel>
            ))}
          </div>
        </section>
      )}

      {rank.isError && (
        <Panel className="mt-6 border-danger p-4 text-[15px] text-danger">
          {(rank.error as Error).message}
        </Panel>
      )}
    </main>
  );
}
