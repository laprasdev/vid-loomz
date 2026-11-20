# vid-loomz

- Standalone video processing, conversion, download, and browser recording utilities
- Kneaded in shape for game engine render sequence automations

## Setup

```bash
python3 src/setup.py
```

Installs: ffmpeg, yt-dlp, playwright + chromium, create-dmg (mac only).

## Usage

### Convert local video
```bash
python3 src/convert.py input.mov --format all
python3 src/convert.py input.mov --format gif --fps 15 --width 720
python3 src/convert.py input.mov -g                 # → ~/Exports/input_<timestamp>/
python3 src/convert.py input.mov -o ~/Desktop/demo   # → ~/Desktop/demo/
```

### Download + convert
Nothing is asked: every choice has a default and a flag, and `--help` lists them all.
```bash
python3 src/download.py https://youtube.com/watch?v=xxx                  # mp4 into the exports folder and the current folder
python3 src/download.py https://youtube.com/watch?v=xxx -.               # current folder only (-e: exports folder only)
python3 src/download.py https://youtube.com/watch?v=xxx -o ./renders     # an explicit folder
python3 src/download.py https://youtube.com/watch?v=xxx --format all     # a gif and a webp as well
python3 src/download.py https://youtube.com/watch?v=xxx -g               # a gif as well (same as --format gif)
python3 src/download.py https://youtube.com/watch?v=xxx -t 10:20 -g      # seconds 10 to 20 only, as an mp4 and a gif
python3 src/download.py https://youtube.com/watch?v=xxx -t 10            # second 10 to the end only
python3 src/download.py "https://youtube.com/watch?v=xxx&t=90"          # also a 15 s clip from 1:30 and a gif of it
python3 src/download.py "https://youtube.com/watch?v=xxx&t=90" --clip 30 --no-clip-gif
python3 src/download.py https://youtube.com/watch?v=xxx --twitter 2-5    # twitter-safe gifs of 15 s chunks 2 to 5
python3 src/download.py https://youtube.com/watch?v=xxx --twitter-squeeze 0:15-1:45
```
Downloads are named after the video's title and id, so no two share a folder or a file; a `-t` span adds itself to the name (`_0m10s-0m20s`, `_0m10s-end`). `-t` (`--time`, `--timestamp`) takes plain seconds, `S` or `S:E`, and fetches only that stretch, cut on its exact frames.

### Record browser session
```bash
python3 src/record.py https://mysite.com
python3 src/record.py https://mysite.com --duration 30 --format gif
python3 src/record.py https://mysite.com -o ./captures
```

### Formats

| flag | output |
|------|--------|
| `--format mp4` | h264 mp4, no audio |
| `--format gif` | palettegen optimised gif |
| `--format webp` | animated webp |
| `--format all` | all three + copy of original |

### Output location

| flag | behavior |
|------|----------|
| *(default)* | next to input file (convert) or `~/Exports/` (download, record) |
| `-g` (convert) | global exports: `~/Exports/<stem>_<timestamp>/`; in download, `-g` is `--format gif` and `-e` is its exports folder |
| `-o path` | explicit directory |
| `VID_LOOMZ_EXPORTS` | env var to override the global exports path |

## Vendoring

Self-contained Python with no relative imports outside `src/`.
Drop the folder into any project as a plain vendor copy.
