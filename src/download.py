#!/usr/bin/env python3
"""
Download a video, then clip and convert it. Nothing is asked: every choice has a default and a flag.
  python3 src/download.py js7F9EmZhpg                  # mp4 into the exports folder and the current folder
  python3 src/download.py js7F9EmZhpg -.               # current folder only
  python3 src/download.py js7F9EmZhpg -e               # exports folder only
  python3 src/download.py js7F9EmZhpg -o path          # an explicit folder
  python3 src/download.py js7F9EmZhpg --format gif     # a gif as well (gif, webp or all; -g is --format gif)
  python3 src/download.py js7F9EmZhpg -t 10:20 -g      # seconds 10 to 20 only, as an mp4 and a gif
  python3 src/download.py js7F9EmZhpg -t 10            # second 10 to the end
  python3 src/download.py "js7F9EmZhpg?t=90"           # a timestamp also cuts a 15 s clip there, and a gif of it
  python3 src/download.py js7F9EmZhpg --twitter 2-5    # twitter-safe gifs of 15 s chunks 2 to 5
"""

import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from convert import to_gif, to_webp, to_mp4, GLOBAL_EXPORTS

SECS_IN_MIN = 60
SECS_IN_HOUR = SECS_IN_MIN * SECS_IN_MIN

YT_ID_PATTERN = re.compile(r'^(?:v=|=)?([a-zA-Z0-9_-]{11})$')
YT_URL_PATTERNS = [
    re.compile(r'(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})'),
]
YT_TIME_PATTERN = re.compile(r'[?&]t=(\d+)')
NAME_TEMPLATE = "%(title)s_%(id)s"
LENGTH_TEMPLATE = "%(duration)s"
UNKNOWN_LENGTH = "NA"  # what yt-dlp prints for a length it does not know, as for a live stream

CLIP_SECONDS = 15  # the clip cut where a timestamp points, unless --clip says otherwise
TWITTER_CHUNK_SECONDS, TWITTER_FPS, TWITTER_WIDTH = 15, 15, 720
TWITTER_VIDEO_LIMIT_SECONDS, DISCORD_LIMIT_MB, LARGE_GIF_SECONDS = 140, 25, 60
TWITTER_FROM_START = "start"
TWITTER_EVERY_CHUNK = "all"
CHUNK_NUMBER = re.compile(r"^(\d+)$")
CHUNK_NUMBERS = re.compile(r"^(\d+)-(\d+)$")
RANGE_END = "end"
SPAN_SEPARATOR = ":"
SECTION_END = "inf"  # yt-dlp's name for the end of the video in --download-sections


@dataclass(frozen=True)
class Segment:
    """One stretch of the video to make a gif of."""
    start: float
    seconds: float
    suffix: str
    speed: float = 1.0


@dataclass(frozen=True)
class Span:
    """The stretch of the video to keep, in seconds; end is None for the end of the video."""
    start: float
    end: Optional[float]

    def section(self):
        return f"*{self.start}-{SECTION_END if self.end is None else self.end}"

    def suffix(self):
        return f"_{time_suffix(self.start)}-{RANGE_END if self.end is None else time_suffix(self.end)}"

    def describe(self):
        return f"{fmt_dur(self.start)}–{RANGE_END if self.end is None else fmt_dur(self.end)}"


def export_dest_for_log():
    return f"{GLOBAL_EXPORTS}/{{file}}"


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


@dataclass(frozen=True)
class Video:
    """A video's name, after its title and id so no two downloads share a folder or a file, and its length if known."""
    name: str
    seconds: Optional[float]


def fetch_video(url):
    r = yt_dlp(url, "--print", NAME_TEMPLATE, "--print", LENGTH_TEMPLATE, capture_output=True, text=True)
    lines = r.stdout.splitlines()
    if r.returncode != 0 or len(lines) != 2 or not sanitize(lines[0]):
        sys.exit(f"could not read the title and length of {url}\n{r.stderr.strip()}")
    return Video(sanitize(lines[0]), None if lines[1] == UNKNOWN_LENGTH else float(lines[1]))


def check_span(span, video):
    """Refuse a span the video cannot give before anything is made; an end past the video's end means its end."""
    if video.seconds is None:
        sys.exit("-t: this video's length is not known, so it cannot be cut")
    if span.start >= video.seconds:
        sys.exit(f"-t {span.describe()}: the video is only {fmt_dur(video.seconds)} long")


