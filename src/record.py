#!/usr/bin/env python3
"""
Record a browser session then convert output.
  python3 src/record.py https://mysite.com
  python3 src/record.py https://mysite.com --duration 30 --format gif
  python3 src/record.py https://mysite.com -o ~/Desktop/renders
"""

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path
from convert import convert


async def _record(url, duration, out_dir, width, height):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            record_video_dir=str(out_dir),
            record_video_size={"width": width, "height": height}
        )
        page = await context.new_page()
        print(f"── recording {url} for {duration}s...")
        await page.goto(url)
        await asyncio.sleep(duration)
        await context.close()
        await browser.close()


def record(url, fmt, duration, fps, width, height, out=None):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        asyncio.run(_record(url, duration, tmp_path, width, height))
        recorded = next(tmp_path.glob("*.webm"), None)
        if not recorded:
            print("recording failed — no webm produced")
            sys.exit(1)
        convert(recorded, fmt, fps, width, out=out, global_export=(out is None))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--duration", type=int, default=10)
    p.add_argument("--format", choices=["mp4", "gif", "webp", "all"], default="all")
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("-o", "--out", help="output directory (default: ~/Exports)")
    args = p.parse_args()
    record(args.url, args.format, args.duration, args.fps, args.width, args.height, args.out)
