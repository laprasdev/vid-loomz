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
```bash
python3 src/download.py https://youtube.com/watch?v=xxx --format all
python3 src/download.py https://youtube.com/watch?v=xxx --format gif
python3 src/download.py https://youtube.com/watch?v=xxx -o ./renders
```

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
| `-g` | global exports: `~/Exports/<stem>_<timestamp>/` |
| `-o path` | explicit directory |
| `VID_LOOMZ_EXPORTS` | env var to override the global exports path |

## Vendoring

Self-contained Python with no relative imports outside `src/`.
Drop the folder into any project as a plain vendor copy.
