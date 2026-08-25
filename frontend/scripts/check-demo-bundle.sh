#!/usr/bin/env bash
#
# Assert that the public demo bundle carries no API client.
#
# The README's claim is not "the demo does not call the API" but "there are no
# endpoints in it to call": `VITE_DEMO_MODE` is a build-time constant, so Rollup
# tree-shakes `api/client.js` out of the demo build entirely. That guarantee is
# one stray `import ... from "../api/client.js"` in a component away from being
# quietly false, and the bundle is the only place the truth shows up.
#
# Run against an existing `dist/` (built with `--mode demo`):
#
#     npm run build:demo && bash scripts/check-demo-bundle.sh
#
# or `make demo-bundle-check` from the repo root, which does both.
set -euo pipefail

DIST="${1:-dist}"

if [ ! -d "$DIST" ]; then
  echo "no build to inspect at '$DIST' — run 'npm run build:demo' first" >&2
  exit 2
fi

# Credential handling and endpoints that exist only inside api/client.js. Each
# one is present in the API-profile build and absent from the demo build, so a
# hit means the client (or a key) came along.
NEEDLES=(
  'X-API-Key'
  'VITE_API_KEY'
  'VITE_API_BASE_URL'
  'localhost'
  '/cleanup/execute'
  '/cleanup/audit'
  '/scans/diff'
  '/users'
)

leaked=0
for needle in "${NEEDLES[@]}"; do
  if grep -rqF -- "$needle" "$DIST"; then
    echo "LEAK: the public demo bundle contains '$needle'" >&2
    grep -rlF -- "$needle" "$DIST" | sed 's/^/      /' >&2
    leaked=1
  fi
done

if [ "$leaked" -ne 0 ]; then
  cat >&2 <<'MSG'

The public demo must ship no API endpoints and no credential handling.
The usual cause is a component importing `api/client.js` directly instead of
going through the provider in `src/data/` — that defeats the tree-shake.
MSG
  exit 1
fi

echo "demo bundle clean: no endpoints, no credential handling in $DIST"
