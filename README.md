<div align="center">

<img src="icon.png" width="96" alt="WanGP Video Browser icon">

# WanGP Video Browser

### A local library, inspector and A/B comparison tool for AI-generated video

**Browse your Wan2GP (WanGP) outputs, see the full generation recipe of every clip,
and find out exactly what changed between two runs.**

1-click install for [Pinokio](https://pinokio.co) · works with [Wan2GP / WanGP](https://github.com/deepbeepmeep/Wan2GP) out of the box ·
any folder of MP4s (ComfyUI, LTX, Hunyuan…) can be browsed too · no dependencies, no account, nothing leaves your machine

![WanGP Video Browser: library, player and the full generation recipe of the selected clip](screenshots/preview.jpg)

</div>

---

## Why

Generating video with Wan 2.x, LTX-Video, Hunyuan or any other model in WanGP leaves you with
a folder of 30 MB clips with 200-character filenames. When you are dialling in a shot you end up
with a dozen near-identical takes. Was the good one 20 steps or 8? Did the flow shift matter, or
was it just a luckier seed?

The answer is already inside every file: **WanGP writes the full generation settings as JSON into
the MP4 itself**. Nothing reads it back, so that knowledge is stuck in files you can't tell apart.

This app reads it back and builds a proper video library on top of it.

## Features

| | |
| --- | --- |
| **Video library** | Every clip indexed with thumbnails. Search by prompt, seed, model or filename; sort by date, size, duration or render time. Hover a thumbnail to scrub it. |
| **Generation recipe** | Seed, steps, guidance, flow shift, solver, resolution, frames, LoRAs with weights and render time, colour-coded and copied with one click. |
| **Readable prompts** | Structured WanGP prompts split into summary, description and subject sections, with placeholders like *Subject 1* and *Shot 2* highlighted. |
| **A/B comparison** | Up to four clips on one synced transport: play, scrub and frame-step them together, solo any clip's audio. |
| **Settings diff** | Only the settings that differ between runs, with a word-by-word prompt diff. |
| **Wipe & blink** | Overlay two takes in the same screen position and drag a divider, or flicker between them so motion differences jump out. |
| **Mobile** | A real phone layout with bottom navigation, sheet previews and full-screen wipe. Open it over your LAN through Pinokio. |
| **Local & private** | Pure-Python standard library server on `127.0.0.1`. Read-only on your files. No telemetry, no CDN, no external requests. |

---

## Compare two generations

![Comparing two AI video generations side by side with a settings diff](screenshots/compare.jpg)

Put up to four clips side by side on one shared transport. Underneath, the **settings diff** lays
WanGP's ~50 settings side by side and shows only the rows that differ. Two runs of the same prompt
usually come down to a handful of rows: seed, steps, model weights. When the prompt itself
changed, it is diffed **word by word**, so a three-word edit in a 400-word prompt stands out.

## Catch differences too subtle for side by side

![Wipe comparison of two AI video takes](screenshots/wipe.jpg)

Two clips a few pixels apart look the same next to each other, so two more modes put them in the
**same screen position**:

- **Wipe**: stack them and drag the divider across.
- **Blink**: swap between them in place, by hand (`B`) or on an auto-flicker timer. Whatever
  moved jumps straight out. The highlighted tag always shows which clip you are looking at.

## On your phone

<img src="screenshots/mobile.jpg" width="290" alt="AI video library on mobile"> <img src="screenshots/mobile-cmp.jpg" width="290" alt="Wipe comparison on mobile">

Not a shrunk desktop layout. The library becomes a contact sheet, navigation moves to a bottom
bar, preview arrives as a sheet, and comparison defaults to wipe because two 195-pixel frames side
by side tell you nothing. The settings diff turns into stacked cards.

## Look and feel

A dark, pro-app interface in the style of desktop video editors: neutral greys that don't skew
how you judge colour, one accent for anything clickable, and clip-label colours that carry
meaning (seed, sampling, size, timing, LoRAs). A light theme is one click away and remembered.

---

## Install

**In Pinokio:** *Discover → Download from URL* →

```
https://github.com/Noeljarillo/wangp-video-browser
```

Then **Install** → **Start** → **Open Web UI**. Install takes seconds — there are no
Python dependencies to download.

It auto-discovers every `<PINOKIO_HOME>/api/*/app/outputs` folder, so an existing Wan2GP
install just shows up. Anything elsewhere can be added from the **Folders** tab and is remembered.

<details>
<summary><b>Running it outside Pinokio</b></summary>

```bash
cd app
python server.py                                 # http://127.0.0.1:7899, auto-discovers outputs
python server.py --root /path/to/outputs --root /another/outputs
WANGP_OUTPUTS=/path/to/outputs python server.py  # or point it with an env var
```

Python 3.8+, standard library only. Binds to `127.0.0.1`. Set `WANGP_BROWSER_VERBOSE=1` for
request logging.
</details>

---

## How to use it

1. Pick a clip in the left list to inspect it in **Preview**.
2. Click **+** on a card (or double-click it) to add it to **Compare** — up to four.
3. With exactly two picked, switch to **Wipe** or **Blink**.
4. Read the **Settings diff** underneath to see what changed.
5. Hit **Link** to copy a URL that reopens that exact comparison, in that exact mode.

**Little things that add up:** sweep your mouse across any thumbnail to scrub that clip without
opening it · drag the divider between the library and the content to resize it, or collapse it
entirely for full-width comparison — both are remembered · every video uses a purpose-built
transport with a frame counter rather than the browser's default controls.

**Keyboard** (Compare tab): `Space` play/pause all · `←` `→` step one frame (`Shift` for 10) ·
`Home` back to start · `B` swap the blink clips. The wipe divider and the scrubber are both
focusable and driven with the arrow keys.

**Comparing something from outside your outputs folder?** Drag any video onto the window. Its
embedded WanGP metadata gets parsed in the browser and it joins the compare tray like any other.

---

## Requirements

- **Pinokio** (or any Python 3.8+).
- **Nothing else.** Metadata is parsed with a pure-Python MP4 box reader, so `ffprobe` isn't needed.
  The interface ships its own fonts, so it looks identical offline and on every machine.
- `ffmpeg`/`ffprobe` are used **if present** for thumbnails and exact stream info, and the app
  degrades gracefully without them.

Videos need to have been written by WanGP with metadata saving on (`metadata_type: "metadata"`,
its default) for the settings panel and diff. Older or re-encoded files still appear, just with
empty settings.

### FAQ

**Does it work with ComfyUI?** Yes. Add a ComfyUI `output` folder from the **Folders** tab. Clips
saved by VideoHelperSuite (Video Combine) carry the workflow, and the browser turns it into the same
recipe, filters and settings diff as a WanGP clip (seed, steps, CFG, sampler, resolution, prompts,
LoRAs, model). **Workflow** in the preview header copies the embedded workflow JSON.

**Which formats?** MP4, MOV, M4V, MKV, WebM and AVI are indexed. Generation settings are read
without ffmpeg from MP4/MOV/M4V and MKV/WebM tags (ffprobe is used as a fallback for anything else).
See *Formats* below.

#### Formats

| Generator | Where the settings are | Read |
| --- | --- | --- |
| WanGP / Wan2GP | JSON in the `comment` tag | Every setting, unchanged |
| ComfyUI (VideoHelperSuite) | `prompt` + `workflow` JSON in `comment` (or separate tags) | KSampler, KSamplerAdvanced, SamplerCustom(Advanced), WanVideo wrapper; LoRA, UNet and checkpoint loaders. Raw graph kept |
| A1111 / Forge / SD.Next | `parameters` text block (`Steps: 20, Sampler: ...`) in `parameters`, `comment` or `description` | Prompt, negative, every `Key: value` pair, `<lora:name:weight>` |
| LTX-Video | Argument JSON in `comment` / `description`, when a script embeds it | Prompt, seed, steps, guidance, size, frames, STG and other args |
| HunyuanVideo | Argument JSON in `comment` / `description`, when a script embeds it | Prompt, seed, steps, guidance, `video_size`, frames, model |

LTX-Video's and HunyuanVideo's own scripts do not embed settings by default; files without metadata
are simply listed without a recipe. Anything else stays exactly as written in the file.

**Does it change my files?** No. The server only reads them.

**Which port?** `7899` by default, chosen to stay clear of the port Pinokio assigns to Wan2GP.
If it is taken the next free port is used; set `WANGP_BROWSER_PORT` to choose.

---

## API

The server exposes a small JSON API on the same port as the UI. It listens on `7899` by
default — a fixed port, so it never collides with Wan2GP's launcher-assigned one. If 7899 is
taken it moves to the next free port and prints the address in the Terminal tab. Set
`WANGP_BROWSER_PORT` to pick a different one.

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

- The index is cached in `app/.cache/` keyed by path + size + mtime, so rescans are cheap.
  **Reset** clears the venv and that cache; it never touches your videos.
- The server only ever **reads** your video files — nothing is modified, moved or deleted.
- Thumbnails double as poster frames, so clips show a real still instead of a black box
  before you press play.
- Colours are checked against WCAG AA in both themes, every control is reachable from the
  keyboard, and all motion is disabled under `prefers-reduced-motion`.

## Credits

UI typeface is [Source Sans 3](https://github.com/adobe-fonts/source-sans) with
[IBM Plex Mono](https://github.com/IBM/plex) for file names and timecode, both bundled under the
[SIL Open Font License 1.1](app/web/fonts/LICENSE.txt) so the app renders identically offline
and on every device. Icons are drawn in the page: no icon font, no CDN, no external requests
of any kind.

<sub>Keywords: Wan2GP, WanGP, Wan 2.1, Wan 2.2, AI video generation, video generation output
browser, generation metadata viewer, seed and settings comparison, A/B video comparison, Pinokio,
ComfyUI output folder, local AI video gallery.</sub>
