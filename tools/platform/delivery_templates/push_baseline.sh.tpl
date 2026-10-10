#!/bin/bash
# push_t@@TRAIN@@_baseline.sh -- train @@TRAIN@@ is LIVE: publish the prod-baseline commit and tag it.
# Run by the USER:  ! bash /c/Users/hichan/push_t@@TRAIN@@_baseline.sh
# No key involved. Fast-forward only (never --force). Aborts on any doubt.
set -u

REPO=/d/MOTRIX-PLATFORM
GATED=@@GATED@@      # the commit that was gated, built, published and applied (@@BRANCH@@)
OLD_PLATFORM=@@OLD_PLATFORM@@  # origin/platform before train @@TRAIN@@
BR=chore/t@@TRAIN@@-baseline-d8                             # local branch: baseline commit on top of $GATED
TAG=prod/@@GATED8@@

fail() { echo "ABORT: $*"; exit 1; }

cd "$REPO" || fail "repo not found"

# 0) fresh view of origin
git fetch origin || fail "git fetch failed"

# 1) origin/platform must still be exactly the pre-train commit
NOW=$(git rev-parse origin/platform) || fail "origin/platform not found"
[ "$NOW" = "$OLD_PLATFORM" ] || fail "origin/platform is $NOW, expected $OLD_PLATFORM (someone pushed?)"

# 2) the baseline branch exists locally, descends from the gated commit, which descends from origin/platform
git rev-parse --verify -q "refs/heads/$BR" >/dev/null || fail "local branch $BR does not exist"
TIP=$(git rev-parse "$BR")
git merge-base --is-ancestor "$GATED" "$TIP" || fail "$BR ($TIP) does not contain the gated commit $GATED"
git merge-base --is-ancestor "$OLD_PLATFORM" "$GATED" || fail "gated commit is not a descendant of origin/platform"
git merge-base --is-ancestor origin/platform "$TIP" || fail "$BR is not a fast-forward of origin/platform"

# 3) between the gated commit and the tip only docs / baseline constant may change (no code slipped in)
BAD=$(git diff --name-only "$GATED" "$TIP" | grep -v -E '^(docs/|backend/tests/_prod_baseline\.py$)' || true)
if [ -n "$BAD" ]; then echo "Unexpected changed files since the gated commit:"; echo "$BAD"; fail "non-docs files differ from the gated tree"; fi

# 4) local platform tree clean (shared checkout)
[ -z "$(git status --short --untracked-files=all)" ] || fail "working tree in $REPO is not clean"

# 5) the tag must not exist yet (locally or on origin)
git rev-parse --verify -q "refs/tags/$TAG" >/dev/null && fail "tag $TAG already exists locally"
[ -z "$(git ls-remote --tags origin "refs/tags/$TAG")" ] || fail "tag $TAG already exists on origin"

echo "origin/platform : $NOW"
echo "gated commit    : $GATED"
echo "baseline tip    : $TIP  ($BR)"
echo "changed since gated commit:"; git diff --stat "$GATED" "$TIP" | tail -n 8

# 6) push: fast-forward only (no --force); the branch lands on origin as 'platform'
git push origin "$BR:platform" || fail "push to origin/platform failed (non fast-forward or rejected)"
echo "pushed $TIP -> origin/platform"

# 7) tag the gated/built commit (same style as prod/dc4e2e42: lightweight tag on the commit prod runs)
git tag "$TAG" "$GATED" || fail "could not create tag $TAG"
git push origin "refs/tags/$TAG" || fail "tag push failed"
echo "tag $TAG -> $(git rev-parse --short=9 "$TAG^{commit}") pushed"

# 8) local platform follows origin (fast-forward)
git fetch origin
git merge --ff-only origin/platform && echo "local platform now: $(git rev-parse --short=9 HEAD)"
git status -sb | head -n 2
echo "DONE"
