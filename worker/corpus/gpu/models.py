"""LTX-2.5 model files on a Race pod: fetch once, verify once, re-link every boot.

Race servers are overcommitted, so pods get moved between hosts often and every
fresh host means a 40 GB download. This keeps that cheap:

  * The host's REAL free space is checked before a byte is written. /workspace is
    a sparse file on the host's shared disk; a 70 GB pod on a host with 3 GB free
    corrupts mid-download (seen 2026-10-03), so short hosts are refused up front.
  * Each big file is fetched as N parallel byte ranges written straight to their
    offsets in the final file — no parts, no join, exactly the file's size on disk.
  * Hashes come from the Hugging Face API *on the pod* (the operator's network
    masks 64-hex strings) and are checked in parallel; a `.verified` manifest makes
    a resumed pod skip both the download and the 40 GB re-hash.
  * Model links into /opt/ComfyUI/models are rebuilt every time: the pod's root
    filesystem resets on resume, /workspace does not.
"""

from __future__ import annotations

REPO = "Lightricks/LTX-2.5"
DEST = "/workspace/models/ltx25"

# repo path -> bytes (from the HF tree API; the hashes are fetched on the pod).
FILES = {
    "diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors": 21504034224,
    "text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors": 15372969374,
    "vae/ltx-2.5-video-vae-bf16.safetensors": 1472223346,
    "vae/ltx-2.5-audio-vae-bf16.safetensors": 364866540,
    "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors": 995778752,
}
TOTAL_BYTES = sum(FILES.values())
MARGIN_BYTES = 12_000_000_000      # room for renders, logs and the host not to choke

# Runs on the pod under bash. Prints machine-readable lines (STATUS ...) that the
# session reads; exit codes: 0 ready, 2 host disk too full, 3 manifest/API error,
# 4 verification failed, 5 files missing and NO_FETCH=1.
ENSURE_SCRIPT = r"""
set -u
DEST=__DEST__; REPO=__REPO__; N=16; MARGIN=__MARGIN__
mkdir -p "$DEST" && cd "$DEST" || exit 3
TOKEN=$(cat /root/.hf_token 2>/dev/null || true)
cleanup() { rm -f /root/.hf_token; }
trap cleanup EXIT

python3 - "$REPO" "$TOKEN" > manifest.txt <<'PY' || { echo "STATUS manifest_error"; exit 3; }
import json, sys, urllib.request
repo, tok = sys.argv[1], sys.argv[2]
want = __WANT__
req = urllib.request.Request(f"https://huggingface.co/api/models/{repo}/tree/main?recursive=1",
                             headers={"Authorization": f"Bearer {tok}"} if tok else {})
tree = {f["path"]: f.get("lfs") for f in json.load(urllib.request.urlopen(req, timeout=60))}
for p in want:
    print(tree[p]["oid"], tree[p]["size"], p)
PY

touch .verified
# Pass 1: files already present at the right size but not yet in .verified (e.g.
# fetched by an older downloader) are hashed in place instead of downloaded. Not on
# a helper pod (NO_FETCH=1): on Race's shared disks 36 GB of hashing took over 10
# billed minutes (2026-10-16) — a helper is either verified and joins at once, or
# steps aside in seconds.
if [ "${NO_FETCH:-0}" != 1 ]; then
  while read -r sha size path; do
    if ! grep -qx "$sha $path" .verified && [ "$(stat -c %s "$path" 2>/dev/null)" = "$size" ]; then
      ( [ "$(sha256sum "$path" | cut -d' ' -f1)" = "$sha" ] && echo "$sha $path" >> .verified ) &
    fi
  done < manifest.txt
  wait
fi

# Pass 2: whatever is still unverified must be downloaded.
need=0; todo=""
while read -r sha size path; do
  if grep -qx "$sha $path" .verified && [ "$(stat -c %s "$path" 2>/dev/null)" = "$size" ]; then
    echo "STATUS cached $path"
  else
    need=$((need + size)); todo="$todo $path"
  fi
done < manifest.txt

# A helper pod joins a render only if it is ready now: never a 40 GB download for it.
if [ "$need" -gt 0 ] && [ "${NO_FETCH:-0}" = 1 ]; then echo "STATUS needs_download $need"; exit 5; fi

free=$(df -B1 --output=avail / | tail -1)
echo "STATUS host_free $free need $need"
if [ "$need" -gt 0 ] && [ "$free" -lt $((need + MARGIN)) ]; then echo "STATUS disk_full"; exit 2; fi

AUTH=(); [ -n "$TOKEN" ] && AUTH=(-H "Authorization: Bearer $TOKEN")
fetch() {  # <sha> <bytes> <path>
  sha=$1; S=$2; p=$3; c=$(( (S + N - 1) / N ))
  mkdir -p "$(dirname "$p")"; rm -f "$p"; truncate -s "$S" "$p"
  for i in $(seq 0 $((N - 1))); do
    s=$((i * c)); e=$(( (i + 1) * c - 1 )); [ $e -ge $S ] && e=$((S - 1)); [ $s -gt $e ] && continue
    ( curl -fsSL --retry 8 --retry-delay 3 "${AUTH[@]}" -r "$s-$e" \
        "https://huggingface.co/$REPO/resolve/main/$p" \
      | dd of="$p" bs=4M seek="$s" oflag=seek_bytes conv=notrunc status=none ) &
  done
  wait
  if [ "$(sha256sum "$p" | cut -d' ' -f1)" = "$sha" ]; then
    echo "$sha $p" >> .verified; echo "STATUS verified $p"
  else
    rm -f "$p"; echo "STATUS bad_hash $p"
  fi
}

start=$(date +%s)
while read -r sha size path; do
  case " $todo " in *" $path "*) fetch "$sha" "$size" "$path" & ;; esac
done < manifest.txt
wait
echo "STATUS fetch_seconds $(( $(date +%s) - start )) bytes $need"

ok=1
while read -r sha size path; do
  grep -qx "$sha $path" .verified || ok=0
  mkdir -p "/opt/ComfyUI/models/$(dirname "$path")"
  ln -sf "$DEST/$path" "/opt/ComfyUI/models/$path"
done < manifest.txt
[ $ok = 1 ] && { echo "STATUS ready"; exit 0; }
echo "STATUS verify_failed"; exit 4
"""


def ensure_script() -> str:
    want = "[" + ", ".join(repr(p) for p in FILES) + "]"
    return (ENSURE_SCRIPT.replace("__DEST__", DEST).replace("__REPO__", REPO)
            .replace("__MARGIN__", str(MARGIN_BYTES)).replace("__WANT__", want))
