// Riskiest first. Dashboard lists findings in this order and the findings table
// sorts and filters by it — one definition, so the two cannot disagree.
export const RISK_ORDER = { HIGH: 0, REVIEW: 1, MEDIUM: 2, LOW: 3 };

// Colored badge for a resource's risk level. Colors come from theme tokens
// (see .risk-badge in styles.css) so the badge adapts to light/dark.
export default function RiskBadge({ level }) {
  const mod = (level || "").toLowerCase();
  return <span className={`risk-badge risk-badge--${mod}`}>{level}</span>;
}
