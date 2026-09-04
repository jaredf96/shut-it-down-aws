"""The committed screenshots must not outlive the claims they show.

`docs/img/` holds three PNGs the README publishes. Nothing in this suite reads
a pixel, so this module cannot tell you an image is stale, and it is not a
visual-regression test. What it can tell you is when an image has become
*suspect*: every sentence and every figure legible in those captures is listed
below and asserted against the source that renders it, so a reword or a fixture
change fails here instead of sitting in a published image for 34 commits —
which is exactly what happened to `dashboard.png`, whose hero capture went on
showing "the real bill is higher, never lower" for a month after that claim was
retracted as false.

When one of these fails, the order is: recapture the named image (`CLAUDE.md`
§ Gotchas has the recipe), *then* update the manifest here. Updating the
manifest alone leaves a green test certifying nothing.

No AWS calls, no network.
"""

from __future__ import annotations

import json
import re

from tests.conftest import REPO_ROOT

FRONTEND = REPO_ROOT / "frontend" / "src"
DEMO_DATA = REPO_ROOT / "demo-data"

DASHBOARD_PNG = "docs/img/dashboard.png"
CLEANUP_PNG = "docs/img/cleanup-preview.png"
HISTORY_PNG = "docs/img/history-diff.png"


def _visible_text(path):
    """JSX reduced to the words a reader sees, whitespace-collapsed.

    Comments go first: the comment above the cost caveat paraphrases it, and
    leaving it in would let a stale caveat pass on the strength of the note
    explaining it. `{expr}` interpolations are left intact, so a phrase that
    spans one cannot be pinned here — none of the phrases below does.
    """
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"\{/\*.*?\*/\}", " ", src, flags=re.DOTALL)
    src = re.sub(r"<[^>]*>", " ", src)
    return re.sub(r"\s+", " ", src)


def _source_text(path):
    """Raw source, whitespace-collapsed — for plain `.js` data modules.

    `_visible_text`'s tag strip is wrong for JavaScript: `<[^>]*>` eats arrow
    functions and comparisons.
    """
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


# Keyed by the image whose claims each entry backs, so a failure names the file
# to recapture rather than only the file that changed.
PROSE = {
    DASHBOARD_PNG: [
        (
            FRONTEND / "pages" / "Dashboard.jsx",
            _visible_text,
            [
                "Minimum monthly exposure at on-demand list prices",
                "NAT data processing and S3 storage are not priced, so "
                "list-price spend is higher, never lower; Free Tier, credits, "
                "or reserved pricing can bring the actual bill below it.",
            ],
        ),
    ],
    CLEANUP_PNG: [
        (
            FRONTEND / "components" / "CleanupPanel.jsx",
            _visible_text,
            [
                "Walk the real safety checks — action catalog, typed confirmation, and a live",
                "Every attempt that reaches the service is audited below, refusals included",
                "Dry run (preview only — does not change anything)",
                "locked in this build",
            ],
        ),
        # The strings the image shows that CleanupPanel.jsx does not own. This
        # is the file that has actually moved since the capture, so it is the
        # one worth guarding.
        (
            FRONTEND / "data" / "demoScanProvider.js",
            _source_text,
            [
                'description: "Release an unassociated Elastic IP to stop hourly charges."',
                "Would release unassociated Elastic IP",
                'verb: "Release"',
            ],
        ),
    ],
}


def _assert_prose(image):
    for path, reduce, phrases in PROSE[image]:
        text = reduce(path)
        for phrase in phrases:
            assert phrase in text, (
                f"{image} shows text {path.name} no longer renders. "
                f"Recapture the image (CLAUDE.md § Gotchas), THEN update this "
                f"manifest — in that order. Missing: {phrase!r}"
            )


def test_dashboard_screenshot_prose_is_still_what_the_ui_renders():
    _assert_prose(DASHBOARD_PNG)


def test_cleanup_screenshot_prose_is_still_what_the_ui_renders():
    _assert_prose(CLEANUP_PNG)


def test_screenshot_figures_match_the_demo_fixtures():
    """The numbers and ids legible in the captures, against the fixtures that
    produce them.

    The diff is computed here rather than read from `expected-diff.json`: the
    demo provider computes its own (`demoScanProvider.js`), and that computed
    diff is what `history-diff.png` shows. `expected-diff.json` is the
    backend's reference file, which the demo never opens.
    """
    scan = json.loads((DEMO_DATA / "current-scan.json").read_text())
    previous = json.loads((DEMO_DATA / "previous-scan.json").read_text())

    # dashboard.png's summary row.
    assert scan["summary"]["total_resources"] == 15
    assert scan["summary"]["by_risk_level"] == {"HIGH": 3, "REVIEW": 2, "MEDIUM": 4, "LOW": 6}
    assert scan["summary"]["estimated_monthly_cost"] == 123.30

    # The 4-tuple identity the alert/diff engine uses (CLAUDE.md § Gotchas).
    def identity(resource):
        return (
            resource["resource_type"],
            resource["region"],
            resource["resource_id"],
            resource["account_id"],
        )

    before = {identity(r): r for r in previous["resources"]}
    after = {identity(r): r for r in scan["resources"]}
    added = [after[k] for k in after if k not in before]
    removed = [before[k] for k in before if k not in after]
    changed = [
        after[k]
        for k in after
        if k in before and any(before[k][f] != after[k][f] for f in ("status", "risk_level"))
    ]
    unchanged = [k for k in after if k in before]

    # history-diff.png's summary row: +2 / −1 / ~1, with 12 untouched.
    assert (len(added), len(removed), len(changed)) == (2, 1, 1)
    assert len(unchanged) - len(changed) == 12

    # The ids are what an unseeded regeneration churns, and the ids are what
    # the images show — cleanup-preview.png renders the Elastic IP's id four
    # times. Names come from literal tags in the generator and are stable with
    # or without the seed, so pinning names alone would pin nothing.
    assert [(r["resource_id"], r["name"]) for r in added] == [
        ("eipalloc-8a571f951985fe53a", "left-over-lab-ip"),
        ("nat-bcebadb4a7c3c19da", "lab-vpc-nat"),
    ]
    assert [(r["resource_id"], r["name"]) for r in removed] == [
        ("vol-0e11a2b3c4d5e6f70", "retired-lab-volume"),
    ]
    assert [(r["resource_id"], r["name"]) for r in changed] == [
        ("i-af04af89f100491dd", "tutorial-web-server"),
    ]


def test_the_fixture_seed_is_still_pinned():
    """Every id above is reproducible only because the generator seeds its
    sandbox. Without the seed each regeneration churns them all and invalidates
    all three captures at once (CLAUDE.md § Gotchas)."""
    from scripts.generate_demo_fixtures import RANDOM_SEED

    assert RANDOM_SEED == 20260817


def test_every_committed_image_is_still_referenced():
    """`docs/img/README.md` is a manifest, not a folder listing: an image that
    stops being referenced is one nobody will notice going stale."""
    readme = (REPO_ROOT / "README.md").read_text()
    manifest = (REPO_ROOT / "docs" / "img" / "README.md").read_text()

    for image in (DASHBOARD_PNG, CLEANUP_PNG, HISTORY_PNG):
        name = image.rsplit("/", 1)[1]
        assert image in readme, f"{image} is committed but the README does not show it"
        assert name in manifest, f"{image} is committed but docs/img/README.md does not list it"
