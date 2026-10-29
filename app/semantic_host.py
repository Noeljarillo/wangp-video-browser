"""Core side of P4.1 semantic search. Standard library only (C1).

The analysis worker (add-on venv) owns the SigLIP text encoder and the frame
embedding matrix; it listens on a loopback port published in
app/.cache/semantic/port.json. The core forwards the query there and maps the
returned file paths back to library ids.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PORT_FILE = Path(__file__).resolve().parent / ".cache" / "semantic" / "port.json"


def _port(port_file=PORT_FILE):
    try:
        return int(json.loads(Path(port_file).read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def search(query, entries_by_path, k=50, port_file=PORT_FILE, timeout=5.0):
    """Returns {"available": bool, "results": [{id, time, frame, score}], ...}."""
    query = (query or "").strip()
    if not query:
        return {"available": True, "results": []}
    port = _port(port_file)
    if not port:
        return {"available": False, "reason": "Content search needs the analysis add-on running.", "results": []}
    url = f"http://127.0.0.1:{port}/search?" + urllib.parse.urlencode({"q": query, "k": int(k)})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as error:
        return {"available": False, "reason": f"Analysis worker not reachable ({error}).", "results": []}
    results = []
    for hit in body.get("results", []):
        entry = entries_by_path.get(hit.get("path"))
        if entry:
            results.append({"id": entry["id"], "time": hit.get("time", 0), "frame": hit.get("frame", 0),
                            "score": hit.get("score", 0)})
    return {"available": True, "results": results, "clips": body.get("clips", 0),
            "ms": body.get("ms_total"), "ms_text": body.get("ms_text")}
