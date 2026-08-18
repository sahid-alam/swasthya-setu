# DESIGN.md — MediCore Design Language

A portable design system extracted from the MediCore Hospital Management UI.
Aesthetic in one line: **light editorial workspace + dark glassmorphic chrome — near-black ink, deep blue primary, mint accent, mono-caps micro-labels, oversized kinetic headlines, and cinematic dark-veil transitions.**

---

## 1. Design Tokens (copy-paste)

```css
:root {
  /* Ink (near-black, used for text AND dark surfaces/buttons) */
  --ink:         #0a0e14;
  --ink-2:       #11161e;

  /* Brand */
  --primary:     #0F4C81;   /* deep blue — headings accent, focus rings */
  --primary-700: #0a3a64;
  --primary-100: #e7eef8;
  --accent:      #00C49F;   /* mint — CTAs, active states, success */
  --accent-100:  #e0f7f1;

  /* Surfaces (light, cool-tinted) */
  --bg:          #f5f7fb;   /* app background */
  --surface:     #ffffff;   /* cards, panels */
  --surface-2:   #fafbfd;   /* hover, table headers */
  --line:        #e3e8f0;   /* borders */
  --line-2:      #eef1f6;   /* subtle dividers, row borders */
  --muted:       #6b7588;   /* secondary text */
  --muted-2:     #98a1b3;   /* tertiary text */

  /* Semantic (muted, not neon) */
  --danger:      #e0526b;
  --warn:        #f0a637;
  --info:        #5a8def;
  --success:     #00C49F;

  /* Radii — generous, rounder as elements get bigger */
  --r-xs: 6px;  --r-sm: 10px;  --r-md: 14px;  --r-lg: 20px;  --r-xl: 28px;

  /* Shadows — blue-tinted, soft, large-blur */
  --sh-1:   0 1px 0 rgba(15,20,30,0.04), 0 1px 2px rgba(15,20,30,0.04);
  --sh-2:   0 6px 24px -8px rgba(15,40,90,0.12), 0 2px 6px rgba(15,40,90,0.06);
  --sh-pop: 0 24px 60px -20px rgba(10,30,70,0.25), 0 4px 12px rgba(10,30,70,0.06);

  /* Type */
  --f-sans: 'DM Sans', ui-sans-serif, system-ui, sans-serif;
  --f-mono: 'JetBrains Mono', ui-monospace, monospace;
}
```

```css
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400;1,9..40,500&family=JetBrains+Mono:wght@400;500;600&display=swap');
```

Chart / data-series palette (in order): `#5a8def` `#00C49F` `#f0a637` `#9b8ef0` `#e07ab5` `#e0526b`

---

## 2. Typography

Base: `html { font-size: 14px; font-family: var(--f-sans); -webkit-font-smoothing: antialiased; }`

| Role | Spec |
|---|---|
| Hero headline | DM Sans 500, `clamp(40px, 7vw, 96px)`, `letter-spacing: -0.04em`, `line-height: 0.94`. One word italicized 400-weight in `--primary` for contrast. |
| Section title | 15–17px, 600, `-0.01em` |
| Body / table | 13px, 400–500 |
| Stat value | 20px, 500, `-0.02em` |
| **Eyebrow / micro-label** | Mono 10–11px, uppercase, `letter-spacing: 0.08–0.14em`, `--muted`. THE signature detail — used on section labels, table headers, form labels, stat keys. Hero eyebrow gets a `22px × 1px` dash before it. |
| Numbers/IDs | Mono, `font-feature-settings: "tnum"` for counters |

Rules: negative tracking on everything sans (−0.005 to −0.04em, larger = tighter); positive wide tracking only on mono uppercase micro-text. Never bold above 600 except tiny brand marks.

---

## 3. Color Usage Rules

- **Ink is the workhorse**: primary buttons are `--ink` (not blue), toasts are ink-dark, the sidebar/veils are `#0a0e14`. Blue and mint are accents, not fills.
- **Accent (`#00C49F`) is earned**: the single loudest CTA, active nav state (`rgba(0,196,159,0.15)` bg + mint icon), brand mark gradient `linear-gradient(135deg, #00C49F, #25e0bb)`, live/pulse dots.
- **Primary blue** appears in: italic hero word, focus rings `0 0 0 3px rgba(15,76,129,0.1)`, links/actions, spinner.
- Status chips use *paired* soft-bg + dark-text, never solid:
  - success `#e0f7f1` / `#00785f` · warn `#fff1dc` / `#a26302` · danger `#fde4e8` / `#b32a44` · info `#e6efff` / `#2a55ab` · primary `--primary-100` / `--primary` · neutral `--line-2` / `--muted`
  - Chip anatomy: pill (`border-radius: 999px`), 11px 500, 3px 9px padding, 5px `currentColor` dot.
