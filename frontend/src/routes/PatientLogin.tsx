import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button, Eyebrow, FieldBlock, Input, Panel } from "../components/ui";
import { setToken } from "../lib/api";
import { getLang, setLang, t, type Lang } from "../lib/i18n";

/** Patient login by phone OTP. DESIGN.md §9b: no flair, 48px+ targets, Hindi first.
 *  The code arrives by SMS — in dev, the mock adapter puts it in the outbox. */
export default function PatientLogin() {
  const nav = useNavigate();
  const [lang, setLangState] = useState<Lang>(getLang());
  const [phone, setPhone] = useState("");
  // Phone is the default because it is what most patients in Himachal have; email is
  // the way in for someone whose handset drops SMS.
  const [via, setVia] = useState<"phone" | "email">("phone");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [stage, setStage] = useState<"phone" | "code">("phone");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const say = (k: Parameters<typeof t>[1]) => t(lang, k);
  // The API takes exactly one of the two; sending both is a 422.
  const contact = () => (via === "phone" ? { phone } : { email });

  async function requestCode(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await fetch("/api/v1/auth/otp/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(contact()),
      });
      // the answer is the same whether or not the number is on file, by design
      setNote(say("codeSent"));
      setStage("code");
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/v1/auth/otp/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...contact(), code }),
      });
      if (!res.ok) {
        setError(say("codeWrong"));
        return;
      }
      setToken((await res.json()).access_token);
      nav("/book");
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
    <main className="mx-auto grid min-h-screen max-w-[460px] place-items-center px-4 text-[15px]">
      <Panel className="fade-up w-full p-7">
        <div className="flex items-center justify-between">
          <Eyebrow dash>{say("appName")}</Eyebrow>
          <button
            onClick={toggleLang}
            className="min-h-[48px] px-3 text-[15px] text-primary underline"
          >
            {say("switchLang")}
          </button>
        </div>

        <h1 className="mt-4 text-[26px] leading-tight tracking-[-0.02em]">
          {say("signIn")}
        </h1>

        {stage === "phone" ? (
          <form onSubmit={requestCode} className="mt-6 grid gap-4">
            {via === "phone" ? (
              <FieldBlock label={say("phoneLabel")}>
                <Input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  inputMode="numeric"
                  autoComplete="tel"
                  className="min-h-[48px] text-[17px]"
                  required
                />
              </FieldBlock>
            ) : (
              <FieldBlock label={say("emailLabel")}>
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  inputMode="email"
                  autoComplete="email"
                  className="min-h-[48px] text-[17px]"
                  required
                />
              </FieldBlock>
            )}
            <Button type="submit" variant="accent" size="lg" disabled={busy}>
              {say("sendCode")}
            </Button>
            <button
              type="button"
              onClick={() => setVia(via === "phone" ? "email" : "phone")}
              className="min-h-[48px] text-[15px] text-primary underline"
            >
              {say(via === "phone" ? "useEmail" : "usePhone")}
            </button>
          </form>
        ) : (
          <form onSubmit={verify} className="mt-6 grid gap-4">
            {note && <p className="text-[15px] text-muted">{note}</p>}
            <FieldBlock label={say("codeLabel")} error={error}>
              <Input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                className="tnum min-h-[48px] text-[22px] tracking-[0.3em]"
                required
              />
            </FieldBlock>
            <Button type="submit" variant="accent" size="lg" disabled={busy}>
              {say("verify")}
            </Button>
            <button
              type="button"
              onClick={() => {
                setStage("phone");
                setCode("");
                setError("");
              }}
              className="min-h-[48px] text-[15px] text-primary underline"
            >
              {say("changeNumber")}
            </button>
          </form>
        )}
      </Panel>
    </main>
  );
}
