#!/usr/bin/env python3
"""
Meld (concatenate) and trim GIFs.
  gifmeld a.gif b.gif                        # concat
  gifmeld a.gif b.gif -end 5s               # concat, trim 5s off end
  gifmeld a.gif b.gif -begin 5s             # concat, trim 5s off start
  gifmeld a.gif -end 5s                     # just trim a single gif
  gifmeld a.gif b.gif -begin 10f -end 20f   # trim by frames (f) or seconds (s)
  gifmeld a.gif b.gif -o out.gif            # explicit output path
  gifmeld a.gif b.gif --target 15s          # concat then time-compress to 15s
  gifmeld a.gif --target 15s                # speed up single gif to fit 15s
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from convert import ff


def probe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0


def probe_fps(path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True
    )
    try:
        num, den = r.stdout.strip().split("/")
        return int(num) / int(den)
    except (ValueError, ZeroDivisionError):
        return 15


def parse_trim(val):
    """Parse a trim value like '5s' or '20f'. Returns (amount, unit)."""
    val = val.strip().lstrip("-")
    if val.endswith("f"):
        return int(val[:-1]), "f"
    if val.endswith("s"):
        return float(val[:-1]), "s"
    return float(val), "s"


def trim_to_secs(amount, unit, fps):
    if unit == "f":
        return amount / fps
    return amount


def default_output(inputs):
    first = inputs[0]
    stem = first.stem
    if len(inputs) > 1:
        stem += "_melded"
    else:
        stem += "_trimmed"
    return first.parent / f"{stem}.gif"


def meld(inputs, begin=None, end=None, output=None, target=None):
    for f in inputs:
        if not f.exists():
            print(f"  ⚠ not found: {f}")
            sys.exit(1)

    out = Path(output) if output else default_output(inputs)

    # get fps from first input for frame-based trim math
    fps = probe_fps(inputs[0])

    # calculate total duration of all inputs
    durations = [probe_duration(p) for p in inputs]
    total_dur = sum(durations)
    print(f"  inputs: {len(inputs)} gif{'s' if len(inputs) > 1 else ''}, total {total_dur:.1f}s @ {fps:.0f}fps")

    # resolve trim values to seconds
    ss = 0
    if begin:
        amount, unit = parse_trim(begin)
        ss = trim_to_secs(amount, unit, fps)

    out_dur = total_dur - ss
    if end:
        amount, unit = parse_trim(end)
        out_dur -= trim_to_secs(amount, unit, fps)

    if out_dur <= 0:
        print(f"  ⚠ nothing left after trimming ({total_dur:.1f}s - {total_dur - out_dur:.1f}s trimmed)")
        sys.exit(1)

    speed = 1.0
    if target:
        amount, unit = parse_trim(target)
        target_secs = trim_to_secs(amount, unit, fps)
        if target_secs <= 0:
            print(f"  ⚠ target must be > 0")
            sys.exit(1)
        if target_secs >= out_dur:
            print(f"  ⚠ target {target_secs:.1f}s ≥ source {out_dur:.1f}s — no compression needed")
            sys.exit(1)
        speed = out_dur / target_secs
        print(f"  target: {target_secs:.1f}s → {speed:.2f}× speedup")

    print(f"  output: {out_dur / speed:.1f}s (trim begin={ss:.1f}s, end={total_dur - ss - out_dur:.1f}s)")

    pre = f"setpts=PTS/{speed}," if speed != 1.0 else ""
    vf = f"{pre}fps={fps},scale=-1:-1:flags=lanczos"

    if len(inputs) == 1:
        # single file — just trim (and optionally compress)
        palette = out.parent / "_palette.png"
        inp = []
        if ss > 0:
            inp += ["-ss", str(ss)]
        inp += ["-t", str(out_dur)]
        ff(*inp, "-i", inputs[0], "-vf", f"{vf},palettegen", palette, "-y")
        ff(*inp, "-i", inputs[0], "-i", palette,
           "-filter_complex", f"{vf}[x];[x][1:v]paletteuse",
           "-an", out, "-y")
        palette.unlink(missing_ok=True)
    else:
        # multiple files — concat then trim (and optionally compress)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            for p in inputs:
                f.write(f"file '{p.resolve()}'\n")
            concat_list = f.name

        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as tmp:
            tmp_path = tmp.name

        ff("-f", "concat", "-safe", "0", "-i", concat_list, "-y", tmp_path)

        palette = out.parent / "_palette.png"
        inp = []
        if ss > 0:
            inp += ["-ss", str(ss)]
        inp += ["-t", str(out_dur)]
        ff(*inp, "-i", tmp_path, "-vf", f"{vf},palettegen", palette, "-y")
        ff(*inp, "-i", tmp_path, "-i", palette,
           "-filter_complex", f"{vf}[x];[x][1:v]paletteuse",
           "-an", out, "-y")
        palette.unlink(missing_ok=True)
        Path(concat_list).unlink(missing_ok=True)
        Path(tmp_path).unlink(missing_ok=True)

    print(f"  ✓ {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Meld (concat) and trim GIFs")
    p.add_argument("inputs", nargs="+", help="input GIF files")
    p.add_argument("-begin", help="trim from start (e.g. 5s, 20f)")
    p.add_argument("-end", help="trim from end (e.g. 5s, 20f)")
    p.add_argument("-o", "--output", help="output file path")
    p.add_argument("--target", help="time-compress to target duration (e.g. 15s)")
    args = p.parse_args()

    meld([Path(i) for i in args.inputs], args.begin, args.end, args.output, args.target)