- Ambient depth on hero areas: huge blurred radial "blobs" (`filter: blur(44–56px)`) of primary/accent at 3–15% opacity, plus a faint diagonal gradient wash.

---

## 4. Surfaces & Chrome

**Light workspace, dark chrome.** Content lives on white panels over `--bg`; navigation and transitions are near-black.

- **Panel/card**: `--surface`, `1px solid --line`, `--r-lg` (20px), `--sh-1`. Elevation raises to `--sh-2`, modals get `--sh-pop` + `--r-xl`.
- **Floating dark dock sidebar** (signature): fixed with 16px inset gap on all sides, 20px radius, `rgba(10,14,20,0.88)` + `backdrop-filter: blur(20px) saturate(160%)`, `1px solid rgba(255,255,255,0.07)`, inset top highlight `inset 0 1px 0 rgba(255,255,255,0.06)`, heavy black shadow. Collapsed 68px → expands to 220px on hover (`300ms cubic-bezier(0.2, 0.8, 0.2, 1)`); labels fade/slide in with 60ms delay.
- **Film grain**: SVG `feTurbulence` noise data-URI overlaid at 0.18–0.22 opacity on all dark surfaces (sidebar, transition veil). This kills the "flat CSS" look.
- On dark: text at white 0.55 opacity resting → 0.9 on hover; hairlines at `rgba(255,255,255,0.06–0.07)`.

---

## 5. Motion

One easing family everywhere:

| Curve | Use |
|---|---|
| `cubic-bezier(0.2, 0.8, 0.2, 1)` | **Default** — entrances, hovers, layout (220–480ms) |
| `cubic-bezier(0.77, 0, 0.18, 1)` | Dramatic sweeps — page veil, boot exit (700–800ms) |
| `cubic-bezier(0.2, 0.7, 0.2, 1)` | Long kinetic text reveals (900ms) |

Signature moves:
- **Page transition veil**: full-screen `#0a0e14` layer sweeps bottom→top in (700ms), shows a giant page-name in white (`clamp(48px, 9vw, 132px)`, −0.04em) with a small mono index number, then sweeps out top. Grain + soft radial halftone on the veil.
- **Kinetic text reveal**: headlines split into words, each wrapped in `overflow: hidden`; inner span starts `translateY(105%)` and rises with per-word `transition-delay: var(--d)` stagger.
- **Fade-up**: `opacity: 0; translateY(16px)` → in, 680ms, staggered via `--delay`.
- **Modal in**: `translateY(18px) scale(0.97)` → identity, 340ms. Drawer slides from right. Backdrop `rgba(10,14,20,0.48)` + `blur(2px)`, 220ms fade.
- **Custom cursor** (desktop only, `@media (pointer: fine)`): native cursor hidden; a 28px blurred primary-blue blob with `mix-blend-mode: multiply` + a 5px ink dot. Grows to 72px mint on interactive hover, becomes a 4×22px caret over text, shrinks on press. Disabled entirely on touch.
- Micro: skeleton shimmer (1.4s linear gradient sweep), pulsing accent dot with `box-shadow: 0 0 8px var(--accent)` glow, progress bars animate width 800ms, magnetic buttons (240ms transform follow).

---

## 6. Components

**Buttons** — 13px 500, 10px radius, 9px 15px padding, `1px` border:
- default: white/`--line` border · `.primary`: **ink** bg, white text · `.accent`: mint bg, *ink* text, 600 · `.ghost`: transparent · `.danger`: `--danger`
- sizes: `.sm` 12px/8px-radius, `.lg` 14px/12px-radius, `.icon-only` 34×34.

**Tables** — wrapped in a panel shell (radius 20, overflow hidden): toolbar row (segmented pill filters — active segment = ink bg white text; pill-shaped search fields), mono-caps 10px headers on `--surface-2`, 13px rows with `--line-2` hairlines, hover → `--surface-2`, footer with count + pagination.

**Forms** — 2-col grid (14px gap, `.full` spans), mono-caps labels, 10px-radius inputs, focus = primary border + `0 0 0 3px rgba(15,76,129,0.1)` ring, 11px danger error text.

**Toasts** — bottom-right, ink-dark with white text, 12px radius, `--sh-pop`; success tinted `#0a2a20` + mint border at 0.3 alpha; error `#2a0a12` + danger border; colored status dot; slide in from right.

