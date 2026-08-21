import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useState } from "react";

import { Button, Chip, Panel, PwaHeader } from "../components/ui";
import { api, isPatient } from "../lib/api";
import { formatWhen, getLang, setLang, t, type Lang } from "../lib/i18n";

/** Mirrors MyQueueOut in backend/app/api/v1/booking.py. `position` and
 *  `predicted_wait_minutes` are both null once the slot time has passed — the
 *  patient is at the front, not "number null". */
export type QueueEntry = {
  appointment_id: string;
  doctor_name: string;
  hospital: string;
  scheduled_for: string;
  token_number: number | null;
  position: number | null;
  predicted_wait_minutes: number | null;
  status: "BOOKED" | "CHECKED_IN" | "RESCHEDULE_PENDING";
};

export type QueueState = "moving" | "now" | "waiting";

/** The whole screen turns on this. Kept pure and exported so the null-position
 *  branch is testable without a render. */
export function queueState(q: QueueEntry): QueueState {
  if (q.status === "RESCHEDULE_PENDING") return "moving";
  // Backend nulls position once starts_at is in the past: the wait is over.
  if (q.position === null) return "now";
  return "waiting";
}

/** People ahead, as dots a patient can count without reading (§9b: low literacy).
 *  Beyond nine the row stops being countable, so it becomes a number instead. */
function AheadDots({ ahead }: { ahead: number }) {
  if (ahead <= 0 || ahead > 9) return null;
  return (
    <div className="mt-4 flex items-center gap-1.5" aria-hidden>
      {Array.from({ length: ahead }).map((_, i) => (
        <span key={i} className="h-2.5 w-2.5 rounded-full bg-line" />
      ))}
      <span className="ml-1 h-3.5 w-3.5 rounded-full bg-accent" />
    </div>
  );
}

function HeroCard({ q, lang }: { q: QueueEntry; lang: Lang }) {
  const say = (k: Parameters<typeof t>[1]) => t(lang, k);
  const state = queueState(q);
  const ahead = (q.position ?? 1) - 1;

  return (
    <Panel raised className="fade-up mt-5 overflow-hidden p-6">
      <div className="flex items-start justify-between gap-3">
        {state === "moving" ? (
          <Chip tone="warn">
            <span className="live-state">{say("beingMoved")}</span>
          </Chip>
        ) : q.status === "CHECKED_IN" ? (
          <Chip tone="info">
            <span className="live-state">{say("checkedIn")}</span>
          </Chip>
        ) : (
          <Chip tone="success">
            <span className="live-state">{say("confirmed")}</span>
          </Chip>
        )}
        {q.token_number !== null && (
          <span className="shrink-0 text-right">
            <span className="block text-[14px] text-muted">{say("token")}</span>
            <span className="num-hero block text-[24px] font-medium text-ink">
              {q.token_number}
            </span>
          </span>
        )}
      </div>

      {state === "waiting" && (
        <>
          <p className="mt-6 text-[16px] text-muted">{say("positionLabel")}</p>
          {/* §7.1 contrast of scale. DM Sans, not mono: §9b makes mono staff
              decoration, and this is the one number the patient came for. */}
          <p className="num-hero mt-1 text-[76px] font-medium text-ink">
            {q.position}
          </p>
          <AheadDots ahead={ahead} />
          <p className="mt-3 text-[15px] text-muted">
            {ahead === 0
              ? say("nobodyAhead")
              : ahead === 1
                ? say("onePersonAhead")
                : `${ahead} ${say("peopleAhead")}`}
          </p>

          {q.predicted_wait_minutes !== null && (
            <div className="mt-5 border-t border-line-2 pt-5">
              <p className="text-[16px]">
                {say("waitLabel")}{" "}
                <strong className="tnum text-[20px] text-ink">
                  {q.predicted_wait_minutes}
                </strong>{" "}
                {say("minutes")}
              </p>
              {/* The wait model is trained on synthetic clinic days. Patients get
                  that as plain language, not the §9d SYNTHETIC chip, which is a
                  staff/judge signal. */}
              <p className="mt-1 text-[14px] text-muted">
                {say("waitIsEstimate")}
              </p>
            </div>
          )}
        </>
      )}

      {state === "now" && (
        <div className="mt-6 rounded-md bg-accent-100 px-5 py-6">
          <p className="text-[28px] font-medium tracking-[-0.02em] text-ink">
            {say("yourTurn")}
          </p>
          <p className="mt-1 text-[16px] text-muted">{say("yourTurnHelp")}</p>
        </div>
      )}

      {state === "moving" && (
        <div className="mt-6">
          <p className="text-[20px] font-medium tracking-[-0.01em]">
            {say("beingMovedHelp")}
          </p>
        </div>
      )}

      <div className="mt-6 border-t border-line-2 pt-4 text-[15px] text-muted">
        <p>
          {say("withDoctor")}{" "}
          <strong className="font-medium text-ink">{q.doctor_name}</strong>
        </p>
        <p className="mt-0.5">
          {q.hospital} {say("at")} {formatWhen(q.scheduled_for, lang)}
        </p>
      </div>
    </Panel>
  );
}

