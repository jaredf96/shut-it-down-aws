// Colored badge for a resource's risk level. Colors come from theme tokens
// (see .risk-badge in styles.css) so the badge adapts to light/dark.
export default function RiskBadge({ level }) {
  const mod = (level || "").toLowerCase();
  return <span className={`risk-badge risk-badge--${mod}`}>{level}</span>;
}
