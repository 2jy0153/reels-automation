"""분석·편집용 저용량 사본(720p)을 만든다. 원본은 건드리지 않는다.

LIBRARY/VIDEO/YYYYMMDD/이름.mp4 → PROXY/VIDEO/YYYYMMDD/이름.mp4
"""

import os
import shutil
import subprocess
from pathlib import Path


def proxy_path(library_file: Path, library_root: Path, proxy_root: Path) -> Path:
    return proxy_root / library_file.relative_to(library_root)


def ffmpeg_command(src: Path, dst: Path, height: int) -> list[str]:
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(src),
        "-vf", f"scale=-2:{height}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        str(dst),
    ]


def make_proxy(src: Path, dst: Path, height: int) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg가 설치되어 있지 않습니다.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp = dst.parent / f".{dst.name}.partial.mp4"
    try:
        subprocess.run(ffmpeg_command(src, temp, height), check=True)
        if temp.stat().st_size == 0:
            raise OSError(f"사본이 비어 있습니다: {dst.name}")
        os.replace(temp, dst)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
