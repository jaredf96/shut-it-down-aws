// Colored badge for a resource's risk level.
const COLORS = {
  LOW: { bg: "#e6f4ea", fg: "#1e7e34" },
  MEDIUM: { bg: "#fff4e5", fg: "#b26a00" },
  HIGH: { bg: "#fdecea", fg: "#c62828" },
  REVIEW: { bg: "#e8eaf6", fg: "#3949ab" },
};

export default function RiskBadge({ level }) {
  const color = COLORS[level] || { bg: "#eee", fg: "#333" };
  return (
    <span
      style={{
        backgroundColor: color.bg,
        color: color.fg,
        padding: "2px 10px",
        borderRadius: "12px",
        fontSize: "0.75rem",
        fontWeight: 700,
        letterSpacing: "0.03em",
      }}
    >
      {level}
    </span>
  );
}
