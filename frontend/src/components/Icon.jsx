/**
 * The project's icon set, inlined.
 *
 * These replace emoji, and the reason is not taste. An emoji is drawn by the
 * viewer's OS emoji font, so the same markup renders as Apple's glyphs here,
 * Segoe's on Windows and Noto's on Linux — which means the three committed
 * captures in `docs/img/` and the walkthrough video bake in one platform's
 * artwork and every other reader sees something else. A stroked path renders
 * identically everywhere.
 *
 * Inlined rather than pulled from an icon package: the public demo is a static
 * bundle with a CI check over what it contains, and nine paths do not justify a
 * dependency.
 *
 * `currentColor` throughout, so an icon takes the colour of whatever it sits in
 * and follows the light/dark swap with no per-theme rules.
 *
 * Decorative by default — `aria-hidden`, because the heading beside it already
 * says "Alerts" and a screen reader announcing "warning sign, Alerts" is worse
 * than one that says "Alerts". Pass `title` only when the icon is the sole
 * carrier of meaning.
 */
const PATHS = {
  // Irreversible actions, alerts, and a scan that could not be fully read.
  warning: (
    <>
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </>
  ),
  // Reversible actions — the counterpart to `warning` in the cleanup catalog.
  undo: (
    <>
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
    </>
  ),
  brush: (
    <>
      <path d="m9.06 11.9 8.07-8.06a2.85 2.85 0 1 1 4.03 4.03l-8.06 8.08" />
      <path d="M7.07 14.94c-1.66 0-3 1.35-3 3.02 0 1.33-2.5 1.52-2 2.02 1.08 1.1 2.49 2.02 4 2.02 2.2 0 4-1.8 4-4.04a3.01 3.01 0 0 0-3-3.02z" />
    </>
  ),
  check: (
    <>
      <path d="M21.8 10A10 10 0 1 1 17 3.34" />
      <path d="m9 11 3 3L22 4" />
    </>
  ),
  flask: (
    <>
      <path d="M10 2v7.53a2 2 0 0 1-.21.89L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.07-10.13a2 2 0 0 1-.21-.89V2" />
      <path d="M8.5 2h7" />
      <path d="M7 16h10" />
    </>
  ),
  lock: (
    <>
      <rect x="3" y="11" width="18" height="11" rx="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </>
  ),
  history: (
    <>
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
      <path d="M12 7v5l3.5 2" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </>
  ),
  moon: <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />,
};

export default function Icon({ name, size = 16, className = "", title }) {
  const paths = PATHS[name];
  if (!paths) return null;
  return (
    <svg
      className={`icon ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : "true"}
      focusable="false"
    >
      {title ? <title>{title}</title> : null}
      {paths}
    </svg>
  );
}
