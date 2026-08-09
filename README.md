# WanGP Video Browser

A local web app for browsing, previewing and **comparing** the videos produced by
[Wan2GP / WanGP](https://github.com/deepbeepmeep/Wan2GP).

WanGP embeds the complete generation settings as a JSON blob inside every video it
writes (the MP4 `©cmt` atom, or the `comment` tag for MKV/WEBM). This app reads that
blob back out, indexes every output it can find, and lets you play several results
side by side while it highlights exactly which settings changed between them.

![icon](icon.png)

## What it does

- **Auto-discovers your outputs.** On start it scans every `<PINOKIO_HOME>/api/*/app/outputs`
  folder, so an existing Wan2GP install is picked up with no configuration. Extra folders
  can be added from the UI and are remembered.
- **Reads the embedded generation settings** — prompt, seed, model, steps, flow shift,
  sampler, LoRAs, sliding-window settings, generation time and everything else WanGP records.
  MP4 parsing is pure Python, so no ffprobe is required to read metadata.
- **Preview** any result with the video on top and the full settings underneath, broken
  into readable groups, plus file and stream info (codec, resolution, fps, bitrate, audio).
- **Compare up to 4 videos** with a shared transport: play/pause all, a single scrubber,
  frame stepping, playback speed, loop and per-video audio solo. Each clip carries a
  frame-accurate readout (`0:01.25 · f30`) so you can cite an exact frame.
- **Three comparison modes**, because side-by-side alone hides small differences:
  - **Side by side** — up to 4 clips, the widest overview.
  - **Wipe** — two clips stacked in the same position with a draggable divider, for
    checking whether a detail actually moved.
  - **Blink** — swaps two clips in the exact same screen position, manually (`B`) or on an
    auto-flicker timer. The most effective way to make subtle differences pop; the
    highlighted tag always tells you which clip you are looking at.
- **Settings diff.** A table of every setting across the selected videos, with the
  differing rows highlighted and a "differences only" filter — so "what actually changed
  between these two runs?" is a one-glance answer.
- **Compare against outside files.** Drag any video into the window (or use
  *Load file to compare…*) to drop it into the compare tray; its embedded WanGP
  metadata is parsed in the browser.
- **Shareable links.** The *Link* button copies a URL that reopens the exact comparison
  in the same mode (`/?compare=<id>,<id>&mode=wipe`).
- **Light and dark themes.** Follows your system/Pinokio colour scheme automatically; the
  ◐ button in the header overrides it and the choice is remembered.

Only the Python standard library is required. `ffmpeg`/`ffprobe` are used when present
for thumbnails and exact stream info, and the app degrades gracefully without them.

## How to use it

1. **Install** — from the Pinokio sidebar (creates the venv).
2. **Start** — then **Open Web UI**.
3. Pick a video in the left list to inspect it in **Preview**.
4. Click the **+** on a card (or double-click the card) to add it to **Compare**.
   Add up to four, then use the transport bar to play them in sync.
5. With exactly two picked, switch to **Wipe** or **Blink** to overlay them in the same
   screen position — that is where small differences become obvious.
6. Read the **Settings diff** under the players to see what changed.

Useful shortcuts while in the Compare tab: `Space` play/pause all, `←`/`→` step one
frame (`Shift` for 10), `Home` jump to start, `B` swap the blink clips.

If your outputs live somewhere unusual, add the folder under the **Folders** tab.

## Running it outside Pinokio

```bash
cd app
python server.py --port 7899                     # auto-discovers outputs folders
python server.py --port 7899 --root /path/to/outputs --root /another/outputs
WANGP_OUTPUTS=/path/to/outputs python server.py  # or point it with an env var
```

It binds to `127.0.0.1` by default. Set `WANGP_BROWSER_VERBOSE=1` for request logging.

## API

The server exposes a small JSON API on the same port as the UI. Replace `7899` with
whatever port the launcher assigned (shown in the Terminal tab on start).

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/videos` | Full index: every video with its embedded metadata and probe info |
| `GET` | `/api/rescan` | Re-scan all folders and return the refreshed index |
| `GET` | `/media/<id>` | Stream the video file (supports HTTP `Range`) |
| `GET` | `/thumb/<id>` | JPEG thumbnail (404 if ffmpeg is unavailable) |
| `POST` | `/api/roots/add` | Body `{"path": "..."}` — index an extra folder, remembered across restarts |
| `POST` | `/api/roots/remove` | Body `{"path": "..."}` — stop indexing a folder |

Each entry in `videos` looks like:

```json
{
  "id": "21f731e98b9c1a2c",
  "name": "2026-08-09-02h28m28s_seed164194557_....mp4",
  "path": "/home/you/pinokio/api/wan.git/app/outputs/....mp4",
  "root": "/home/you/pinokio/api/wan.git/app/outputs",
  "rel": "....mp4",
  "size": 36538207,
  "mtime": 1786235353.0,
  "filename_info": { "date": "2026-08-09", "time": "02:28:28", "seed": 164194557, "tags": "duration=5s" },
  "probe": { "duration": 5.1667, "width": 2560, "height": 1408, "fps": 24.0,
             "codec": "h264", "bitrate": 56575284, "frames": 124, "has_audio": true },
  "meta": { "seed": 164194557, "prompt": "...", "model_type": "minimax_h3_fl2va_pruned",
            "num_inference_steps": 15, "flow_shift": 12, "resolution": "1280x704", "...": "..." }
}
```

`meta` is WanGP's own settings blob, passed through untouched — it is `{}` for videos
that carry no embedded metadata.

### curl

```bash
# List every indexed video with its seed and model
curl -s http://127.0.0.1:7899/api/videos |
  python3 -c "import json,sys;[print(v['meta'].get('seed'), v['meta'].get('model_type'), v['name']) for v in json.load(sys.stdin)['videos']]"

# Re-scan after a new generation finishes
curl -s http://127.0.0.1:7899/api/rescan > /dev/null

# Index another outputs folder
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"path":"/mnt/big-disk/wan-outputs"}' \
  http://127.0.0.1:7899/api/roots/add

