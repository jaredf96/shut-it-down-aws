// Regions the scan could not read.
//
// A disabled, throttled, or unpermitted region returns nothing — exactly what an
// empty region returns. Without this panel the dashboard would present a partial
// inventory as a complete one, which is the worst answer a tool whose whole
// claim is "here is what you have running" can give. Renders nothing when every
// region was read.
export default function RegionFailures({ failures }) {
  if (!failures || failures.length === 0) return null;

  return (
    <section className="region-failures" role="status">
      <h2 className="region-failures__title">
        ⚠️ {failures.length} {failures.length === 1 ? "region" : "regions"} could not be
        fully read
      </h2>
      <p className="region-failures__lede">
        Anything running in {failures.length === 1 ? "it" : "them"} is missing from these
        results — this scan is incomplete, not clean.
      </p>
      <ul className="region-failures__list">
        {failures.map((f) => (
          <li
            key={`${f.account_id ?? ""}-${f.region}`}
            className="region-failures__item"
          >
            <span className="region-failures__region">{f.region}</span>
            <span className="region-failures__reason">{f.reason}</span>
            {(f.account_label || f.account_id) && (
              <span className="region-failures__account">
                {f.account_label || f.account_id}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
