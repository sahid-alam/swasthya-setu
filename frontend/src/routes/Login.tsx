import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button, Eyebrow, FieldBlock, Input, Panel } from "../components/ui";
import { login } from "../lib/api";

export default function Login() {
  const nav = useNavigate();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await login(phone, password);
      nav("/");
    } catch {
      setError("Phone number or password is incorrect.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <Panel raised className="fade-up w-full max-w-[420px] p-8">
        <Eyebrow dash>Command Center</Eyebrow>
        <h1 className="mt-4 text-[32px] leading-[1.05] tracking-[-0.03em]">
          Swasthya<span className="font-normal italic text-primary">-Setu</span>
        </h1>
        <p className="mt-2 text-[13px] text-muted">
          Doctor availability and appointment allocation for Himachal Pradesh.
        </p>

        <form onSubmit={submit} className="mt-7 grid gap-4">
          <FieldBlock label="Phone number">
            <Input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              autoComplete="username"
              inputMode="numeric"
              required
            />
          </FieldBlock>
          <FieldBlock label="Password" error={error}>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </FieldBlock>
          <Button type="submit" variant="accent" size="lg" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Panel>
    </main>
  );
}
