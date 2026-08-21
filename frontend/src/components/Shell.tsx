import { NavLink, Outlet } from "react-router-dom";
import type { ReactNode } from "react";

import VoiceCall from "./VoiceCall";

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

export default function Shell() {
  return (
    <div className="min-h-screen">
      {/* No `grain` here: DESIGN.md §4 asks for film grain on dark surfaces, but at
          the specified opacity over the dock it reads as noise rather than film. */}
      <nav className="dock" aria-label="Command centre">
        <ul className="flex h-full flex-col gap-1 p-3">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === "/"}
                className="dock-item flex min-h-[44px] items-center gap-3 rounded-md px-3"
              >
                {item.icon}
                <span className="dock-label text-[14px]">{item.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      {/* 68px dock + 16px inset either side */}
      <div className="pl-[100px]">
        <div className="flex justify-end px-6 pt-4">
          <VoiceCall />
        </div>
        <Outlet />
      </div>
    </div>
  );
}
