// What the scan could not see.
//
// A disabled, throttled, or unpermitted region returns nothing — exactly what an
// empty region returns. So does a scanner that could not run at all: S3 is
// global, so `list_buckets` failing has no region to blame, and "no buckets" and
// "could not list buckets" are the same empty array. Without this panel the
// dashboard would present a partial inventory as a complete one, which is the
// worst answer a tool whose whole claim is "here is what you have running" can
// give.
//
// Both gaps live in one panel because a reader has one question — is this
// complete? — and two stacked warning boxes would answer it twice.
// Renders nothing when the scan read everything.
export default function IncompleteScan({ regions, scanners }) {
  const regionGaps = regions || [];
  const scannerGaps = scanners || [];
  const total = regionGaps.length + scannerGaps.length;
  if (total === 0) return null;

  const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const headline = [
    scannerGaps.length && count(scannerGaps.length, "service", "services"),
    regionGaps.length && count(regionGaps.length, "region", "regions"),
  ]
    .filter(Boolean)
    .join(" and ");

  const gap = (key, what, f) => (
    <li key={key} className="incomplete-scan__item">
      <span className="incomplete-scan__what">{what}</span>
      <span className="incomplete-scan__reason">{f.reason}</span>
      {(f.account_label || f.account_id) && (
        <span className="incomplete-scan__account">{f.account_label || f.account_id}</span>
      )}
    </li>
  );

  return (
    <section className="incomplete-scan" role="status">
      <h2 className="incomplete-scan__title">⚠️ {headline} could not be fully read</h2>
      <p className="incomplete-scan__lede">
        Anything {total === 1 ? "it holds" : "they hold"} is missing from these results —
        this scan is incomplete, not clean.
      </p>
      {scannerGaps.length > 0 && (
        <ul className="incomplete-scan__list">
          {scannerGaps.map((f) => gap(`${f.account_id ?? ""}-${f.scanner}`, f.label, f))}
        </ul>
      )}
      {regionGaps.length > 0 && (
        <ul className="incomplete-scan__list">
          {regionGaps.map((f) => gap(`${f.account_id ?? ""}-${f.region}`, f.region, f))}
        </ul>
      )}
    </section>
  );
}
