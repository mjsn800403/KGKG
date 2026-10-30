#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Remove the per-sha release images that nothing needs any more.
#
#   prune_images.sh <keep-sha>...    keep these, plus anything in use
#   prune_images.sh --selftest
#
# Every staging run and every deploy builds `kgkg-backend:<short>` and
# `kgkg-frontend:<short>` — 3.46 GB a pair. `deploy.sh` already had retention
# for them, and it was correct, but it ran **only at the end of a full
# promote**. Staging is the path that runs on every push to `work`, and it
# reached `exit 0` several hundred lines earlier, so the images it built were
# never considered. Measured on the production host 2026-10-30: 23 `kgkg-*`
# images, 40.19 GB with 10.12 GB reclaimable, roughly 21 GB from six staging
# runs in nine hours, root filesystem 74.5 % -> 77 % with 70 G free. On a host
# where disk is the standing top risk and production, staging, QA and the
# observability stack share one filesystem, that is weeks, not months.
#
# What is kept:
#   * every sha named on the command line — the caller passes the live release,
#     the rollback target and the sha it has just built;
#   * every tag a container still references, running or stopped. `docker ps -a`
#     is consulted *in addition to* the caller's list because state.env is
#     written by deploy.sh and could be stale, while a container referencing a
#     deleted image is a rollback that cannot start;
#   * the newest KEEP_IMAGES-1 others, so a recently staged commit can still be
#     promoted without a rebuild.
#
# Deleting the rollback image would turn `deploy.sh --rollback` into a rebuild
# at the one moment nobody has time for it, which is why `docker image prune -a`
# is never the answer here and why this script takes an explicit keep list.
#
# KG_DOCKER replaces the docker binary (tests). KEEP_IMAGES overrides the count.
# ---------------------------------------------------------------------------
set -uo pipefail

DOCKER=${KG_DOCKER:-docker}
KEEP_IMAGES=${KEEP_IMAGES:-4}
REPOS=${KG_IMAGE_REPOS:-"kgkg-backend kgkg-frontend"}

prune() {
  local keep repo
  keep=$(mktemp) || return 0
  # A sentinel that cannot equal a 9-hex tag, so the keep list is never empty:
  # `grep -vxF -f <empty file>` has no patterns to invert and its behaviour is
  # not worth depending on.
  printf '%s\n' 0000000000 > "$keep"
  local s
  for s in "$@"; do [[ -n ${s:-} ]] && printf '%s\n' "${s:0:9}" >> "$keep"; done
  for repo in $REPOS; do
    $DOCKER ps -a --format '{{.Image}}' 2>/dev/null \
      | sed -n "s|^$repo:||p" >> "$keep"
  done

  local removed=0 tag
  for repo in $REPOS; do
    while read -r tag; do
      [[ -n $tag ]] || continue
      $DOCKER image rm -f "$repo:$tag" >/dev/null 2>&1 && removed=$((removed + 1))
    done < <($DOCKER images "$repo" --format '{{.Tag}}' 2>/dev/null \
               | grep -xE '[0-9a-f]{9}' \
               | grep -vxF -f "$keep" \
               | tail -n +"$KEEP_IMAGES")
  done
  rm -f "$keep"
  printf '%s\n' "$removed"
}

