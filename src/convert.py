#!/usr/bin/env python3
"""
Convert any local video to mp4 / gif / webp / all.
  python3 src/convert.py input.mov --format all
  python3 src/convert.py input.mov --format gif --fps 15 --width 720
  python3 src/convert.py input.mov -g
  python3 src/convert.py input.mov -o ~/Desktop/renders
"""

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

GLOBAL_EXPORTS = Path(os.environ.get("VID_LOOMZ_EXPORTS", Path.home() / "media" / "tmp" / "vids" / "yt"))


def outdir(source: Path, global_export=False, out=None):
    if out:
        d = Path(out)
        d.mkdir(parents=True, exist_ok=True)
        return d
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{source.stem}_{ts}"
    base = GLOBAL_EXPORTS if global_export else source.parent
    d = base / stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def ff(*args, check=True):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", *[str(a) for a in args]]
    print(f"  → {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0 and check:
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result.returncode == 0


def to_mp4(src, out, ss=None, t=None):
    inp = []
    if ss is not None:
        inp += ["-ss", str(ss)]
    if t is not None:
        inp += ["-t", str(t)]
    ff(*inp, "-i", src, "-c:v", "libx264", "-crf", "23", "-preset", "medium", "-an", out, "-y")


def to_gif(src, out, fps=24, width=960, ss=None, t=None, speed=1.0):
    palette = out.parent / "_palette.png"
    inp = []
    if ss is not None:
        inp += ["-ss", str(ss)]
    if t is not None:
        inp += ["-t", str(t)]
    pre = f"setpts=PTS/{speed}," if speed and speed != 1.0 else ""
    vf = f"{pre}fps={fps},scale={width}:-1:flags=lanczos"
    ff(*inp, "-i", src, "-vf", f"{vf},palettegen", palette, "-y")
    ff(*inp, "-i", src, "-i", palette,
       "-filter_complex", f"{vf}[x];[x][1:v]paletteuse",
       "-an", out, "-y")
    palette.unlink(missing_ok=True)


def to_webp(src, out, fps=24, width=960, ss=None, t=None):
    inp = []
    if ss is not None:
        inp += ["-ss", str(ss)]
    if t is not None:
        inp += ["-t", str(t)]
    ok = ff(*inp, "-i", src,
            "-c:v", "libwebp", "-lossless", "0", "-compression_level", "4",
            "-q:v", "75", "-loop", "0", "-an",
            "-vf", f"fps={fps},scale={width}:-1:flags=lanczos",
            out, "-y", check=False)
    if not ok:
        print(f"  ⚠ webp failed — video may be too long for animated webp")


def convert(src: Path, fmt: str, fps=24, width=960, out=None, global_export=False):
    d = outdir(src, global_export, out)
    if fmt in ("mp4", "all"):
        to_mp4(src, d / "output.mp4")
        print(f"  ✓ {d / 'output.mp4'}")
    if fmt in ("gif", "all"):
        to_gif(src, d / "output.gif", fps, width)
        print(f"  ✓ {d / 'output.gif'}")
    if fmt in ("webp", "all"):
        to_webp(src, d / "output.webp", fps, width)
        print(f"  ✓ {d / 'output.webp'}")
    if fmt == "all":
        shutil.copy(src, d / ("original" + src.suffix))
    print(f"\n── outputs in {d}")
    return d


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("input", help="input video file")
    p.add_argument("--format", choices=["mp4", "gif", "webp", "all"], default="all")
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--width", type=int, default=960)
    p.add_argument("-o", "--out", help="output directory")
    p.add_argument("-g", "--global", dest="global_export", action="store_true",
                   help="save to global exports folder (~/ Exports or VID_LOOMZ_EXPORTS)")
    args = p.parse_args()
    convert(Path(args.input), args.format, args.fps, args.width, args.out, args.global_export)