def get_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        sys.exit(f"could not read the length of {path}")


def file_size_mb(path):
    return path.stat().st_size / (1024 * 1024)


def fmt_dur(s):
    return f"{int(s // SECS_IN_MIN)}:{int(s % SECS_IN_MIN):02d}"


def time_suffix(seconds):
    return fmt_dur(seconds).replace(':', 'm') + "s"


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


def time_argument(text):
    try:
        return parse_time(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a time: {text!r} (use seconds or m:ss)")


def twitter_argument(text):
    """Check the shape of a --twitter choice now; whether it fits the video is checked once its length is known."""
    if text in (TWITTER_FROM_START, TWITTER_EVERY_CHUNK) or CHUNK_NUMBER.match(text) or CHUNK_NUMBERS.match(text):
        return text
    if ":" in text:
        range_argument(text) if "-" in text else time_argument(text)
        return text
    raise argparse.ArgumentTypeError(
        f"not a twitter choice: {text!r} (start, all, a chunk N, chunks N-M, a start m:ss or a range m:ss-m:ss)")


def range_argument(text):
    """'1:30-2:00' or '1:30-end' as (start, end); end is None for the end of the video."""
    start, separator, end = text.partition("-")
    if not separator or not start.strip():
        raise argparse.ArgumentTypeError(f"not a range: {text!r} (use m:ss-m:ss or m:ss-end)")
    return time_argument(start), None if end.strip().lower() == RANGE_END else time_argument(end)


def span_argument(text):
    """'10' as second 10 to the end, '10:20' as seconds 10 to 20."""
    start, separator, end = text.partition(SPAN_SEPARATOR)
    try:
        span = Span(float(start), float(end) if separator else None)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a span: {text!r} (use S for second S to the end, or S:E for seconds S to E)")
    if span.start < 0 or (span.end is not None and span.end <= span.start):
        raise argparse.ArgumentTypeError(f"not a span: {text!r} (the start must be 0 or more and the end after it)")
    return span


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


def report(mp4_path):
    """The mp4's size and length, with the limits it runs past."""
    dur = get_duration(mp4_path)
    size = file_size_mb(mp4_path)
    print(f"\n── mp4 saved ({size:.1f}MB, {fmt_dur(dur)})")
    if dur > TWITTER_VIDEO_LIMIT_SECONDS:
        print(f"  ⚠ exceeds twitter video limit ({fmt_dur(TWITTER_VIDEO_LIMIT_SECONDS)})")
    if size > DISCORD_LIMIT_MB:
        print(f"  ⚠ exceeds discord free upload limit ({DISCORD_LIMIT_MB}MB)")
    if dur > LARGE_GIF_SECONDS:
        print("  ℹ gif at this length will be very large")
    return dur


def chunk(number, dur):
    start = (number - 1) * TWITTER_CHUNK_SECONDS
    return Segment(start, min(TWITTER_CHUNK_SECONDS, dur - start), f"_twitter_{number}")


def chunks_between(start, end):
    """A range split into twitter-length chunks, each named after where it starts."""
    segments, position = [], start
    while position < end:
        segments.append(Segment(position, min(TWITTER_CHUNK_SECONDS, end - position), f"_twitter_{time_suffix(position)}"))
        position += TWITTER_CHUNK_SECONDS
    return segments


def twitter_segments(which, dur, start_time):
    """The stretches a --twitter choice names, checked against the video's length."""
    chunk_count = math.ceil(dur / TWITTER_CHUNK_SECONDS)
    if which == TWITTER_FROM_START:
        start = start_time or 0
        suffix = "_twitter" if start == 0 else f"_twitter_{time_suffix(start)}"
        return [Segment(start, min(TWITTER_CHUNK_SECONDS, dur - start), suffix)]
    if which == TWITTER_EVERY_CHUNK:
        return [chunk(number, dur) for number in range(1, chunk_count + 1)]
    numbers = CHUNK_NUMBERS.match(which) or CHUNK_NUMBER.match(which)
    if numbers:
        first, last = int(numbers.group(1)), int(numbers.groups()[-1])
        if not 1 <= first <= last <= chunk_count:
            sys.exit(f"--twitter {which}: this video has chunks 1 to {chunk_count}")
        return [chunk(number, dur) for number in range(first, last + 1)]
    if "-" in which:
        start, end = range_argument(which)
        end = dur if end is None else min(end, dur)
        if end <= start:
            sys.exit(f"--twitter {which}: the end must come after the start, within {fmt_dur(dur)}")
        return chunks_between(start, end)
    start = parse_time(which)
    if start >= dur:
        sys.exit(f"--twitter {which}: the video is only {fmt_dur(dur)} long")
    return [Segment(start, min(TWITTER_CHUNK_SECONDS, dur - start), f"_twitter_{time_suffix(start)}")]


def squeezed_segment(squeeze, dur):
    """A range of any length sped up to fit one twitter-length gif."""
    start, end = squeeze
    end = dur if end is None else min(end, dur)
    if end - start <= TWITTER_CHUNK_SECONDS:
        sys.exit(f"--twitter-squeeze: that range is {end - start:.1f}s, already short enough; use --twitter with it instead")
    speed = (end - start) / TWITTER_CHUNK_SECONDS
    return Segment(start, end - start, f"_twitter_cmp_{time_suffix(start)}_{speed:.1f}x", speed)


def make_twitter_gifs(mp4_path, name, dests, segments):
    print(f"\n  generating {len(segments)} gif{'s' if len(segments) > 1 else ''}...")
    for segment in segments:
        span = f"{fmt_dur(segment.start)}–{fmt_dur(segment.start + segment.seconds)}"
        print(f"  ⌐ {span} → {TWITTER_CHUNK_SECONDS}s @ {segment.speed:.2f}× speed" if segment.speed != 1.0 else f"  ⌐ {span}")
        for d in dests:
            to_gif(mp4_path, d / f"{name}{segment.suffix}.gif", TWITTER_FPS, TWITTER_WIDTH,
                   ss=segment.start, t=segment.seconds, speed=segment.speed)


def make_clip(mp4_path, name, dests, start_time, dur, clip_seconds, clip_gif):
    """A clip from the timestamp, and a twitter-safe gif of its first stretch."""
    clip_dur = min(clip_seconds, dur - start_time)
    if clip_dur <= 0:
        sys.exit(f"the timestamp {fmt_dur(start_time)} is past the end of the video ({fmt_dur(dur)})")
    clip_suffix = f"_clip_{time_suffix(start_time)}"
    print(f"\n── clipping {fmt_dur(start_time)}–{fmt_dur(start_time + clip_dur)}")
    for d in dests:
        clip_path = d / f"{name}{clip_suffix}.mp4"
        to_mp4(mp4_path, clip_path, ss=start_time, t=clip_dur)
        print(f"  ✓ {clip_path}")
    if clip_gif:
        for d in dests:
            gif_path = d / f"{name}{clip_suffix}_twitter.gif"
            to_gif(mp4_path, gif_path, TWITTER_FPS, TWITTER_WIDTH, ss=start_time, t=min(TWITTER_CHUNK_SECONDS, clip_dur))
            print(f"  ✓ {gif_path}")


def do_download(url, tmp_dir, span):
    """The video, or only the span of it, fetched as one mp4; a span is cut on its exact frames."""
    dl = Path(tmp_dir) / "download.mp4"
    section = ("--download-sections", span.section(), "--force-keyframes-at-cuts") if span else ()
    yt_dlp(
        url,
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        *section,
        "-o", str(dl),
        check=True,
    )
    found = next(Path(tmp_dir).glob("*.mp4"), None)
    if not found:
        sys.exit("download failed — no mp4 produced")
    return found


def download(args):
    # A span says exactly what to keep, so the URL's ?t= clip is not cut as well.
    start_time = None if args.time else extract_start_time(args.url)
    url = resolve_url(args.url)
    video = fetch_video(url)
    if args.time:
        check_span(args.time, video)
    name = video.name + (args.time.suffix() if args.time else "")
    cwd = Path.cwd()

    print(f"── downloading {url}")
    print(f"── {name}")
    if args.time:
        print(f"── keeping {args.time.describe()}")
    if start_time is not None:
        print(f"── timestamp: {fmt_dur(start_time)}")

    if args.out:
        dests = [Path(args.out) / name]
        dests[0].mkdir(parents=True, exist_ok=True)
    else:
        dests = resolve_destinations("e" if args.e else "." if args.local else "", name, cwd)

    with tempfile.TemporaryDirectory() as tmp:
        found = do_download(url, tmp, args.time)
        for d in dests:
            mp4 = d / f"{name}.mp4"
            shutil.copy(found, mp4)
            print(f"  ✓ {mp4}")

    primary = dests[0] / f"{name}.mp4"
    dur = report(primary)

    if start_time is not None and not args.no_clip:
        make_clip(primary, name, dests, start_time, dur, args.clip, not args.no_clip_gif)

    if args.twitter:
        make_twitter_gifs(primary, name, dests, twitter_segments(args.twitter, dur, start_time))
    if args.twitter_squeeze:
        make_twitter_gifs(primary, name, dests, [squeezed_segment(args.twitter_squeeze, dur)])

    for d in dests:
        if args.format in ("gif", "all"):
            to_gif(primary, d / f"{name}.gif", args.fps, args.width)
        if args.format in ("webp", "all"):
            to_webp(primary, d / f"{name}.webp", args.fps, args.width)
        if args.clean and args.format != "mp4":
            (d / f"{name}.mp4").unlink(missing_ok=True)

    for d in dests:
        print(f"── outputs in {d}")


def arguments():
    p = argparse.ArgumentParser(
        description="Download a video, then clip and convert it. Nothing is asked: each choice below has a default.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  dlyt URL                     mp4 into the exports folder and the current folder\n"
            "  dlyt URL -.                  current folder only\n"
            "  dlyt URL -g                  a gif of the whole video as well (same as --format gif)\n"
            "  dlyt URL -t 10:20 -g         seconds 10 to 20 only, as an mp4 and a gif\n"
            "  dlyt URL -t 10               second 10 to the end only\n"
            "  dlyt 'URL?t=90'              also a 15 s clip from 1:30, and a twitter-safe gif of it\n"
            "  dlyt 'URL?t=90' --clip 30    that clip 30 s long\n"
            "  dlyt URL --twitter all       twitter-safe gifs of every 15 s chunk\n"
            "  dlyt URL --twitter-squeeze 0:15-1:45   that minute and a half sped up into one 15 s gif\n"
        ),
    )
    p.add_argument("url", help="full URL, YouTube video ID, or =ID; a ?t= in the URL is a timestamp")
    where = p.add_mutually_exclusive_group()
    where.add_argument("-e", action="store_true", help=f"save to {export_dest_for_log()} only (default: there and the current folder)")
    where.add_argument("-.", dest="local", action="store_true", help="save to the current folder only")
    where.add_argument("-o", "--out", help="save to this folder only")
    kind = p.add_mutually_exclusive_group()
    kind.add_argument("--format", choices=["mp4", "gif", "webp", "all"], default="mp4",
                      help="mp4 only, or a gif, a webp or both as well (default: mp4)")
    kind.add_argument("-g", "--gif", dest="format", action="store_const", const="gif", help="same as --format gif")
    p.add_argument("--fps", type=int, default=24, help="frame rate of --format gif and webp (default: 24)")
    p.add_argument("--width", type=int, default=960, help="width of --format gif and webp (default: 960)")
    p.add_argument("-c", "--clean", action="store_true", help="remove the mp4 once --format gif or webp is made")
    p.add_argument("-t", "--time", "--timestamp", type=span_argument, metavar="S[:E]",
                   help="keep only second S to the end, or seconds S to E; every output is made from that stretch "
                        "(replaces the clip at ?t= in the URL)")
    p.add_argument("--clip", type=time_argument, default=CLIP_SECONDS,
                   help=f"length of the clip cut at ?t= in the URL (default: {CLIP_SECONDS} s)")
    p.add_argument("--no-clip", action="store_true", help="cut no clip at ?t= in the URL")
    p.add_argument("--no-clip-gif", action="store_true", help="make no gif of that clip")
    p.add_argument("--twitter", nargs="?", const=TWITTER_FROM_START, type=twitter_argument, metavar="WHICH",
                   help=f"twitter-safe gifs ({TWITTER_CHUNK_SECONDS} s chunks, {TWITTER_WIDTH}px): "
                        f"'{TWITTER_FROM_START}' ({TWITTER_CHUNK_SECONDS} s from the timestamp or the start, the default), "
                        f"'{TWITTER_EVERY_CHUNK}', a chunk N, chunks N-M, a start m:ss, or a range m:ss-m:ss split into chunks")
    p.add_argument("--twitter-squeeze", type=range_argument, metavar="RANGE",
                   help=f"one twitter-safe gif of a range m:ss-m:ss (or m:ss-end) sped up to {TWITTER_CHUNK_SECONDS} s")
    return p.parse_args()


if __name__ == "__main__":
    download(arguments())
