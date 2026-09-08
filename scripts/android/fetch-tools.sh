#!/usr/bin/env bash
# Assemble the SDK-less Android toolchain into $TOOLS (default /tmp/atools).
# Only PyPI, npm and the GitHub API are required (no dl.google.com / maven).
set -euo pipefail
TOOLS="${TOOLS:-/tmp/atools}"; mkdir -p "$TOOLS"; cd "$TOOLS"
echo "== JRE (jdk4py from PyPI)"
[ -x jdk/bin/java ] || { pip download --no-deps -q -d . jdk4py; unzip -qo jdk4py-*.whl 'jdk4py/java-runtime/*' -d j; rm -rf jdk; mv j/jdk4py/java-runtime jdk; rm -rf j; }
echo "== ecj (Eclipse compiler) — from a public mason/jdtls mirror on GitHub"
[ -f ecj.jar ] || gh api repos/mesteryui/Dotfiles/git/blobs/bc22cd6ec545945007768aedd1cb296d312ddfd8 -H "Accept: application/vnd.github.raw" > ecj.jar
echo "== aapt2 (aaptjs3 npm)"
[ -x aapt2 ] || { npm pack aaptjs3@2.0.2 --silent >/dev/null; tar xzf aaptjs3-2.0.2.tgz package/bin/x64/linux/aapt2; mv package/bin/x64/linux/aapt2 .; chmod +x aapt2; rm -rf package aaptjs3-*.tgz; }
echo "== d8 + apksigner (bundled in the MobSF wheel on PyPI)"
[ -f d8.jar ] || { pip download --no-deps -q -d . mobsf; unzip -qo mobsf-*.whl 'mobsf/StaticAnalyzer/tools/bundletool-all-*.jar' 'mobsf/StaticAnalyzer/tools/apksigner.jar' -d m; mv m/mobsf/StaticAnalyzer/tools/bundletool-all-*.jar d8.jar; mv m/mobsf/StaticAnalyzer/tools/apksigner.jar .; rm -rf m mobsf-*.whl; }
echo "== android.jar (API 34 stubs) — public GitHub mirror"
[ -f android.jar ] || gh api repos/altaga/Txt2App/git/blobs/923bafccf73aef996495c559e919ad8be3cabd58 -H "Accept: application/vnd.github.raw" > android.jar
ls -la "$TOOLS"
