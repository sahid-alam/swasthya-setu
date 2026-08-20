import { useQuery } from "@tanstack/react-query";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";

import {
  Cell,
  Chip,
  Eyebrow,
  Panel,
  Row,
  SimulatedChip,
  TableShell,
} from "../components/ui";
import { fetchNetwork, SEVERITY_TONE, type Facility } from "../lib/command";

/* Leaflet's default marker icons are bundled as separate image files whose URLs break
   under a bundler. We draw our own instead — a divIcon is plain HTML, so it also lets
   the marker carry the same status vocabulary as the rest of the board (§9d). */
function marker(f: Facility): L.DivIcon {
  const colour = f.worst_severity
    ? { critical: "var(--danger)", warn: "var(--warn)", info: "var(--info)" }[
        f.worst_severity
      ]
    : "var(--success)";
  return L.divIcon({
    className: "",
    html: `<span style="display:grid;place-items:center;width:34px;height:34px;border-radius:999px;
      background:${colour};color:#fff;font:600 13px/1 var(--f-sans);
      box-shadow:0 4px 12px rgba(10,30,70,.35);border:2px solid #fff">${f.present}</span>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

/** Network map — PRD §M4. Himachal is mountains: two hospitals 40 km apart can be two
 *  hours apart, which is why the referral and Golden Hour work needs this view. */
export default function NetworkMap() {
  const holder = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);

  const [tilesOffline, setTilesOffline] = useState(false);

  const { data: facilities = [] } = useQuery({
    queryKey: ["network"],
    queryFn: fetchNetwork,
    refetchInterval: 20_000,
  });

  useEffect(() => {
    if (!holder.current || map.current) return;
    map.current = L.map(holder.current, { scrollWheelZoom: false }).setView(
      [31.6, 77.1],
      8,
    );
    // Iron Rule 4: the demo must run with no internet. Tiles are the one thing here
    // that needs it, so their absence is labelled rather than left as a blank rectangle
    // — the markers still place correctly and the table below carries every number.
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap",
      maxZoom: 17,
    })
      .on("tileerror", () => setTilesOffline(true))
      .on("tileload", () => setTilesOffline(false))
      .addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    if (!map.current || !layer.current || facilities.length === 0) return;
    layer.current.clearLayers();
    for (const f of facilities) {
      L.marker([f.lat, f.lng], { icon: marker(f) })
        .bindPopup(
          `<strong>${f.name}</strong><br/>${f.district} · ${f.level.replace(/_/g, " ")}<br/>` +
            `${f.present} of ${f.doctors} doctors present<br/>${f.waiting} waiting` +
            (f.alerts ? `<br/><b>${f.alerts} alerts</b>` : ""),
        )
        .addTo(layer.current);
    }
    map.current.fitBounds(
      L.latLngBounds(
        facilities.map((f) => [f.lat, f.lng] as [number, number]),
      ).pad(0.35),
    );
  }, [facilities]);

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="fade-up">
        <Eyebrow dash>Command Center</Eyebrow>
        <h1 className="mt-3 text-[44px] leading-[0.98] tracking-[-0.04em]">
          Facility{" "}
          <span className="font-normal italic text-primary">network</span>
        </h1>
      </header>

      <Panel className="fade-up relative mt-6 overflow-hidden p-0">
        {tilesOffline && (
          <div className="absolute right-3 top-3 z-[500]">
            <SimulatedChip label="Basemap offline — positions are real" />
          </div>
        )}
        <div ref={holder} className="h-[420px] w-full bg-surface-2" />
      </Panel>

      <section
        className="fade-up mt-6"
        style={{ ["--delay" as string]: "80ms" }}
      >
        <TableShell
          columns={[
            "Facility",
            "District",
            "Level",
            "Present",
            "Waiting",
            "Alerts",
          ]}
          footer={`${facilities.length} facilities`}
        >
          {facilities.map((f) => (
            <Row key={f.hospital_id}>
              <Cell>{f.name}</Cell>
              <Cell>{f.district}</Cell>
              <Cell mono>{f.level.replace(/_/g, " ")}</Cell>
              <Cell>
                <Chip tone={f.present === 0 ? "neutral" : "success"}>
                  <span className="live-state">
                    {f.present} of {f.doctors}
                  </span>
                </Chip>
              </Cell>
              <Cell mono>{f.waiting}</Cell>
              <Cell>
                {f.alerts === 0 ? (
                  <span className="text-muted-2">—</span>
                ) : (
                  <Chip tone={SEVERITY_TONE[f.worst_severity ?? "info"]}>
                    <span className="live-state">{f.alerts}</span>
                  </Chip>
                )}
              </Cell>
            </Row>
          ))}
        </TableShell>
      </section>
    </main>
  );
}