function OtherRow({ q, lang }: { q: QueueEntry; lang: Lang }) {
  const say = (k: Parameters<typeof t>[1]) => t(lang, k);
  const state = queueState(q);
  return (
    <li className="flex min-h-[48px] items-center justify-between gap-3 border-t border-line-2 px-4 py-3 first:border-t-0">
      <span>
        <span className="block text-[15px]">
          {formatWhen(q.scheduled_for, lang)}
        </span>
        <span className="block text-[14px] text-muted">{q.doctor_name}</span>
      </span>
      {state === "moving" ? (
        <Chip tone="warn">{say("beingMoved")}</Chip>
      ) : state === "now" ? (
        <Chip tone="success">{say("yourTurn")}</Chip>
      ) : (
        <span className="flex shrink-0 items-baseline gap-1.5">
          {/* Sans, not the mono micro-label: JetBrains Mono has no Devanagari, and
              §9b bars mono micro-caps from carrying patient information at all. */}
          <span className="text-[14px] text-muted">{say("positionLabel")}</span>
          <span className="num-hero text-[22px] font-medium text-ink">
            {q.position}
          </span>
        </span>
      )}
    </li>
  );
}

/** Patient queue position — PRD §M3. DESIGN.md §9b: tokens and type yes, flair no.
 *  No blur, no veil, no grain, no custom cursor; fade-up is the only motion. */
export default function MyQueue() {
  const [lang, setLangState] = useState<Lang>(getLang());
  const say = (k: Parameters<typeof t>[1]) => t(lang, k);

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["my-queue"],
    // A patient token scopes to its holder; the staff/kiosk path takes an id,
    // exactly as Book.tsx branches.
    queryFn: async (): Promise<QueueEntry[]> => {
      if (isPatient()) return api<QueueEntry[]>("/me/queue");
      const ctx = await api<{ patient: { id: string } }>("/pwa/context");
      return api<QueueEntry[]>(`/pwa/my-queue/${ctx.patient.id}`);
    },
    // The queue moves while the patient is looking at it. No socket: /ws/dashboard
    // is staff- and hospital-scoped, and a poll survives a flaky waiting-room signal.
    refetchInterval: 20_000,
  });

  function toggleLang() {
    const next: Lang = lang === "HI" ? "EN" : "HI";
    setLang(next);
    setLangState(next);
  }

  const [first, ...rest] = data ?? [];

  return (
    <main className="mx-auto max-w-[560px] px-4 py-6 text-[15px]">
      <PwaHeader
        appName={say("appName")}
        switchLabel={say("switchLang")}
        onSwitch={toggleLang}
        signOutLabel={say("signOut")}
      />

      <h1 className="mt-4 text-[28px] leading-tight tracking-[-0.02em]">
        {say("myQueue")}
      </h1>

      {isLoading && (
        <div className="skeleton mt-5 h-[260px] rounded-lg" aria-hidden />
      )}

      {isError && (
        <Panel className="mt-5 p-5">
          <p className="text-[15px] text-danger">{say("somethingWrong")}</p>
          <Button
            size="lg"
            className="mt-4 min-h-[48px]"
            onClick={() => void refetch()}
          >
            {say("tryAgain")}
          </Button>
        </Panel>
      )}

      {data && data.length === 0 && (
        <Panel className="fade-up mt-5">
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <div
              className="h-[84px] w-[84px] rounded-full border border-dashed border-line"
              style={{
                background:
                  "radial-gradient(circle, var(--primary-100), var(--surface))",
              }}
              aria-hidden
            />
            <h2 className="text-[17px] font-semibold">{say("noQueue")}</h2>
            <p className="max-w-[320px] text-[15px] text-muted">
              {say("noQueueCopy")}
            </p>
            <Link to="/book" className="mt-1">
              <Button variant="accent" size="lg" className="min-h-[48px]">
                {say("bookTitle")}
              </Button>
            </Link>
          </div>
        </Panel>
      )}

      {first && <HeroCard q={first} lang={lang} />}

      {rest.length > 0 && (
        <section className="mt-7">
          <h2 className="text-[17px] font-semibold">{say("alsoBooked")}</h2>
          <Panel
            className="fade-up mt-3 overflow-hidden"
            style={{ "--delay": "80ms" } as React.CSSProperties}
          >
            <ul>
              {rest.map((q) => (
                <OtherRow key={q.appointment_id} q={q} lang={lang} />
              ))}
            </ul>
          </Panel>
        </section>
      )}

      {/* The empty state carries its own single CTA; repeating it here — next to a
          "check again" for a queue that is empty — was two dead controls. */}
      {data && data.length > 0 && (
        <div className="mt-7 flex items-center gap-3">
          <Button
            size="lg"
            className="min-h-[48px] flex-1"
            onClick={() => void refetch()}
            disabled={isFetching}
          >
            {say("refresh")}
          </Button>
          <Link to="/book" className="flex-1">
            <Button size="lg" className="min-h-[48px] w-full">
              {say("backToBook")}
            </Button>
          </Link>
        </div>
      )}
    </main>
  );
}
