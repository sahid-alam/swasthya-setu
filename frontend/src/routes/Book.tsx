import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Button, Chip, Panel, PwaHeader } from "../components/ui";
import VoiceCall from "../components/VoiceCall";
import { api, getToken, isPatient } from "../lib/api";
import { formatWhen, getLang, setLang, t, type Lang } from "../lib/i18n";
import { enqueue, flush, pending, type Intent } from "../lib/outbox";

type Offer = {
  slot_id: string;
  doctor_name: string;
  department: string;
  hospital: string;
  starts_at: string;
};
type Dept = { id: string; name: string; hospital: string };
type Booked = {
  token_number: number | null;
  doctor_name: string;
  hospital: string;
  starts_at: string;
};

/** Patient booking — DESIGN.md §9b: tokens and type yes, flair no. No blur, no veil,
 *  no custom cursor; 48px touch targets; body copy at 15-16px, not 13. */
export default function Book() {
  const [lang, setLangState] = useState<Lang>(getLang());
  const [online, setOnline] = useState(navigator.onLine);
  const [queued, setQueued] = useState<Intent[]>(pending());
  const [depts, setDepts] = useState<Dept[]>([]);
  const [dept, setDept] = useState<string>("");
  const [offers, setOffers] = useState<Offer[]>([]);
  const [patient, setPatient] = useState<{ id: string; name: string } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Booked | null>(null);
  const [note, setNote] = useState<string>("");

  const say = (k: Parameters<typeof t>[1]) => t(lang, k);

  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  useEffect(() => {
    api<{ departments: Dept[]; patient: { id: string; name: string } }>(
      // a patient token scopes to its holder; the staff/kiosk path takes an id
      isPatient() ? "/me/context" : "/pwa/context",
    )
      .then((ctx) => {
        setDepts(ctx.departments);
        setPatient(ctx.patient);
        if (ctx.departments[0]) setDept(ctx.departments[0].id);
      })
      .catch(() => setNote(say("somethingWrong")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!dept) return;
    api<Offer[]>(
      `${isPatient() ? "/me/slots" : "/booking/slots"}?department_id=${dept}&limit=12`,
    )
      .then(setOffers)
      .catch(() => setOffers([]));
  }, [dept]);

  // whenever we are back online, drain anything booked while offline
  useEffect(() => {
    if (!online || queued.length === 0) return;
    void sync();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [online]);

  async function sync() {
    const { rejected } = await flush((i) =>
      fetch(isPatient() ? "/api/v1/me/booking" : "/api/v1/booking", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${getToken() ?? ""}`,
        },
        body: JSON.stringify({
          patient_id: i.patient_id,
          slot_id: i.slot_id,
          channel: i.channel,
        }),
      }),
    );
    setQueued(pending());
    if (rejected.length) {
      // never silently book a taken slot — say so and let them pick again
      setNote(say("somethingWrong"));
    }
  }

  async function choose(offer: Offer) {
    if (!patient) return;
    setBusy(true);
    setNote("");
    const payload = {
      patient_id: patient.id,
      slot_id: offer.slot_id,
      channel: "PWA",
      label: `${offer.doctor_name} · ${formatWhen(offer.starts_at, lang)}`,
    };

    if (!online) {
      enqueue(payload);
      setQueued(pending());
      setBusy(false);
      setNote(say("offlineBanner"));
      return;
    }
    try {
      const booked = await api<Booked>(
        isPatient() ? "/me/booking" : "/booking",
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      setDone(booked);
    } catch {
      // treat any failure as offline-ish: keep the intent rather than lose it
      enqueue(payload);
      setQueued(pending());
      setNote(say("somethingWrong"));
    } finally {
      setBusy(false);
    }
  }

  function toggleLang() {
    const next: Lang = lang === "HI" ? "EN" : "HI";
    setLang(next);
    setLangState(next);
  }

  return (
    <main className="mx-auto max-w-[560px] px-4 py-6 text-[15px]">
      <PwaHeader
        appName={say("appName")}
        switchLabel={say("switchLang")}
        onSwitch={toggleLang}
        signOutLabel={say("signOut")}
      />

      {!online && (
        <Panel className="mt-4 border-warn p-4 text-[15px]">
          {say("offlineBanner")}
        </Panel>
      )}

      {queued.length > 0 && (
        <Panel className="mt-4 flex items-center justify-between gap-3 p-4">
          <span>
            {queued.length}{" "}
            {queued.length === 1
              ? say("pendingCount")
              : say("pendingCountPlural")}
          </span>
          <Button size="lg" onClick={() => void sync()} disabled={!online}>
            {say("syncNow")}
          </Button>
        </Panel>
      )}

      {done ? (
        <Panel className="fade-up mt-6 p-6">
          <Chip tone="success">
            <span className="live-state">{say("booked")}</span>
          </Chip>
          <p className="mt-4 text-[16px]">
            {say("withDoctor")} <strong>{done.doctor_name}</strong>
          </p>
          <p className="text-[16px]">
            {done.hospital} {say("at")} {formatWhen(done.starts_at, lang)}
          </p>
          {done.token_number !== null && (
            <p className="mt-3 text-[20px]">
              {say("token")}{" "}
              <strong className="tnum">{done.token_number}</strong>
            </p>
          )}
          {/* The journey the confirmation used to dead-end: booked → where am I in line. */}
          <Link to="/my-queue" className="mt-5 block">
            <Button variant="accent" size="lg" className="min-h-[48px] w-full">
              {say("seeMyPlace")}
            </Button>
          </Link>
        </Panel>
      ) : (
        <>
          <h1 className="mt-4 text-[28px] leading-tight tracking-[-0.02em]">
            {say("bookTitle")}
          </h1>
          {patient && <p className="mt-1 text-muted">{patient.name}</p>}

          {/* Speaking is the more accessible path for a low-literacy patient, so it
              leads rather than hides under the form. Renders nothing when Vapi is
              unconfigured, and the form below books the same appointment. */}
          <div className="mt-6">
            <VoiceCall lang={lang} />
          </div>

          <label className="mt-6 block">
            <span className="text-[15px] text-muted">
              {say("chooseDepartment")}
            </span>
            <select
              value={dept}
              onChange={(e) => setDept(e.target.value)}
              className="mt-2 min-h-[48px] w-full rounded-sm border border-line bg-surface px-3 text-[16px]"
            >
              {depts.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} — {d.hospital}
                </option>
              ))}
            </select>
          </label>

          <h2 className="mt-6 text-[17px] font-semibold">
            {say("availableTimes")}
          </h2>
          {offers.length === 0 ? (
            <p className="mt-2 text-muted">{say("noTimes")}</p>
          ) : (
            <ul className="mt-3 grid gap-2">
              {offers.map((o) => (
                <li key={o.slot_id}>
                  <button
                    disabled={busy}
                    onClick={() => void choose(o)}
                    className="flex min-h-[64px] w-full items-center justify-between rounded-md border border-line bg-surface px-4 py-3 text-left disabled:opacity-50"
                  >
                    <span>
                      <span className="block text-[16px]">
                        {formatWhen(o.starts_at, lang)}
                      </span>
                      <span className="block text-[14px] text-muted">
                        {o.doctor_name}
                      </span>
                    </span>
                    <span className="text-[15px] text-primary">
                      {say("confirm")}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {note && <p className="mt-4 text-[15px] text-danger">{note}</p>}
          {busy && <p className="mt-4 text-muted">{say("booking")}</p>}
        </>
      )}
    </main>
  );
}
