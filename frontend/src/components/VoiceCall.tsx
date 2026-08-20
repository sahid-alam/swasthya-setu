import { useEffect, useRef, useState } from "react";

import { Button, Chip } from "./ui";

/** Talk to the booking agent from the dashboard — DESIGN.md §9a (command centre).
 *
 *  Vapi runs the speech in the browser with the PUBLIC key; the assistant's tools call
 *  our booking API from Vapi's servers, so booking only works once the backend has a
 *  public URL. Unconfigured, this says so instead of failing mid-sentence — the phone
 *  line books the same appointment with no internet at all (Iron Rule 4). */

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

export default function VoiceCall() {
  const [state, setState] = useState<State>("idle");
  const [detail, setDetail] = useState("");
  // The SDK opens a mic and a websocket; one instance, torn down on unmount, or a
  // navigation away leaves a live call running with nothing on screen to stop it.
  const vapi = useRef<import("@vapi-ai/web").default | null>(null);

  useEffect(() => {
    return () => {
      vapi.current?.stop();
      vapi.current = null;
    };
  }, []);

  if (!PUBLIC_KEY || !ASSISTANT_ID) {
    return (
      <div className="flex items-center gap-3">
        <Chip tone="neutral">Voice agent not configured</Chip>
        <span className="text-[13px] text-muted">
          Set VITE_VAPI_PUBLIC_KEY and VITE_VAPI_ASSISTANT_ID. The IVR line
          still books.
        </span>
      </div>
    );
  }

  async function start() {
    setState("connecting");
    setDetail("");
    try {
      const { default: Vapi } = await import("@vapi-ai/web");
      const client = (vapi.current ??= new Vapi(PUBLIC_KEY!));
      client.on("call-start", () => setState("live"));
      client.on("call-end", () => setState("ended"));
      client.on("error", (e: unknown) => {
        setState("error");
        setDetail(e instanceof Error ? e.message : String(e));
      });
      await client.start(ASSISTANT_ID!);
    } catch (e) {
      setState("error");
      setDetail(e instanceof Error ? e.message : "could not start the call");
    }
  }

  function stop() {
    vapi.current?.stop();
    setState("ended");
  }

  return (
    <div className="flex items-center gap-3">
      <Button
        variant={state === "live" ? "ghost" : "accent"}
        onClick={state === "live" ? stop : () => void start()}
        disabled={state === "connecting"}
      >
        {state === "live" ? "End call" : "Talk to the booking agent"}
      </Button>
      {/* §9a: status is never colour alone — chip text and dot together */}
      <Chip tone={TONE[state]}>
        <span className="live-state">
          {state === "live"
            ? "Listening"
            : state === "connecting"
              ? "Connecting"
              : state === "error"
                ? "Call failed"
                : state === "ended"
                  ? "Call ended"
                  : "Voice agent ready"}
        </span>
      </Chip>
      {detail && <span className="text-[13px] text-danger">{detail}</span>}
    </div>
  );
}
