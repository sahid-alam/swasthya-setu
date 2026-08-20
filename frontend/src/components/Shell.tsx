import { NavLink, Outlet } from "react-router-dom";

/** Command centre chrome — DESIGN.md §4 (floating dark dock) and §9a (this is the
 *  one surface that gets the full treatment; the PWA deliberately gets none of it). */

const NAV = [
  { to: "/", label: "Presence", glyph: "◉" },
  { to: "/queue", label: "Queues", glyph: "≡" },
  { to: "/alerts", label: "Alerts", glyph: "!" },
  { to: "/map", label: "Network", glyph: "⌖" },
  { to: "/scenarios", label: "Scenarios", glyph: "▶" },
  { to: "/dev/ui", label: "Design", glyph: "◆" },
];

export default function Shell() {
  return (
    <div className="min-h-screen">
      <nav className="dock grain" aria-label="Command centre">
        <ul className="flex h-full flex-col gap-1 p-3">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === "/"}
                className="dock-item flex min-h-[44px] items-center gap-3 rounded-md px-3"
              >
                <span
                  aria-hidden
                  className="w-5 shrink-0 text-center text-[16px]"
                >
                  {item.glyph}
                </span>
                <span className="dock-label text-[14px]">{item.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      {/* 68px dock + 16px inset either side */}
      <div className="pl-[100px]">
        <Outlet />
      </div>
    </div>
  );
}
