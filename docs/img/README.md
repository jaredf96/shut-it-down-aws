# Screenshots

Every image in this folder is committed *and* referenced. All three are captured
from the fixture demo, so no real account or resource identifier appears in any
of them.

| File | What it shows | Referenced from | Claims checked by |
| --- | --- | --- | --- |
| `dashboard.png` | A scan result: cost total, risk badges, alerts panel | root `README.md` — hero image and Screenshots | `test_screenshot_claims.py` (cost caveat, summary figures) |
| `history-diff.png` | The scan-history sidebar and the diff between two scans | root `README.md` — Screenshots | `test_screenshot_claims.py` (diff counts, resource IDs) |
| `cleanup-preview.png` | The guided cleanup panel mid dry-run | root `README.md` — Screenshots | `test_screenshot_claims.py` (panel prose, action catalog, EIP id) |

Those tests flag the source and fixture changes that make an image *suspect*;
whether the pixels were re-taken is not machine-checkable. `dashboard.png`
published a retracted cost claim for 34 commits before anyone noticed, which is
what they exist to prevent.

**These captures are pinned to the fixtures, so regenerating one means
re-checking all of them.** `make demo-fixtures` is deterministic only because it
seeds the moto sandbox; without the seed every regeneration churns the resource
IDs shown above. Resource *ages* are equally pinned — they are measured against
the fixture's own `created_at` rather than render time, which is what stops them
creeping upward daily and outrunning these images. Both rules are in `CLAUDE.md`
§ Gotchas; break either one and every screenshot here is stale.

Capture recipe — viewport, theme, timezone — is in `CLAUDE.md` § Gotchas.
Recapture only the image whose inputs moved: "re-checking all of them" above
means checking, not regenerating.
