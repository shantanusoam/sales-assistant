"""Deterministic parallel frame capture for the SalesCopilot launch film (`window.seek(t)` contract)."""
from __future__ import annotations

import asyncio
import http.server
import json
import shutil
import socketserver
import subprocess
import tempfile
import threading
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output"
AUDIO_PATH = ROOT / "audio" / "master.wav"
TIMELINE_PATH = ROOT / "timeline.json"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *args):
        pass


async def render_chunk(browser, url: str, start_f: int, end_f: int, fps: float, frames_dir: Path) -> None:
    page = await browser.new_page(viewport={"width": 1920, "height": 1080})
    await page.goto(url)
    await page.evaluate("window.READY")
    for f in range(start_f, end_f):
        t = f / fps
        await page.evaluate(f"window.seek({t:.6f})")
        out_file = frames_dir / f"f_{f:05d}.jpg"
        await page.screenshot(path=str(out_file), type="jpeg", quality=92)
    await page.close()


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tl = json.loads(TIMELINE_PATH.read_text())
    fps = float(tl["meta"]["fps"])
    dur = float(tl["meta"]["dur"])
    total_frames = int(round(dur * fps))

    httpd = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/index.html"

    with tempfile.TemporaryDirectory(prefix="copilot_frames_") as tmp:
        frames_dir = Path(tmp)
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            # Capture poster.png at frame 0
            poster_page = await browser.new_page(viewport={"width": 1920, "height": 1080})
            await poster_page.goto(url)
            await poster_page.evaluate("window.READY")
            await poster_page.evaluate("window.seek(0.2)")
            await poster_page.screenshot(path=str(OUT_DIR / "poster.png"), type="png")
            await poster_page.close()

            workers = 6
            chunk = (total_frames + workers - 1) // workers
            tasks = []
            for w in range(workers):
                s = w * chunk
                e = min(total_frames, (w + 1) * chunk)
                if s < e:
                    tasks.append(render_chunk(browser, url, s, e, fps, frames_dir))
            await asyncio.gather(*tasks)
            await browser.close()

        httpd.shutdown()

        mp4_path = OUT_DIR / "sales-copilot-pitch.mp4"
        webm_path = OUT_DIR / "sales-copilot-pitch.webm"

        # Encode H.264 MP4 + AAC 256k audio at constant 30 fps
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-framerate", str(int(fps)),
                "-i", str(frames_dir / "f_%05d.jpg"),
                "-i", str(AUDIO_PATH),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-crf", "18",
                "-preset", "fast",
                "-r", str(int(fps)),
                "-c:a", "aac",
                "-b:a", "256k",
                "-shortest",
                "-movflags", "+faststart",
                str(mp4_path),
            ],
            check=True,
        )

        # Also encode WebM artifact
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-i", str(mp4_path),
                "-c:v", "libvpx-vp9",
                "-b:v", "0",
                "-crf", "30",
                "-deadline", "realtime",
                "-cpu-used", "6",
                "-c:a", "libopus",
                "-b:a", "160k",
                str(webm_path),
            ],
            check=True,
        )
        print(f"Rendered {total_frames} frames -> {mp4_path} and {webm_path}")


if __name__ == "__main__":
    asyncio.run(main())