# Download one video by id
curl -s -o clip.mp4 http://127.0.0.1:7899/media/21f731e98b9c1a2c
```

### Python

```python
import json, urllib.request

BASE = "http://127.0.0.1:7899"

def get(path):
    with urllib.request.urlopen(BASE + path) as response:
        return json.load(response)

def post(path, payload):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)

index = get("/api/videos")

# Which settings differ between the two most recent generations?
a, b = index["videos"][0]["meta"], index["videos"][1]["meta"]
for key in sorted(set(a) | set(b)):
    if a.get(key) != b.get(key):
        print(f"{key}: {a.get(key)!r} -> {b.get(key)!r}")

# Every run that used a given model, slowest first
runs = [v for v in index["videos"] if v["meta"].get("model_type") == "minimax_h3_fl2va_pruned"]
for video in sorted(runs, key=lambda v: v["meta"].get("generation_time", 0), reverse=True):
    print(video["meta"].get("generation_time"), video["meta"].get("num_inference_steps"), video["name"])

post("/api/roots/add", {"path": "/mnt/big-disk/wan-outputs"})
```

The same parsing is available without the server running:

```python
import sys
sys.path.insert(0, "app")
from server import read_video_metadata

print(read_video_metadata("/path/to/output.mp4")["seed"])
```

### JavaScript

```javascript
const BASE = "http://127.0.0.1:7899";

const index = await fetch(`${BASE}/api/videos`).then((r) => r.json());

// Group generations by seed to spot repeated experiments
const bySeed = new Map();
for (const video of index.videos) {
  const seed = video.meta?.seed ?? "unknown";
  bySeed.set(seed, [...(bySeed.get(seed) ?? []), video.name]);
}
console.log(bySeed);

// Build a compare permalink for the two newest results
const ids = index.videos.slice(0, 2).map((v) => v.id).join(",");
console.log(`${BASE}/?compare=${ids}`);

// Add another outputs folder
await fetch(`${BASE}/api/roots/add`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ path: "/mnt/big-disk/wan-outputs" }),
});
```

## Notes

- Metadata only exists in files WanGP wrote with metadata saving enabled
  (`metadata_type: "metadata"` in its server config, which is the default). Older or
  externally re-encoded files show up in the list with an empty `meta`.
- The index is cached in `app/.cache/` keyed by path + size + mtime, so rescans are cheap.
  **Reset** clears the venv and that cache; it never touches your videos.
- The server only ever reads your video files — nothing is modified, moved or deleted.
