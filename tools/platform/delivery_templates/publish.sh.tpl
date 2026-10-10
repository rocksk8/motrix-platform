#!/bin/bash
# publish_t@@TRAIN@@.sh -- train @@TRAIN@@: publish the gated package to the cloud delivery folder and write the step file.
# Run by the PM (node-d8) or the user:  bash /c/Users/hichan/publish_t@@TRAIN@@.sh [--check]
# The signing key is only passed as a PATH to delivery.py; this script never reads it. No force, aborts on any doubt.
set -u

MODE=publish
[ "${1:-}" = "--check" ] && MODE=check

GATED=@@GATED@@        # @@BRANCH@@, the commit that was gated and built
PKGNAME=@@PKGNAME@@                       # build output dir name (publish appends _full)
PY=/d/MOTRIX-PLATFORM/.venv312/Scripts/python.exe
KEY='D:\MOTRIX-KEYS\delivery\delivery_signing_key.pem'
DRILL_TEXT=@@DRILL_TEXT_SH@@
AUDIT_TEXT=@@AUDIT_TEXT_SH@@

fail() { echo "ABORT: $*"; exit 1; }
export PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1

# locate worktree and package WITHOUT typing the CJK directory name
WT=$(ls -d /d/*/@@WT@@ 2>/dev/null | head -1)
PKG=$(ls -d /d/*/@@PKGROOT@@/$PKGNAME 2>/dev/null | head -1)
DRAFT=$(ls /d/*/@@PKGROOT@@/@@DRAFT@@ 2>/dev/null | head -1)
[ -n "$WT" ] && [ -d "$WT" ] || fail "worktree @@WT@@ not found"
[ -n "$PKG" ] && [ -d "$PKG" ] || fail "package dir not found: $PKGNAME"
[ -n "$DRAFT" ] && [ -f "$DRAFT" ] || fail "step file draft not found"

# 1) preconditions ---------------------------------------------------------------------------
cd "$WT" || fail "cannot cd to worktree"
git fetch origin || fail "git fetch failed"
HEAD_NOW=$(git rev-parse HEAD) || fail "no HEAD"
[ "$HEAD_NOW" = "$GATED" ] || fail "worktree HEAD is $HEAD_NOW, expected $GATED"
REMOTE=$(git rev-parse origin/@@BRANCH@@) || fail "origin/@@BRANCH@@ not found"
[ "$REMOTE" = "$GATED" ] || fail "origin/@@BRANCH@@ is $REMOTE, expected $GATED (someone pushed?)"
[ -z "$(git status --porcelain)" ] || fail "changes in worktree"
MC=$("$PY" -I -X utf8 -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8-sig'))['commit'])" "$PKG/deploy_manifest.json") || fail "cannot read deploy_manifest.json"
[ "$MC" = "$GATED" ] || fail "deploy_manifest commit is $MC, expected $GATED"
BAD=$(find "$PKG" \( -name '*.db' -o -name '*.pyc' -o -name '__pycache__' \) | head -3)
[ -z "$BAD" ] || fail "forbidden files in package: $BAD"
echo "[check] verify_package --expect-db-version 118 ..."
"$PY" -X utf8 backend/tools/verify_package.py "$PKG" --expect-db-version 118 > /tmp/verify@@TRAIN@@.log 2>&1 || { tail -20 /tmp/verify@@TRAIN@@.log; fail "verify_package failed"; }
grep -q '全部通過（0 項 FAIL）' /tmp/verify@@TRAIN@@.log || { tail -20 /tmp/verify@@TRAIN@@.log; fail "verify_package did not report 0 FAIL"; }
[ -f 'D:/MOTRIX-KEYS/delivery/delivery_signing_key.pem' ] || fail "signing key path not found (not read, only tested)"
R=$(ls -d /g/*/MOTRIX-交付 2>/dev/null | head -1)
[ -n "$R" ] && [ -d "$R" ] || fail "cloud delivery root not found"
SRC=$(ls "$R"/*第@@PREV_CN@@班更新步驟.md 2>/dev/null | head -1)
[ -n "$SRC" ] || fail "train @@PREV@@ step file not found in cloud root (needed to derive the file name)"
DST="${SRC/@@PREV_CN@@/@@THIS_CN@@}"
[ "$DST" != "$SRC" ] || fail "could not derive train @@TRAIN@@ step file name"
[ ! -e "$DST" ] || fail "step file already exists: $DST"
[ ! -e "$R/packages/${PKGNAME}_full" ] || fail "package already published"
grep -q '<PKG_NAME>' "$DRAFT" && grep -q '<PKG_SHA256>' "$DRAFT" || fail "draft placeholders missing"
echo "CHECK_OK  commit=$GATED  pkg=$PKGNAME  cloud=$R"
echo "          step file will be: $DST"
if [ "$MODE" = "check" ]; then
  echo "AUDIT_TEXT=$AUDIT_TEXT"
  echo "(--check: nothing published, nothing written)"; exit 0
fi
[ "$AUDIT_TEXT" != "PENDING" ] || fail "AUDIT_TEXT still PENDING: record the independent audit result first"

# 2) publish (key path only) ------------------------------------------------------------------
echo "[publish] delivery.py publish ..."
"$PY" -X utf8 backend/tools/delivery.py publish --pkg "$PKG" --root "$R" --private-key "$KEY" > /tmp/publish@@TRAIN@@.log 2>&1
RC=$?
tail -15 /tmp/publish@@TRAIN@@.log
[ $RC -eq 0 ] || fail "delivery.py publish exit $RC"
NAME=$(grep -o 'DELIVERY_PUBLISH_OK [^ ]*' /tmp/publish@@TRAIN@@.log | tail -1 | cut -d' ' -f2)
[ -n "$NAME" ] || fail "no DELIVERY_PUBLISH_OK line"
PD="$R/packages/$NAME"
[ -f "$PD/package.sha256" ] || fail "published package.sha256 missing: $PD"
SHA=$(sha256sum "$PD/package.sha256" | cut -d' ' -f1)
LINES=$(wc -l < "$PD/package.sha256" | tr -d ' ')

# 3) step file --------------------------------------------------------------------------------
OUT=$(mktemp -d)
"$PY" -I -X utf8 - "$DRAFT" "$(cygpath -w "$OUT")/step@@TRAIN@@.md" "$NAME" "$SHA" "$LINES" "$DRILL_TEXT" "$AUDIT_TEXT" <<'PYEOF' || fail "step-file generator failed (package IS published: $NAME)"
import sys, io, re
src, dst, name, sha, n, drill, audit = sys.argv[1:8]
s = io.open(src, encoding='utf-8', newline='').read()
for k, v in (('<PKG_NAME>', name), ('<PKG_SHA256>', sha), ('<N>', n)):
    s = s.replace(k, v)
old48 = @@VERIFY_ANCHOR_PY@@
assert old48 in s, 'verification sentence not found'
s = s.replace(old48, '`verify_package --expect-db-version 118` 0 項 FAIL；V5 逐檔比對僅允許差異；' + drill + '。' + audit)
for _old, _new in @@PATCHES_PY@@:          # train-specific text patches (each must match or the script aborts)
    assert _old in s, 'patch anchor not found: ' + _old[:40]
    s = s.replace(_old, _new)
# acceptance letters: the draft's items are renumbered to continue after the previous train's last letter
letters = @@LETTERS_FROM_PY@@
newl = @@LETTERS_TO_PY@@
m = dict(zip(letters, newl))
cnt = [0]
def repl(mo):
    cnt[0] += 1
    return mo.group(1) + m[mo.group(2)] + '. **'
s = re.sub(r'(^|\n)(' + '|'.join(letters) + r')\. \*\*', repl, s)
assert cnt[0] == len(letters), 'acceptance renumber count %d' % cnt[0]
s = s.replace('**草稿（開發機整合者 b7 撰寫，待主持 node-d8 定稿／發布）**', '**定稿（開發機整合者 b7 撰寫、主持 node-d8 定稿並發布）**')
left = [t for t in ('<PKG_NAME>', '<PKG_SHA256>', '<N>', '見定稿', 'PENDING') if t in s]
if left:
    print('leftover placeholders:', left); sys.exit(1)
io.open(dst, 'w', encoding='utf-8', newline='').write(s)
print('written', len(s))
PYEOF
cp "$OUT/step@@TRAIN@@.md" "$DST" || fail "writing cloud step file failed (package IS published: $NAME)"
rm -rf "$OUT"

echo "DELIVERY_PUBLISH_OK $NAME"
echo "package.sha256 SHA256: $SHA"
echo "lines/files: $LINES"
echo "step file: $DST"
