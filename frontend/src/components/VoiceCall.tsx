import { useEffect, useRef, useState } from "react";

import { Button, Chip } from "./ui";
import { t, type Lang } from "../lib/i18n";

/** Book by speaking — PRD §M3 (patient access), so it lives on the patient PWA.
 *
 *  It used to sit in the command centre, which was a category error: it books
 *  appointments, and staff already have the booking form. DESIGN.md §9b applies here,
 *  not §9a — 48px target, patient language, no flair.
 *
 *  Vapi runs the speech in the browser with the PUBLIC key; the assistant's tools call
 *  our booking API from Vapi's servers, so booking only works once the backend has a
 *  public URL. Unconfigured, this renders nothing at all — a patient must never be
 *  shown an env var, and the form below books the same appointment. The IVR phone line
 *  books it with no internet whatsoever (Iron Rule 4). */

const PUBLIC_KEY = import.meta.env.VITE_VAPI_PUBLIC_KEY as string | undefined;
const ASSISTANT_ID = import.meta.env.VITE_VAPI_ASSISTANT_ID as
  string | undefined;

type State = "idle" | "connecting" | "live" | "ended" | "error";

const TONE = {
  idle: "neutral",
  connecting: "info",
  live: "success",
  ended: "neutral",
  error: "danger",
} as const;

const STATUS_KEY = {
  idle: "voiceReady",
  connecting: "voiceConnecting",
  live: "voiceListening",
  ended: "voiceEnded",
  error: "voiceFailed",
} as const;

export default function VoiceCall({ lang }: { lang: Lang }) {
  const [state, setState] = useState<State>("idle");
  const [failed, setFailed] = useState(false);
  // The SDK opens a mic and a websocket; one instance, torn down on unmount, or a
  // navigation away leaves a live call running with nothing on screen to stop it.
  const vapi = useRef<import("@vapi-ai/web").default | null>(null);

  useEffect(() => {
    return () => {
      vapi.current?.stop();
      vapi.current = null;
    };
  }, []);

  const say = (k: Parameters<typeof t>[1]) => t(lang, k);

  // Not configured: offer nothing rather than a dead button or a developer message.
  if (!PUBLIC_KEY || !ASSISTANT_ID) return null;

  async function start() {
    setState("connecting");
    setFailed(false);
    try {
      const { default: Vapi } = await import("@vapi-ai/web");
      const client = (vapi.current ??= new Vapi(PUBLIC_KEY!));
      client.on("call-start", () => setState("live"));
      client.on("call-end", () => setState("ended"));
      client.on("error", () => {
        setState("error");
        setFailed(true);
      });
      await client.start(ASSISTANT_ID!);
    } catch {
      // The reason is for the console, not for a patient standing in a corridor.
      setState("error");
      setFailed(true);
    }
  }

  function stop() {
    vapi.current?.stop();
    setState("ended");
  }

  return (
    <div className="flex flex-col gap-3">
      <Button
        variant={state === "live" ? "default" : "accent"}
        size="lg"
        className="min-h-[56px] w-full text-[16px]"
        onClick={state === "live" ? stop : () => void start()}
        disabled={state === "connecting"}
      >
        {state === "live" ? say("endCall") : say("talkToAgent")}
      </Button>
      <div className="flex items-center gap-2">
        {/* Status is never colour alone — chip text and dot together */}
        <Chip tone={TONE[state]}>
          <span className="live-state">{say(STATUS_KEY[state])}</span>
        </Chip>
      </div>
      {/* Names the recovery, not the error: the form below still works. */}
      {failed && (
        <p className="text-[15px] text-danger">{say("voiceFailedHelp")}</p>
      )}
    </div>
  );
}
