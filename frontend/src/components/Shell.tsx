import { NavLink, Outlet } from "react-router-dom";
import { useState, type ReactNode } from "react";

import { logout } from "../lib/api";

/** Command centre chrome — DESIGN.md §4 (floating dark dock) and §9a (this is the
 *  one surface that gets the full treatment; the PWA deliberately gets none of it). */

/** One authored set: 20x20, 1.5 stroke, round caps and joins, currentColor, no fill.
 *  Unicode glyphs used to stand in here — they inherit the text face, so weight and
 *  optical size drifted per glyph and none of them lined up with each other. */
function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 20 20"
      className="h-5 w-5 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}

const NAV = [
  {
    to: "/",
    label: "Presence",
    icon: (
      <Icon>
        <circle cx="10" cy="6.5" r="3" />
        <path d="M4.2 16.3c0-2.7 2.6-4.4 5.8-4.4s5.8 1.7 5.8 4.4" />
      </Icon>
    ),
  },
  {
    to: "/queue",
    label: "Queues",
    icon: (
      <Icon>
        <path d="M8 5.5h8M8 10h8M8 14.5h8" />
        <circle cx="4.5" cy="5.5" r="1.1" />
        <circle cx="4.5" cy="10" r="1.1" />
        <circle cx="4.5" cy="14.5" r="1.1" />
      </Icon>
    ),
  },
  {
    to: "/alerts",
    label: "Alerts",
    icon: (
      <Icon>
        <path d="M10 3.6 2.8 16.4h14.4L10 3.6Z" />
        <path d="M10 8.2v3.4M10 14.1h.01" />
      </Icon>
    ),
  },
  {
    to: "/map",
    label: "Network",
    icon: (
      <Icon>
        <circle cx="10" cy="4.6" r="2.1" />
        <circle cx="4.6" cy="15.1" r="2.1" />
        <circle cx="15.4" cy="15.1" r="2.1" />
        <path d="M8.6 6.5 5.9 13.1M11.4 6.5l2.7 6.6M6.7 15.1h6.6" />
      </Icon>
    ),
  },
  {
    to: "/beds",
    label: "Beds",
    icon: (
      <Icon>
        <path d="M3 15.5V6M3 15.5h14M17 15.5v-4a2 2 0 0 0-2-2H8.5v6" />
        <circle cx="6" cy="9" r="1.6" />
      </Icon>
    ),
  },
  {
    to: "/referrals",
    label: "Referrals",
    icon: (
      <Icon>
        <path d="M3.5 6.5h9M9.5 3.5l3 3-3 3" />
        <path d="M16.5 13.5h-9M10.5 10.5l-3 3 3 3" />
      </Icon>
    ),
  },
  {
    to: "/golden-hour",
    label: "Golden Hour",
    icon: (
      <Icon>
        <circle cx="10" cy="10" r="6.8" />
        <path d="M10 6v4.2l2.8 1.7" />
      </Icon>
    ),
  },
  {
    to: "/impact",
    label: "Impact",
    icon: (
      <Icon>
        <path d="M3.5 16.5V9M8.5 16.5V4M13.5 16.5v-5M18 16.5h-16" />
      </Icon>
    ),
  },
  {
    to: "/scenarios",
    label: "Scenarios",
    icon: (
      <Icon>
        <circle cx="10" cy="10" r="6.8" />
        <path d="M8.4 7.1 13 10l-4.6 2.9V7.1Z" />
      </Icon>
    ),
  },
];

const cx = (...parts: (string | false)[]) => parts.filter(Boolean).join(" ");

export default function Shell() {
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen">
      {/* No `grain` here: DESIGN.md §4 asks for film grain on dark surfaces, but at
          the specified opacity over the dock it reads as noise rather than film. */}
      <nav
        className="dock"
        data-open={open || undefined}
        aria-label="Command centre"
      >
        <ul className="flex h-full flex-col gap-1 p-3">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === "/"}
                onClick={() => setOpen(false)}
                className="dock-item flex min-h-[44px] items-center gap-3 rounded-md px-3"
              >
                {item.icon}
                <span className="dock-label text-[14px]">{item.label}</span>
              </NavLink>
            </li>
          ))}
          {/* Pinned to the foot of the dock: a destructive action does not belong in
              the same run as the destinations. */}
          <li className="mt-auto">
            <button
              onClick={logout}
              className="dock-item flex min-h-[44px] w-full items-center gap-3 rounded-md px-3"
            >
              <Icon>
                <path d="M12.5 6V4.5A1.5 1.5 0 0 0 11 3H5a1.5 1.5 0 0 0-1.5 1.5v11A1.5 1.5 0 0 0 5 17h6a1.5 1.5 0 0 0 1.5-1.5V14" />
                <path d="M8.5 10h8M14 7.5 16.5 10 14 12.5" />
              </Icon>
              <span className="dock-label text-[14px]">Sign out</span>
            </button>
          </li>
        </ul>
      </nav>

      {/* Below lg the dock is off-canvas and this is how it comes back. A hover-to-
          expand rail has no meaning on a touch screen, and the 100px gutter it reserved
          was eating a third of a phone. */}
      <button
        onClick={() => setOpen(true)}
        aria-label="Open navigation"
        aria-expanded={open}
        className="fixed left-4 top-4 z-30 grid h-12 w-12 place-items-center rounded-md border border-line bg-surface shadow-2 lg:hidden"
      >
        <Icon>
          <path d="M3.5 5.5h13M3.5 10h13M3.5 14.5h13" />
        </Icon>
      </button>

      {/* Scrim: closes on tap, and stays out of the tree for pointers when shut. */}
      <div
        onClick={() => setOpen(false)}
        aria-hidden
        className={cx(
          "fixed inset-0 z-30 bg-ink/50 transition-opacity duration-300 lg:hidden",
          open ? "opacity-100" : "pointer-events-none opacity-0",
        )}
      />

      {/* 68px dock + 16px inset either side — but only once there is room for it. */}
      <div className="pt-20 lg:pl-[100px] lg:pt-0">
        <Outlet />
      </div>
    </div>
  );
}
