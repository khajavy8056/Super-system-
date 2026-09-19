#!/usr/bin/env bash
# One-shot: move the CI workflow into .github/workflows and push.
# Run this from a machine where your GitHub account has the `workflow` scope
# (a normal `gh auth login` or a PAT with `workflow` is enough).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .github/workflows
git mv -f installer/ci/release-windows.yml .github/workflows/release-windows.yml
git mv -f installer/ci/release-android.yml .github/workflows/release-android.yml 2>/dev/null || true
git commit -m "ci: activate release workflows (Windows installer + Android APK)"
git push
echo "Done. Trigger: push a v* tag, or Actions → 'Build and publish release assets' → Run workflow."
