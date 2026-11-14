#!/usr/bin/env python3
"""
vid-loomz setup — run once per machine.
  python3 src/setup.py
"""

import subprocess
import sys
import platform
import shutil
import sysconfig
from pathlib import Path

OS = platform.system()


def run(cmd, check=True):
    print(f"  → {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=check)


def check(binary):
    found = shutil.which(binary) is not None
    print(f"  {'✓' if found else '✗'}  {binary}")
    return found


def user_bin() -> Path:
    return Path(sysconfig.get_path("scripts", scheme="posix_user"))


def install_ffmpeg():
    print("\n── ffmpeg")
    if check("ffmpeg"):
        return
    if OS == "Darwin":   run(["brew", "install", "ffmpeg"])
    elif OS == "Linux":  run(["sudo", "apt-get", "install", "-y", "ffmpeg"])
    elif OS == "Windows": run(["choco", "install", "ffmpeg", "-y"])


def install_ytdlp():
    print("\n── yt-dlp")
    if check("yt-dlp"):
        return
    if OS == "Darwin":   run(["brew", "install", "yt-dlp"])
    else:                run([sys.executable, "-m", "pip", "install", "yt-dlp"])


def install_create_dmg():
    if OS != "Darwin":
        return
    print("\n── create-dmg")
    if check("create-dmg"):
        return
    run(["brew", "install", "create-dmg"])


def install_playwright():
    print("\n── playwright")
    run([sys.executable, "-m", "pip", "install", "playwright"])
    pw = user_bin() / "playwright"
    cmd = str(pw) if (OS == "Darwin" and pw.exists()) else "playwright"
    print("\n── chromium")
    run([cmd, "install", "chromium"])


def path_hint():
    ub = user_bin()
    if OS == "Darwin" and str(ub) not in (shutil.which("playwright") or ""):
        print(f"\n⚠️  Add to PATH in ~/.zprofile if not present:")
        print(f'   export PATH="$PATH:{ub}"')


if __name__ == "__main__":
    print(f"vid-loomz setup ({OS})\n")
    install_ffmpeg()
    install_ytdlp()
    install_create_dmg()
    install_playwright()
    path_hint()
    print("\n── done.")
