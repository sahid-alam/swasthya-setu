import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  Cell,
  Chip,
  EmptyState,
  Eyebrow,
  Panel,
  Row,
  TableShell,
} from "../components/ui";
import { dashboardSocket } from "../lib/api";

type Event = { topic: string; payload: Record<string, unknown> };

/** Phase 0 shell: proves events arrive without a refresh button anywhere (M4).
 *  The real presence board, queues and map land in Phase 1D. */
export default function Dashboard() {
  const [events, setEvents] = useState<Event[]>([]);
  const [live, setLive] = useState(false);

  useEffect(() => {
    const ws = dashboardSocket();
    ws.onclose = () => setLive(false);
    ws.onmessage = (m) => {
      const event: Event = JSON.parse(m.data);
      // an open socket is not yet a subscribed one — wait for the server to say so
      if (event.topic === "ws.ready") return setLive(true);
      setEvents((prev) => [event, ...prev].slice(0, 50));
    };
    return () => ws.close();
  }, []);

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <header className="fade-up flex items-end justify-between">
        <div>
          <Eyebrow dash>Command Center</Eyebrow>
          <h1 className="mt-3 text-[34px] leading-[0.98] tracking-[-0.04em] sm:text-[44px]">
            Live <span className="font-normal italic text-primary">signal</span>{" "}
            feed
          </h1>
        </div>
        <Chip tone={live ? "success" : "neutral"} pulse={live}>
          <span className="live-state">
            {live ? "Connected" : "Disconnected"}
          </span>
        </Chip>
      </header>

      <Panel
        className="fade-up mt-8 p-0"
        style={{ ["--delay" as string]: "80ms" }}
      >
        {events.length === 0 ? (
          <EmptyState
            title="Waiting for events"
            copy="Nothing has been published yet. Publish one from /dev/ui and it appears here without a refresh."
            action={
              <Link className="text-[13px] text-primary underline" to="/dev/ui">
                Open /dev/ui
              </Link>
            }
          />
        ) : (
          <TableShell
            columns={["Topic", "Payload"]}
            footer={`${events.length} event${events.length === 1 ? "" : "s"} this session`}
          >
            {events.map((e, i) => (
              <Row key={i}>
                <Cell>
                  <span className="font-mono text-[12px]">{e.topic}</span>
                </Cell>
                <Cell mono>{JSON.stringify(e.payload)}</Cell>
              </Row>
            ))}
          </TableShell>
        )}
      </Panel>
    </main>
  );
}
