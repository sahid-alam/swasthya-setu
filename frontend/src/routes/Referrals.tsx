import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  Button,
  Cell,
  Chip,
  Eyebrow,
  Panel,
  REFERRAL_TONE,
  Row,
  StatusChip,
  TableShell,
} from "../components/ui";
import {
  cancelReferral,
  confirmReferral,
  fetchReferrals,
  timeLeft,
  type Referral,
} from "../lib/facilities";

/** Referral reservations — PRD §M5, DESIGN.md §9a.
 *
 *  The countdown is the point of the screen. A hold that silently expires while a
 *  receiving hospital keeps a bed marked RESERVED is the exact failure M5 exists to
 *  prevent, so the time remaining is on the row, ticking, and it turns warn as it runs
 *  out. The backend sweeper is what actually releases it — this only shows the truth. */

const URGENCY_TONE = {
  EMERGENCY: "danger",
  URGENT: "warn",
  ROUTINE: "neutral",
} as const;

function Countdown({ referral }: { referral: Referral }) {
  // One second is the honest resolution for something a bed depends on.
  const [, tick] = useState(0);
  useEffect(() => {
    if (referral.status !== "RESERVED") return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [referral.status]);

  if (referral.status !== "RESERVED")
    return <span className="text-muted-2">—</span>;
  const left = timeLeft(referral.expires_at);
  if (!left) {
    // Elapsed on screen but the sweeper has not run yet. Say that, rather than showing
    // a confident "RESERVED" for a bed that is already going back into the pool.
    return (
      <Chip tone="warn">
        <span className="live-state">releasing…</span>
      </Chip>
    );
  }
  const minutes =
    (new Date(referral.expires_at!).getTime() - Date.now()) / 60_000;
  return (
    <Chip tone={minutes < 30 ? "warn" : "info"}>
      <span className="live-state">{left}</span>
    </Chip>
  );
}

export default function Referrals() {
  const qc = useQueryClient();
  const { data: referrals = [], isLoading } = useQuery({
    queryKey: ["referrals"],
    queryFn: fetchReferrals,
    // The sweeper releases holds on its own timer, so the screen has to re-read rather
    // than trust what it rendered a minute ago.
    refetchInterval: 15_000,
  });
  const [note, setNote] = useState("");

  const act = useMutation({
    mutationFn: ({
      id,
      action,
    }: {
      id: string;
      action: "confirm" | "cancel";
    }) => (action === "confirm" ? confirmReferral(id) : cancelReferral(id)),
    onSuccess: () => {
      setNote("");
      qc.invalidateQueries({ queryKey: ["referrals"] });
      qc.invalidateQueries({ queryKey: ["beds"] });
    },
    // A confirm that lost the race to the sweeper is a real answer, not a glitch.
    onError: (e: Error) => setNote(e.message),
  });

  const holding = referrals.filter((r) => r.status === "RESERVED").length;

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="fade-up flex flex-wrap items-end justify-between gap-4">
        <div>
          <Eyebrow dash>Command Center</Eyebrow>
          <h1 className="mt-3 text-[34px] leading-[0.98] tracking-[-0.04em] sm:text-[44px]">
            Referral{" "}
            <span className="font-normal italic text-primary">
              reservations
            </span>
          </h1>
        </div>
        <Chip tone={holding ? "info" : "neutral"}>
          <span className="live-state">{holding} bed(s) held</span>
        </Chip>
      </header>

      {note && (
        <Panel className="fade-up mt-6 border-warn p-4 text-[15px]">
          {note}
        </Panel>
      )}

      {/* Card stack on phones; the eight-column table only earns its keep on a desk. */}
      <div className="fade-up mt-7 grid gap-2 md:hidden">
        {referrals.map((r) => (
          <Panel key={r.id} className="p-4">
            <div className="flex flex-wrap items-center gap-2">
              <StatusChip state={r.status} tones={REFERRAL_TONE} />
              <Countdown referral={r} />
            </div>
            <p className="mt-3 text-[15px] font-medium">{r.patient_name}</p>
            <p className="text-[14px] text-muted">
              {r.from_hospital} → {r.to_hospital}
            </p>
            <p className="mt-1 text-[14px] text-muted">
              {r.specialty} · {r.bed ?? "no bed held"}
            </p>
            {r.status === "RESERVED" && (
              <div className="mt-4 flex gap-2">
                <Button
                  size="sm"
                  variant="accent"
                  onClick={() => act.mutate({ id: r.id, action: "confirm" })}
                >
                  Confirm
                </Button>
                <Button
                  size="sm"
                  onClick={() => act.mutate({ id: r.id, action: "cancel" })}
                >
                  Cancel
                </Button>
              </div>
            )}
          </Panel>
        ))}
      </div>

      <div className="fade-up mt-7 hidden md:block">
        <TableShell
          columns={[
            "Patient",
            "From → To",
            "Specialty",
            "Urgency",
            "Status",
            "Bed",
            "Expires",
            "",
          ]}
          footer={`${referrals.length} referral(s)${isLoading ? " · loading" : ""}`}
        >
          {referrals.map((r) => (
            <Row key={r.id}>
              <Cell>{r.patient_name}</Cell>
              <Cell>
                {r.from_hospital} → {r.to_hospital}
              </Cell>
              <Cell>{r.specialty}</Cell>
              <Cell>
                <Chip tone={URGENCY_TONE[r.urgency]}>
                  <span className="live-state">{r.urgency.toLowerCase()}</span>
                </Chip>
              </Cell>
              <Cell>
                <StatusChip state={r.status} tones={REFERRAL_TONE} />
              </Cell>
              <Cell mono>{r.bed ?? "—"}</Cell>
              <Cell>
                <Countdown referral={r} />
              </Cell>
              <Cell>
                {r.status === "RESERVED" && (
                  <span className="flex gap-2">
                    <Button
                      size="sm"
                      variant="accent"
                      onClick={() =>
                        act.mutate({ id: r.id, action: "confirm" })
                      }
                    >
                      Confirm
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => act.mutate({ id: r.id, action: "cancel" })}
                    >
                      Cancel
                    </Button>
                  </span>
                )}
              </Cell>
            </Row>
          ))}
        </TableShell>
      </div>

      {!isLoading && referrals.length === 0 && (
        <Panel className="mt-8 p-8 text-center text-[15px] text-muted">
          No referrals yet. Rank an emergency on the Golden Hour screen and
          refer from there.
        </Panel>
      )}
    </main>
  );
}
