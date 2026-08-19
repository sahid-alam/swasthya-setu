/* Visual verification page for the design system — every token and component in
   docs/DESIGN.md §1/§6/§9d rendered once, so drift is visible at a glance. */
import { useState } from "react";

import {
  Button,
  Cell,
  Chip,
  type ChipTone,
  EmptyState,
  Eyebrow,
  FieldBlock,
  Input,
  Panel,
  PresenceChip,
  Row,
  SimulatedChip,
  TableShell,
} from "../components/ui";
import { api } from "../lib/api";

const TONES: ChipTone[] = [
  "success",
  "warn",
  "danger",
  "info",
  "primary",
  "neutral",
  "violet",
];
const PRESENCE = [
  "PRESENT_IN_DEPT",
  "PRESENT_ELSEWHERE",
  "ON_ROUNDS",
  "IN_SURGERY",
  "ON_LEAVE",
  "OFF_SHIFT",
  "UNKNOWN",
];
const SWATCHES = [
  "ink",
  "primary",
  "accent",
  "bg",
  "surface-2",
  "line",
  "muted",
  "danger",
  "warn",
  "info",
];

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="fade-up mt-10">
      <Eyebrow dash>{title}</Eyebrow>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export default function DevUI() {
  const [sent, setSent] = useState<string>();

  async function publish() {
    const topic = "presence.changed";
    await api("/dev/publish", {
      method: "POST",
      body: JSON.stringify({
        topic,
        payload: {
          doctor_id: "demo",
          old: "UNKNOWN",
          new: "PRESENT_IN_DEPT",
          confidence: 0.92,
        },
      }),
    });
    setSent(new Date().toLocaleTimeString());
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <Eyebrow dash>Design system</Eyebrow>
      <h1 className="mt-3 text-[44px] leading-[0.98] tracking-[-0.04em]">
        MediCore <span className="font-normal italic text-primary">tokens</span>
      </h1>

      <Section title="Colour">
        <div className="flex flex-wrap gap-3">
          {SWATCHES.map((c) => (
            <div key={c} className="w-[92px]">
              {/* var(), not `bg-${c}` — tailwind can't see a class built at runtime */}
              <div
                className="h-14 rounded-sm border border-line"
                style={{ background: `var(--color-${c})` }}
              />
              <div className="mt-1.5 font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
                {c}
              </div>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Type scale">
        <Panel className="grid gap-3 p-6">
          <div className="text-[44px] leading-[0.98] tracking-[-0.04em]">
            Hero{" "}
            <span className="font-normal italic text-primary">headline</span>
          </div>
          <div className="text-[16px] font-semibold tracking-[-0.01em]">
            Section title
          </div>
          <div className="text-[13px]">Body and table text at 13px.</div>
          <div className="text-[20px] font-medium tracking-[-0.02em]">
            Stat value 128
          </div>
          <Eyebrow>Eyebrow micro-label</Eyebrow>
          <div className="tnum text-[13px]">1234567890 · tabular numerals</div>
        </Panel>
      </Section>

      <Section title="Buttons">
        <div className="flex flex-wrap items-center gap-3">
          {(["default", "primary", "accent", "ghost", "danger"] as const).map(
            (v) => (
              <Button key={v} variant={v}>
                {v}
              </Button>
            ),
          )}
          <Button size="sm">small</Button>
          <Button size="lg" variant="accent">
            large
          </Button>
          <Button disabled>disabled</Button>
        </div>
      </Section>

      <Section title="Chips">
        <div className="flex flex-wrap gap-2">
          {TONES.map((t) => (
            <Chip key={t} tone={t}>
              {t}
            </Chip>
          ))}
          <Chip tone="danger" pulse>
            critical
          </Chip>
          <SimulatedChip />
          <SimulatedChip label="Synthetic data" />
        </div>
      </Section>

      <Section title="Presence states (§9d)">
        <div className="flex flex-wrap gap-3">
          {PRESENCE.map((s) => (
            <PresenceChip
              key={s}
              state={s}
              confidence={s === "UNKNOWN" ? 0.31 : 0.94}
            />
          ))}
        </div>
      </Section>

      <Section title="Form">
        <Panel className="grid grid-cols-2 gap-3.5 p-6">
          <FieldBlock label="Doctor name">
            <Input defaultValue="Dr. Sunita Sharma" />
          </FieldBlock>
          <FieldBlock label="Badge id">
            <Input defaultValue="BADGE-1004" />
          </FieldBlock>
          <FieldBlock label="Department" error="Select a department" full>
            <Input placeholder="General Medicine" />
          </FieldBlock>
        </Panel>
      </Section>

      <Section title="Table">
        <TableShell
          columns={["Doctor", "Department", "State"]}
          footer="3 of 30 doctors"
        >
          {[
            ["Dr. Rajesh Thakur", "General Medicine", "PRESENT_IN_DEPT"],
            ["Dr. Deepak Bhardwaj", "Orthopaedics", "IN_SURGERY"],
            ["Dr. Sunita Sharma", "Paediatrics", "UNKNOWN"],
          ].map(([n, d, s]) => (
            <Row key={n}>
              <Cell>{n}</Cell>
              <Cell>{d}</Cell>
              <Cell>
                <PresenceChip
                  state={s}
                  confidence={s === "UNKNOWN" ? 0.22 : 0.9}
                />
              </Cell>
            </Row>
          ))}
        </TableShell>
      </Section>

      <Section title="Empty state">
        <Panel>
          <EmptyState
            title="No doctors on shift"
            copy="Nobody is rostered for this department right now."
            action={<Button variant="accent">Add a shift</Button>}
          />
        </Panel>
      </Section>

      <Section title="Event round-trip">
        <Panel className="flex items-center gap-4 p-6">
          <Button variant="primary" onClick={publish}>
            Publish presence.changed
          </Button>
          <span className="text-[13px] text-muted">
            {sent
              ? `Published at ${sent} — check /`
              : "Opens on the dashboard with no refresh."}
          </span>
        </Panel>
      </Section>
    </main>
  );
}