**Empty states** — centered, 84px circular illustration disc (`radial-gradient` primary-100→white, dashed border), 15px title, 13px muted copy max-width 320px, CTA below.

**Avatars** — circular, gradient fills (e.g. `linear-gradient(135deg, #4b6da3, #2a4470)`), white initials, sizes 24/32/42/60.

---

## 7. Voice & Layout Principles

1. **Contrast of scale**: gigantic thin-tracked headlines against 10px mono micro-labels. Nothing mid-sized and shouty.
2. **Dark frames light**: chrome (nav, transitions, boot screen) is cinematic near-black with grain; the work surface is airy cool-white. Crossing between them is an event (the veil).
3. **Pills and big radii**: chips, search fields, segmented controls are full-round; cards 20px, modals 28px. No sharp corners anywhere.
4. **Restraint with accent**: mint appears only where you want the eye to land.
5. **Data is mono**: IDs, timestamps, counts, table headers, labels — anything machine-ish gets JetBrains Mono caps.
6. **Motion is choreographed, not decorative**: staggered reveals on entry, one easing family, dramatic curve reserved for full-screen moments.

---

## 8. Porting Checklist

- [ ] Import DM Sans + JetBrains Mono; set `html { font-size: 14px }`
- [ ] Paste the `:root` token block (§1)
- [ ] Recreate: panel, btn (5 variants), chip (6 states), field-block, eyebrow, table shell
- [ ] Add grain data-URI to any dark surface
- [ ] Add fade-up + kinetic-word reveal utilities and the veil transition if the project has routes
- [ ] Custom cursor is optional flair — desktop only, always disabled for `pointer: coarse`

---

## 9. Swasthya-Setu Adaptations (project-specific — read before building any screen)

One token set, **three surfaces**. Apply the system differently per surface:

### 9a. Command Center (staff/admin dashboard)
- Full MediCore treatment: dark dock sidebar, veil transitions, kinetic headlines on section landings, grain, custom cursor.
- **Projector legibility rule**: judges watch this from ~3m. Live-state text (presence board states, queue counts, alerts) minimum 15px; status must never be conveyed by color alone — always chip text + dot.
- Density is fine here; this is the one information-heavy surface.

### 9b. Patient PWA (cheap Android, low literacy, Hindi-first)
- Tokens + type + chips yes; **flair no**: no custom cursor, no veil transitions, no grain, no backdrop-filter, no blur blobs (all are jank on budget devices). Motion limited to fade-up and modal-in.
- Touch targets ≥ 48px; primary actions are `.accent .lg` buttons with icon + label.
- Base font stays 14px but body text runs 15–16px here; mono micro-labels are decoration for staff, not information carriers for patients — never put essential patient info in 10px mono caps.
- Fonts must be self-hosted/bundled (offline-first PWA — no Google Fonts import at runtime).

### 9c. Kiosk skin
- PWA rules, amplified: buttons ≥ 64px tall, single-column, one decision per screen, auto-reset to home after 60s idle. No hover states exist — design for tap only.

### 9d. Semantic status tokens (the demo's visual vocabulary — use these names, never raw hexes)

```css
/* Doctor presence (chips per §3 pairing rule) */
--st-present:   var(--success);   /* PRESENT_IN_DEPT — mint */
--st-elsewhere: var(--info);      /* PRESENT_ELSEWHERE / ON_ROUNDS */
--st-surgery:   #9b8ef0;          /* IN_SURGERY — violet from chart palette */
--st-away:      var(--warn);      /* ON_LEAVE / OFF_SHIFT */
--st-unknown:   var(--muted-2);   /* UNKNOWN — grey, honest */

/* Beds */    FREE=success · OCCUPIED=neutral-ink · RESERVED=info · CLEANING=warn · OOO=danger
/* Alerts */  info=info · warn=warn · critical=danger (critical alerts may pulse — the only pulsing element besides live dots)
/* Referrals */ REQUESTED=neutral · RESERVED=info · CONFIRMED=success · EXPIRED=warn · CANCELLED=danger
```

- `UNKNOWN` presence is always grey and labeled — never hide low confidence behind an optimistic color. Confidence < threshold shows the % in mono next to the chip.
- Anything mock/synthetic visible in a demo gets a neutral chip `SIMULATED` / `SYNTHETIC DATA` (mono-caps, `--line-2`/`--muted`). Honesty is a design feature.
- `prefers-reduced-motion`: all surfaces drop to opacity-only transitions.
