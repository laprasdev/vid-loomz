#!/usr/bin/env python3
"""
Download video from URL then convert.
  python3 src/download.py js7F9EmZhpg          # prompts where to save, defaults both
  python3 src/download.py js7F9EmZhpg -e        # ~/Media/tmp/Video/Exports/yt/{file} only
  python3 src/download.py js7F9EmZhpg -.        # cwd only
  python3 src/download.py js7F9EmZhpg -o path   # explicit directory
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from convert import to_gif, to_webp, to_mp4, GLOBAL_EXPORTS

SECS_IN_MIN = 60
SECS_IN_HOUR = SECS_IN_MIN * SECS_IN_MIN

YT_ID_PATTERN = re.compile(r'^(?:v=|=)?([a-zA-Z0-9_-]{11})$')
YT_URL_PATTERNS = [
    re.compile(r'(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})'),
]
YT_TIME_PATTERN = re.compile(r'[?&]t=(\d+)')
NAME_TEMPLATE = "%(title)s_%(id)s"

def export_dest_for_log():
    return f"{GLOBAL_EXPORTS}/\u007bfile\u007d"

def extract_start_time(raw):
    """Extract ?t=SECONDS from a YouTube URL, returns seconds or None."""
    m = YT_TIME_PATTERN.search(raw)
    return int(m.group(1)) if m else None


def resolve_url(raw):
    if raw.startswith("http"):
        for pat in YT_URL_PATTERNS:
            m = pat.search(raw)
            if m:
                return f"https://youtube.com/watch?v={m.group(1)}"
        return raw
    m = YT_ID_PATTERN.match(raw)
    if m:
        return f"https://youtube.com/watch?v={m.group(1)}"
    return raw


def yt_dlp(url, *arguments, **run):
    # YouTube now requires cookies to pass its "confirm you're not a bot" check.
    # Pull them from a logged-in browser; override with DLYT_COOKIES_BROWSER (e.g. edge, chrome).
    browser = os.environ.get("DLYT_COOKIES_BROWSER", "brave")
    return subprocess.run(["yt-dlp", "--cookies-from-browser", browser, *arguments, url], **run)


def sanitize(name):
    name = re.sub(r'[^\w\s\-.]', '', name).strip()
    return re.sub(r'\s+', '_', name)


def fetch_name(url):
    """Name a download after its title and id, so no two videos share a folder or a file."""
    r = yt_dlp(url, "--print", NAME_TEMPLATE, capture_output=True, text=True)
    name = sanitize(r.stdout)
    if r.returncode != 0 or not name:
        sys.exit(f"could not read the title of {url}\n{r.stderr.strip()}")
    return name


def get_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0


def file_size_mb(path):
    return path.stat().st_size / (1024 * 1024)


def fmt_dur(s):
    return f"{int(s // SECS_IN_MIN)}:{int(s % SECS_IN_MIN):02d}"


def parse_time(t):
    """Parse time string like '1:30', '90', '0:05' into seconds."""
    t = t.strip()
    if ":" in t:
        parts = t.split(":")
        if len(parts) == 2:
            return int(parts[0]) * SECS_IN_MIN + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * SECS_IN_HOUR + int(parts[1]) * SECS_IN_MIN + float(parts[2])
    return float(t)


def prompt_dest_during_download(cwd):
    print(f"\n  [E] {export_dest_for_log()} only")
    print(f"  [.] {cwd} only")
    print(f"  [enter] both\n")
    try:
        return input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return ""


def resolve_destinations(choice, name, cwd):
    dests = []
    if choice == "e":
        dests.append(GLOBAL_EXPORTS / name)
    elif choice == ".":
        dests.append(cwd / name)
    else:
        dests.append(GLOBAL_EXPORTS / name)
        dests.append(cwd / name)
    for d in dests:
        d.mkdir(parents=True, exist_ok=True)
    return dests


def prompt_twitter_safe(mp4_path, name, dests, dur, start_time=None):
    """Sub-menu for twitter-safe GIF generation with time range control."""
    chunk = 15
    num_chunks = int(dur // chunk) + (1 if dur % chunk > 0 else 0)
    default_ss = start_time or 0
    default_end = min(default_ss + chunk, dur)
    print(f"\n── twitter-safe gif (15s chunks, 720px) — video is {fmt_dur(dur)} ({num_chunks} chunks)")
    print()
    print(f"  [enter]  15s from {fmt_dur(default_ss)} ({fmt_dur(default_ss)}–{fmt_dur(default_end)})")
    print(f"  [a]      all {num_chunks} chunks")
    print(f"  [t]      custom start time (e.g. 1:30)")
    print(f"  [r]      custom range (e.g. 1:30-2:00) → split into 15s chunks")
    print(f"  [c]      compress range to 15s (e.g. 90s range → 6× speed)")
    print(f"  [N]      chunk number (e.g. 3 = 0:30–0:45)")
    print(f"  [N-M]    chunk range (e.g. 2-5)")

    try:
        sel = input("\n> ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    segments = []  # list of (start_sec, duration_sec, suffix, speed)

    if not sel:
        suffix = "_twitter" if default_ss == 0 else f"_twitter_{fmt_dur(default_ss).replace(':', 'm')}s"
        segments.append((default_ss, default_end - default_ss, suffix, 1.0))

    elif sel.lower() == "a":
        for i in range(num_chunks):
            ss = i * chunk
            t = min(chunk, dur - ss)
            segments.append((ss, t, f"_twitter_{i+1}", 1.0))

    elif sel.lower() == "t":
        try:
            ts = input("  start time: ").strip()
            ss = parse_time(ts)
            t = min(chunk, dur - ss)
            if t <= 0:
                print("  ⚠ start time is past end of video")
                return
            suffix = f"_twitter_{fmt_dur(ss).replace(':', 'm')}s"
            segments.append((ss, t, suffix, 1.0))
        except (ValueError, EOFError, KeyboardInterrupt):
            print("  ⚠ invalid time")
            return

    elif sel.lower() == "r":
        try:
            rng = input("  range (start-end, e.g. 1:30-2:00 or 1:30-end): ").strip()
            if "-" not in rng:
                print("  ⚠ expected format: start-end")
                return
            parts = rng.split("-", 1)
            # handle "end" keyword
            if parts[0].strip() == "":
                print("  ⚠ missing start time")
                return
            ss = parse_time(parts[0].strip())
            if parts[1].strip().lower() == "end":
                end = dur
            else:
                end = parse_time(parts[1].strip())
            if end <= ss:
                print("  ⚠ end must be after start")
                return
            end = min(end, dur)
            # split into 15s chunks
            i = 0
            pos = ss
            while pos < end:
                t = min(chunk, end - pos)
                i += 1
                suffix = f"_twitter_{fmt_dur(pos).replace(':', 'm')}s"
                segments.append((pos, t, suffix, 1.0))
                pos += chunk
        except (ValueError, EOFError, KeyboardInterrupt):
            print("  ⚠ invalid range")
            return

    elif sel.lower() == "c":
        try:
            rng = input("  range to compress to 15s (start-end, e.g. 0:15-1:45 or 0:15-end): ").strip()
            if "-" not in rng:
                print("  ⚠ expected format: start-end")
                return
            parts = rng.split("-", 1)
            if parts[0].strip() == "":
                print("  ⚠ missing start time")
                return
            ss = parse_time(parts[0].strip())
            if parts[1].strip().lower() == "end":
                end = dur
            else:
                end = parse_time(parts[1].strip())
            if end <= ss:
                print("  ⚠ end must be after start")
                return
            end = min(end, dur)
            total = end - ss
            if total <= chunk:
                print(f"  ⚠ range is {total:.1f}s — already ≤ 15s, use [r] or [t] instead")
                return
            speed = total / chunk
            suffix = f"_twitter_cmp_{fmt_dur(ss).replace(':', 'm')}s_{speed:.1f}x"
            segments.append((ss, total, suffix, speed))
        except (ValueError, EOFError, KeyboardInterrupt):
            print("  ⚠ invalid range")
            return

    elif "-" in sel and sel[0].isdigit():
        # chunk range like 2-5
        try:
            a, b = sel.split("-", 1)
            a, b = int(a), int(b)
            if a < 1 or b > num_chunks or a > b:
                print(f"  ⚠ valid chunk range: 1-{num_chunks}")
                return
            for i in range(a, b + 1):
                ss = (i - 1) * chunk
                t = min(chunk, dur - ss)
                segments.append((ss, t, f"_twitter_{i}", 1.0))
        except (ValueError, EOFError, KeyboardInterrupt):
            print("  ⚠ invalid chunk range")
            return

    elif sel.isdigit():
        # single chunk number
        n = int(sel)
        if n < 1 or n > num_chunks:
            print(f"  ⚠ valid chunks: 1-{num_chunks}")
            return
        ss = (n - 1) * chunk
        t = min(chunk, dur - ss)
        segments.append((ss, t, f"_twitter_{n}", 1.0))

    else:
        print("  ⚠ unrecognized input")
        return

    if not segments:
        return

    print(f"\n  generating {len(segments)} gif{'s' if len(segments) > 1 else ''}...")
    for ss, t, suffix, speed in segments:
        if speed != 1.0:
            print(f"  ⌐ {fmt_dur(ss)}–{fmt_dur(ss + t)} → 15s @ {speed:.2f}× speed")
        else:
            print(f"  ⌐ {fmt_dur(ss)}–{fmt_dur(ss + t)}")
        for d in dests:
            to_gif(mp4_path, d / f"{name}{suffix}.gif", 15, 720, ss=ss, t=t, speed=speed)


def prompt_formats(mp4_path, name, dests, fps, width, start_time=None):
    dur = get_duration(mp4_path)
    size = file_size_mb(mp4_path)

    print(f"\n── mp4 saved ({size:.1f}MB, {fmt_dur(dur)})")

    if dur > 140:
        print("  ⚠ exceeds twitter video limit (2:20)")
    if size > 25:
        print("  ⚠ exceeds discord free upload limit (25MB)")
    if dur > 60:
        print("  ℹ gif at this length will be very large")

    print("\n  [1] gif")
    print("  [2] webp")
    print("  [3] both")
    if dur > 15:
        print("  [4] gif — twitter-safe (15s chunks, 720px)")
    print("  [enter] skip")

    try:
        choice = input("\n> ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    for d in dests:
        if choice == "1":
            to_gif(mp4_path, d / f"{name}.gif", fps, width)
        elif choice == "2":
            to_webp(mp4_path, d / f"{name}.webp", fps, width)
        elif choice == "3":
            to_gif(mp4_path, d / f"{name}.gif", fps, width)
            to_webp(mp4_path, d / f"{name}.webp", fps, width)
        elif choice == "4":
            prompt_twitter_safe(mp4_path, name, dests, dur, start_time)


def do_download(url, tmp_dir):
    dl = Path(tmp_dir) / "download.mp4"
    yt_dlp(
        url,
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", str(dl),
        check=True,
    )
    found = next(Path(tmp_dir).glob("*.mp4"), None)
    if not found:
        print("download failed — no mp4 produced")
        sys.exit(1)
    return found


def prompt_clip(mp4_path, name, dests, start_time, dur):
    """Prompt for clip duration and save a clip MP4 + twitter GIF from start_time."""
    remaining = dur - start_time
    print(f"\n── timestamp detected: {fmt_dur(start_time)} (video is {fmt_dur(dur)})")
    print(f"  save a clip starting at {fmt_dur(start_time)}?")
    print(f"\n  [enter]  15s clip")
    print(f"  [N]      clip duration in seconds (max {int(remaining)})")
    print(f"  [s]      skip clip")

    try:
        sel = input("\n> ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if sel.lower() == "s":
        return

    if not sel:
        clip_dur = min(15, remaining)
    else:
        try:
            clip_dur = min(parse_time(sel), remaining)
        except ValueError:
            print("  ⚠ invalid duration")
            return

    if clip_dur <= 0:
        print("  ⚠ no time remaining from that start")
        return

    clip_suffix = f"_clip_{fmt_dur(start_time).replace(':', 'm')}s"
    print(f"  clipping {fmt_dur(start_time)}–{fmt_dur(start_time + clip_dur)}...")
    for d in dests:
        clip_path = d / f"{name}{clip_suffix}.mp4"
        to_mp4(mp4_path, clip_path, ss=start_time, t=clip_dur)
        print(f"  ✓ {clip_path}")

    # offer a twitter gif of the clip too
    if clip_dur >= 15:
        gif_dur = 15
    else:
        gif_dur = clip_dur
    print(f"\n  gif of clip? ({fmt_dur(start_time)}–{fmt_dur(start_time + gif_dur)}, 720px)")
    print(f"  [enter] yes  [s] skip")
    try:
        gif_sel = input("\n> ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if gif_sel.lower() != "s":
        for d in dests:
            gif_path = d / f"{name}{clip_suffix}_twitter.gif"
            to_gif(mp4_path, gif_path, 15, 720, ss=start_time, t=gif_dur)
            print(f"  ✓ {gif_path}")


def download(url, fmt, fps, width, dest_mode=None, out=None, interactive=True, clean=False, start=None):
    start_time = extract_start_time(url) if start is None else start
    url = resolve_url(url)
    name = fetch_name(url)
    cwd = Path.cwd()

    print(f"── downloading {url}")
    print(f"── {name}")
    if start_time is not None:
        print(f"── timestamp: {fmt_dur(start_time)}")

    if out:
        dests = [Path(out) / name]
        dests[0].mkdir(parents=True, exist_ok=True)
    elif dest_mode == "e":
        dests = resolve_destinations("e", name, cwd)
    elif dest_mode == ".":
        dests = resolve_destinations(".", name, cwd)
    elif interactive:
        dest_choice = prompt_dest_during_download(cwd)
        dests = resolve_destinations(dest_choice, name, cwd)
    else:
        dests = resolve_destinations("", name, cwd)

    with tempfile.TemporaryDirectory() as tmp:
        found = do_download(url, tmp)
        for d in dests:
            mp4 = d / f"{name}.mp4"
            shutil.copy(found, mp4)
            print(f"  ✓ {mp4}")

    primary = dests[0] / f"{name}.mp4"
    dur = get_duration(primary)

    # if a timestamp was provided, offer clip extraction before format menu
    if start_time is not None and interactive and start_time < dur:
        prompt_clip(primary, name, dests, start_time, dur)

    if fmt == "all":
        for d in dests:
            to_gif(primary, d / f"{name}.gif", fps, width)
            to_webp(primary, d / f"{name}.webp", fps, width)
        for d in dests:
            print(f"── outputs in {d}")
        return

    if fmt == "gif":
        for d in dests:
            to_gif(primary, d / f"{name}.gif", fps, width)
            if clean:
                (d / f"{name}.mp4").unlink(missing_ok=True)
        return

    if fmt == "webp":
        for d in dests:
            to_webp(primary, d / f"{name}.webp", fps, width)
            if clean:
                (d / f"{name}.mp4").unlink(missing_ok=True)
        return

    if interactive:
        prompt_formats(primary, name, dests, fps, width, start_time)

    for d in dests:
        print(f"── outputs in {d}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url", help="full URL, YouTube video ID, or =ID")
    p.add_argument("--format", choices=["mp4", "gif", "webp", "all"], default="mp4")
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--width", type=int, default=960)
    p.add_argument("-o", "--out", help="explicit output directory")
    p.add_argument("-e", action="store_true", help=f"save to ~/{export_dest_for_log()} only")
    p.add_argument("-.", dest="local", action="store_true", help="save to cwd only")
    p.add_argument("-t", "--start", help="start time for clip (seconds or mm:ss, overrides ?t= in URL)")
    p.add_argument("-c", "--clean", action="store_true", help="remove source mp4 after conversion")
    p.add_argument("--no-prompt", action="store_true", help="skip interactive prompts")
    args = p.parse_args()

    dest_mode = None
    if args.e:
        dest_mode = "e"
    elif args.local:
        dest_mode = "."

    start = parse_time(args.start) if args.start else None

    download(args.url, args.format, args.fps, args.width,
             dest_mode, args.out, not args.no_prompt, args.clean, start)
