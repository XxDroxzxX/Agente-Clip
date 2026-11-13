"""Wrapper de ffmpeg (usa el del PATH o el incluido en imageio-ffmpeg)."""
from __future__ import annotations

import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Callable

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0


class FFmpegError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args: list, cwd: Path | None = None, duration: float | None = None,
        on_progress: Callable[[float], None] | None = None) -> None:
    """Ejecuta ffmpeg. Si se da duration, reporta progreso 0..1."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
    if on_progress and duration:
        cmd += ["-progress", "pipe:1", "-nostats"]
    cmd += [str(a) for a in args]
    proc = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", creationflags=CREATE_NO_WINDOW)
    if on_progress and duration:
        for line in proc.stdout:
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1])
                    on_progress(min(1.0, us / 1e6 / duration))
                except ValueError:
                    pass
    _, err = proc.communicate()
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg falló ({proc.returncode}): {err.strip()[-1500:]}")


_LUFS_RE = re.compile(r"^\s+I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", re.M)


def measure_lufs(path: Path) -> float | None:
    """Sonoridad integrada (EBU R128) del audio. None si no se pudo medir.
    -70 LUFS es el piso del medidor: silencio o casi silencio."""
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=framelog=quiet",
                           "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=CREATE_NO_WINDOW)
    found = _LUFS_RE.findall(proc.stderr)
    return float(found[-1]) if found else None


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def probe_duration(path: Path) -> float:
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
    m = _DUR_RE.search(proc.stderr)
    if not m:
        raise FFmpegError(f"No se pudo leer la duración de {path.name}")
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def extract_frame(video: Path, out: Path, at: float | None = None, last: bool = False, width: int | None = None):
    args = []
    if last:
        args += ["-sseof", "-0.25"]
    elif at is not None:
        args += ["-ss", f"{at:.2f}"]
    args += ["-i", video]
    vf = []
    if width:
        vf.append(f"scale={width}:-2")
    if vf:
        args += ["-vf", ",".join(vf)]
    args += ["-frames:v", "1", "-q:v", "3", out]
    run(args)
    return out