# ---------------------------------------------------------------------------
selftest() {
  local T fails=0
  T=$(mktemp -d); trap 'rm -rf "$T"' RETURN

  # A docker stub. $STUB/images holds "repo tag" lines newest-first, as
  # `docker images` lists them; $STUB/ps holds container image references;
  # every removal is appended to $STUB/removed.
  cat > "$T/docker" <<'EOF'
#!/usr/bin/env bash
if [[ $1 == images ]]; then awk -v r="$2" '$1==r {print $2}' "$STUB/images"; exit 0; fi
if [[ $1 == ps ]]; then cat "$STUB/ps" 2>/dev/null; exit 0; fi
if [[ $1 == image && $2 == rm ]]; then
  printf '%s\n' "$4" >> "$STUB/removed"
  exit 0
fi
exit 0
EOF
  chmod 755 "$T/docker"

  ok()  { printf '  ok    %s\n' "$1"; }
  no()  { printf '  FAIL  %s\n          %s\n' "$1" "$2"; fails=$((fails + 1)); }

  setup() {  # $1 = newline-separated "repo tag"; $2 = container images
    : > "$T/removed"
    printf '%s\n' "$1" > "$T/images"
    printf '%s\n' "${2:-}" > "$T/ps"
  }
  removed() { tr '\n' ' ' < "$T/removed"; }
  run_prune() { STUB=$T KG_DOCKER="$T/docker" KEEP_IMAGES="${KEEP:-4}" bash "$0" "$@" >/dev/null 2>&1; }
  gone()  { grep -qxF "$1" "$T/removed" 2>/dev/null; }

  # Newest first, as `docker images` lists them.
  local SIX='kgkg-backend aaaaaaaaa
kgkg-backend bbbbbbbbb
kgkg-backend ccccccccc
kgkg-backend ddddddddd
kgkg-backend eeeeeeeee
kgkg-backend fffffffff'

  setup "$SIX"; run_prune aaaaaaaaa bbbbbbbbb
  # keep list = a,b; the rest are c,d,e,f; KEEP_IMAGES=4 drops from the 4th
  # of that remainder, i.e. f only.
  if gone kgkg-backend:fffffffff && ! gone kgkg-backend:ccccccccc; then
    ok "keeps the named shas and the newest few others"
  else no "keeps the named shas and the newest few others" "removed: $(removed)"; fi

  setup "$SIX"; KEEP=1 run_prune aaaaaaaaa bbbbbbbbb
  if gone kgkg-backend:ccccccccc && gone kgkg-backend:ddddddddd \
     && gone kgkg-backend:eeeeeeeee && gone kgkg-backend:fffffffff \
     && ! gone kgkg-backend:aaaaaaaaa && ! gone kgkg-backend:bbbbbbbbb; then
    ok "KEEP_IMAGES=1 removes every unnamed tag and still spares the named ones"
  else no "KEEP_IMAGES=1 removes every unnamed tag and spares the named ones" "removed: $(removed)"; fi

  # The rollback image is the one that must never go, even when the caller
  # forgets it, because a container still references it.
  setup "$SIX" 'kgkg-backend:eeeeeeeee'; KEEP=1 run_prune aaaaaaaaa
  if ! gone kgkg-backend:eeeeeeeee; then
    ok "a tag a container still references is never removed"
  else no "a tag a container still references is never removed" "removed: $(removed)"; fi

  setup "$SIX"; KEEP=1 run_prune
  if [[ $(wc -l < "$T/removed") -eq 6 ]]; then
    ok "with no keep list and no containers, every sha tag is fair game"
  else no "with no keep list, every sha tag is fair game" "removed: $(removed)"; fi

  # Tags that are not 9-hex shas are not ours to delete: `:ci`, `:latest`,
  # anything a human tagged.
  setup 'kgkg-backend ci
kgkg-backend latest
kgkg-backend aaaaaaaaa
kgkg-backend bbbbbbbbb'; KEEP=1 run_prune
  if ! gone kgkg-backend:ci && ! gone kgkg-backend:latest; then
    ok "non-sha tags are left alone"
  else no "non-sha tags are left alone" "removed: $(removed)"; fi

  setup 'kgkg-backend aaaaaaaaa'; KEEP=1 run_prune aaaaaaaaa
  if [[ ! -s $T/removed ]]; then
    ok "a single image that is the live release is not removed"
  else no "a single image that is the live release is not removed" "removed: $(removed)"; fi

  setup ''; KEEP=1 run_prune aaaaaaaaa
  if [[ ! -s $T/removed ]]; then ok "no images at all is not an error"
  else no "no images at all is not an error" "removed: $(removed)"; fi

  # A full sha from state.env must match a 9-char tag.
  setup "$SIX"; KEEP=1 run_prune aaaaaaaaa0123456789abcdef0123456789abcd
  if ! gone kgkg-backend:aaaaaaaaa; then
    ok "a full 40-char sha keeps its 9-char tag"
  else no "a full 40-char sha keeps its 9-char tag" "removed: $(removed)"; fi

  if (( fails )); then echo "prune_images selftest: $fails failure(s)" >&2; return 1; fi
  echo "prune_images selftest: all checks passed"
}

case ${1:-} in
  --selftest) selftest ;;
  *)          prune "$@" ;;
esac
