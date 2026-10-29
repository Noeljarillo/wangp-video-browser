"""Drive the real app in headless Chrome over CDP: navigate, run JS, screenshot.

Usage: python3 cdp_check.py <url> <out.png> ["js to evaluate before the screenshot"] [wait_ms]

Prints any console errors the page produced. Exit code 1 if the page threw.
"""
import asyncio
import base64
import json
import subprocess
import sys
import time
import urllib.request

import websockets

PORT = 9333


def ws_url():
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=1) as r:
                targets = json.load(r)
            for t in targets:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.25)
    raise SystemExit("no CDP target")


async def main():
    url = sys.argv[1]
    out = sys.argv[2]
    script = sys.argv[3] if len(sys.argv) > 3 else ""
    wait_ms = int(sys.argv[4]) if len(sys.argv) > 4 else 3500
    proc = subprocess.Popen([
        "google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
        "--user-data-dir=/tmp/cdp-profile", "--no-first-run", "--disable-gpu",
        "--window-size=1400,1000", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    errors = []
    try:
        async with websockets.connect(ws_url(), max_size=64 * 1024 * 1024) as ws:
            seq = 0

            async def send(method, params=None):
                nonlocal seq
                seq += 1
                await ws.send(json.dumps({"id": seq, "method": method, "params": params or {}}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("method") == "Runtime.exceptionThrown":
                        detail = msg["params"]["exceptionDetails"]
                        errors.append(detail.get("text", "") + " " +
                                      str((detail.get("exception") or {}).get("description", ""))[:200])
                    if msg.get("method") == "Log.entryAdded":
                        entry = msg["params"]["entry"]
                        if entry.get("level") == "error":
                            errors.append(entry.get("text", "")[:200])
                    if msg.get("id") == seq:
                        return msg.get("result", {})

            await send("Runtime.enable")
            await send("Log.enable")
            await send("Page.enable")
            await send("Page.navigate", {"url": url})
            await asyncio.sleep(wait_ms / 1000)
            if script:
                result = await send("Runtime.evaluate", {"expression": script, "awaitPromise": True,
                                                         "returnByValue": True})
                if result.get("exceptionDetails"):
                    errors.append(str(result["exceptionDetails"])[:300])
                elif result.get("result", {}).get("value") is not None:
                    print("js ->", json.dumps(result["result"]["value"])[:400])
                await asyncio.sleep(1.2)
            shot = await send("Page.captureScreenshot", {"format": "png"})
            with open(out, "wb") as fh:
                fh.write(base64.b64decode(shot["data"]))
            print("shot", out)
    finally:
        proc.terminate()
    for err in errors[:8]:
        print("PAGE ERROR:", err.replace("\n", " ")[:220])
    sys.exit(1 if errors else 0)


asyncio.run(main())
