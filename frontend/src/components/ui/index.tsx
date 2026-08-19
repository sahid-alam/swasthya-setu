/* Base components — docs/DESIGN.md §6 (+ §9d status pairings).
   Every screen composes these; no screen re-invents a panel or a chip. */
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

const cx = (...parts: (string | false | undefined)[]) =>
  parts.filter(Boolean).join(" ");

/* --- Eyebrow: the signature mono-caps micro-label (§2) --------------------- */

export function Eyebrow({
  children,
  dash = false,
}: {
  children: ReactNode;
  dash?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
      {dash && <span className="h-px w-[22px] bg-muted-2" aria-hidden />}
      {children}
    </span>
  );
}

/* --- Panel (§4) ----------------------------------------------------------- */

export function Panel({
  children,
  raised = false,
  className,
  ...rest
}: { raised?: boolean } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "rounded-lg border border-line bg-surface",
        raised ? "shadow-2" : "shadow-1",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

/* --- Button: 5 variants x 3 sizes (§6) ------------------------------------ */

type Variant = "default" | "primary" | "accent" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANT: Record<Variant, string> = {
  default: "bg-surface border-line text-ink hover:bg-surface-2",
  primary: "bg-ink border-ink text-white hover:bg-ink-2",
  accent: "bg-accent border-accent text-ink font-semibold hover:brightness-95",
  ghost: "bg-transparent border-transparent text-ink hover:bg-surface-2",
  danger: "bg-danger border-danger text-white hover:brightness-95",
};

const SIZE: Record<Size, string> = {
  sm: "text-xs rounded-sm px-3 py-1.5",
  md: "text-[13px] rounded-sm px-[15px] py-[9px]",
  lg: "text-sm rounded-md px-5 py-3",
};

export function Button({
  variant = "default",
  size = "md",
  className,
  ...rest
}: {
  variant?: Variant;
  size?: Size;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 border font-medium transition-colors",
        "duration-200 ease-[var(--ease-default)] focus-visible:outline-none",
        "focus-visible:border-primary focus-visible:shadow-[var(--focus-ring)]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...rest}
    />
  );
}

/* --- Chip: paired soft-bg + dark-text, never solid (§3) -------------------- */

export type ChipTone =
  "success" | "warn" | "danger" | "info" | "primary" | "neutral" | "violet";

/* Values live in tokens.css (§3 pairings) — never a hex in a component. */
const TONE: Record<ChipTone, { bg: string; fg: string }> = Object.fromEntries(
  (
    [
      "success",
      "warn",
      "danger",
      "info",
      "primary",
      "neutral",
      "violet",
    ] as ChipTone[]
  ).map((t) => [t, { bg: `var(--chip-${t}-bg)`, fg: `var(--chip-${t}-fg)` }]),
) as Record<ChipTone, { bg: string; fg: string }>;

export function Chip({
  tone = "neutral",
  children,
  pulse = false,
}: {
  tone?: ChipTone;
  children: ReactNode;
  pulse?: boolean;
}) {
  const { bg, fg } = TONE[tone];
  return (
    <span
      className="inline-flex items-center gap-[5px] rounded-full px-[9px] py-[3px] text-[11px] font-medium"
      style={{ background: bg, color: fg }}
    >
      <span
        className={cx(
          "h-[5px] w-[5px] rounded-full bg-current",
          pulse && "pulse-dot",
        )}
        aria-hidden
      />
      {children}
    </span>
  );
}

/* §9d — the one place presence state maps to a colour. Text always ships with
   the dot, so status is never conveyed by colour alone (§9a projector rule). */
export const PRESENCE_TONE: Record<string, ChipTone> = {
  PRESENT_IN_DEPT: "success",
  PRESENT_ELSEWHERE: "info",
  ON_ROUNDS: "info",
  IN_SURGERY: "violet",
  ON_LEAVE: "warn",
  OFF_SHIFT: "warn",
  UNKNOWN: "neutral",
};

export function PresenceChip({
  state,
  confidence,
}: {
  state: string;
  confidence?: number;
}) {
  const label = state.replace(/_/g, " ").toLowerCase();
  return (
    <span className="inline-flex items-center gap-2">
      <Chip tone={PRESENCE_TONE[state] ?? "neutral"}>
        {/* §9a beats §6's 11px chip default: judges read this from ~3m */}
        <span className="live-state capitalize">{label}</span>
      </Chip>
      {/* low confidence is shown, never hidden behind an optimistic colour (§9d) */}
      {confidence !== undefined && confidence < 0.6 && (
        <span className="tnum text-[11px] text-muted-2">
          {Math.round(confidence * 100)}%
        </span>
      )}
    </span>
  );
}

/** Honesty is a design feature (§9d): anything mock or generated says so. */
export function SimulatedChip({ label = "SIMULATED" }: { label?: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-line-2 px-[9px] py-[3px] font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
      {label}
    </span>
  );
}

/* --- FieldBlock (§6 forms) ------------------------------------------------ */

export function FieldBlock({
  label,
  error,
  full = false,
  children,
}: {
  label: string;
  error?: string;
  full?: boolean;
  children: ReactNode;
}) {
  return (
    <label className={cx("flex flex-col gap-1.5", full && "col-span-2")}>
      <Eyebrow>{label}</Eyebrow>
      {children}
      {error && <span className="text-[11px] text-danger">{error}</span>}
    </label>
  );
}

export function Input({
  className,
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cx(
        "rounded-sm border border-line bg-surface px-3 py-2 text-[13px] transition-shadow",
        "focus:border-primary focus:shadow-[var(--focus-ring)] focus:outline-none",
        className,
      )}
      {...rest}
    />
  );
}

/* --- TableShell (§6) ------------------------------------------------------ */

export function TableShell({
  columns,
  children,
  footer,
}: {
  columns: string[];
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface shadow-1">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="bg-surface-2">
              {columns.map((c) => (
                <th
                  key={c}
                  className="px-4 py-2.5 text-left font-mono text-[10px] font-medium uppercase tracking-[0.1em] text-muted"
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{children}</tbody>
        </table>
      </div>
      {footer && (
        <div className="border-t border-line-2 px-4 py-2.5 text-[12px] text-muted">
          {footer}
        </div>
      )}
    </div>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return (
    <tr className="border-t border-line-2 transition-colors hover:bg-surface-2">
      {children}
    </tr>
  );
}

export function Cell({
  children,
  mono = false,
}: {
  children: ReactNode;
  mono?: boolean;
}) {
  return (
    <td className={cx("px-4 py-2.5", mono && "tnum text-muted")}>{children}</td>
  );
}

/* --- Empty state (§6) ----------------------------------------------------- */

export function EmptyState({
  title,
  copy,
  action,
}: {
  title: string;
  copy: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
      <div
        className="h-[84px] w-[84px] rounded-full border border-dashed border-line"
        style={{
          background:
            "radial-gradient(circle, var(--primary-100), var(--surface))",
        }}
        aria-hidden
      />
      <h3 className="text-[15px] font-semibold">{title}</h3>
      <p className="max-w-[320px] text-[13px] text-muted">{copy}</p>
      {action}
    </div>
  );
}
