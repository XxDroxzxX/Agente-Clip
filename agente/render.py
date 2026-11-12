"""Montaje final con ffmpeg: tomas → video, subtítulos animados, voz y música."""
from __future__ import annotations

import os
import random
import shutil
from pathlib import Path
from typing import Callable

from . import ffmpeg
from .paths import MUSIC_DIR
from .tts import Word
from .visuals import Shot

FPS = 30

RESOLUTIONS = {
    ("1080p", False): (1920, 1080), ("1080p", True): (1080, 1920),
    ("720p", False): (1280, 720), ("720p", True): (720, 1280),
}

_FONT_CANDIDATES = [
    ("seguibl.ttf", "Segoe UI Black"),
    ("arialbd.ttf", "Arial"),
]


def _even(x: float) -> int:
    return int(x) // 2 * 2


def normalize_shot(shot: Shot, W: int, H: int, out: Path) -> None:
    d = f"{shot.duration:.3f}"
    enc = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-r", FPS]
    fit = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS}"
    if shot.kind == "video" and shot.source:
        args = ["-stream_loop", "-1", "-i", shot.source, "-t", d, "-vf", fit + ",format=yuv420p", *enc, out]
    elif shot.kind == "image" and shot.source:
        frames = max(1, round(shot.duration * FPS))
        bw, bh = _even(W * 1.2), _even(H * 1.2)
        direction = random.choice(["in", "out"])
        z = "min(1+0.12*on/{n},1.12)" if direction == "in" else "max(1.12-0.12*on/{n},1)"
        vf = (f"scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
              f"zoompan=z='{z.format(n=frames)}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":s={W}x{H}:fps={FPS},setsar=1,format=yuv420p")
        args = ["-loop", "1", "-i", shot.source, "-t", d, "-vf", vf, *enc, out]
    else:
        color = random.choice(["0x14213d", "0x1b4332", "0x3c096c", "0x5f0f40", "0x003049"])
        args = ["-f", "lavfi", "-i", f"color=c={color}:s={W}x{H}:r={FPS}:d={d}",
                "-vf", "vignette=PI/4,format=yuv420p", *enc, out]
    if shot.overlay and Path(shot.overlay).exists():
        args = _with_overlay(args, Path(shot.overlay), W, H)
    ffmpeg.run(args)


def _with_overlay(args: list, overlay: Path, W: int, H: int) -> list:
    """Convierte «-i base … -vf X … out» en un filter_complex que superpone la capa animada."""
    a = list(args)
    vi = a.index("-vf")
    vf = a[vi:vi + 2][1]
    a[vi:vi + 2] = [
        "-filter_complex",
        f"[0:v]{vf}[b];[1:v]scale={W}:{H},fps={FPS},setpts=PTS-STARTPTS[o];"
        "[b][o]overlay=0:0:eof_action=pass:format=auto,format=yuv420p[v]",
        "-map", "[v]",
    ]
    # la capa entra justo después de la primera entrada, antes de «-t» (que es opción de salida)
    i = a.index("-i") + 2
    a[i:i] = ["-i", overlay]
    return a


# ── subtítulos ASS ────────────────────────────────────

def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")")


def write_ass(words_by_scene: list[list[Word]], offsets: list[float], W: int, H: int,
              portrait: bool, font_name: str, out: Path) -> None:
    size = round(H * (0.055 if portrait else 0.059))
    outline = max(3, round(size * 0.07))
    margin_v = round(H * (0.27 if portrait else 0.065))
    max_words = 3 if portrait else 5
    # &HAABBGGRR — principal (ya dicho): amarillo cálido; secundario (por decir): blanco
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{font_name},{size},&H0033D6FF,&H00FFFFFF,&H00101010,&H96000000,-1,0,0,0,100,100,1,0,1,{outline},2,2,{round(W*0.06)},{round(W*0.06)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for words, off in zip(words_by_scene, offsets):
        chunk: list[Word] = []
        chunks: list[list[Word]] = []
        for w in words:
            if chunk and (len(chunk) >= max_words or w.start - chunk[-1].end > 0.35):
                chunks.append(chunk)
                chunk = []
            chunk.append(w)
        if chunk:
            chunks.append(chunk)
        for ci, ch in enumerate(chunks):
            start = off + ch[0].start
            nxt = off + chunks[ci + 1][0].start if ci + 1 < len(chunks) else off + ch[-1].end + 0.35
            end = max(nxt, start + 0.3)
            parts = []
            for wi, w in enumerate(ch):
                w_end = ch[wi + 1].start if wi + 1 < len(ch) else w.end
                cs = max(1, round((w_end - w.start) * 100))
                text = _esc(w.text.upper() if portrait else w.text)
                parts.append(f"{{\\k{cs}}}{text}")
            pop = r"{\fscx92\fscy92\t(0,90,\fscx100\fscy100)}"
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Main,,0,0,0,,{pop}{' '.join(parts)}")
    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8-sig")


def prepare_font(dest_dir: Path) -> str:
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for file, family in _FONT_CANDIDATES:
        src = fonts / file
        if src.is_file():
            shutil.copy2(src, dest_dir / file)
            return family
    return "Arial"


def pick_music() -> Path | None:
    files = [p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg")]
    return random.choice(files) if files else None


def assemble(item_dir: Path, shot_files: list[Path], narration: Path, total: float, subs: Path | None,
             music: Path | None, music_volume: float, out: Path, on_progress: Callable[[float], None]) -> None:
    lst = item_dir / "shots.txt"
    lst.write_text("".join(f"file '{p.relative_to(item_dir).as_posix()}'\n" for p in shot_files), encoding="utf-8")
    silent = item_dir / "silent.mp4"
    ffmpeg.run(["-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", silent.name], cwd=item_dir)

    args = ["-i", silent.name, "-i", narration.name]
    vf = "[0:v]tpad=stop_mode=clone:stop_duration=3"
    if subs is not None:
        vf += f",subtitles={subs.name}:fontsdir=fonts"
    vf += "[v]"
    if music is not None:
        args += ["-stream_loop", "-1", "-i", str(music)]
        af = (f"[2:a]volume={music_volume:.3f},aresample=48000[m];"
              f"[1:a]aresample=48000,asplit=2[n1][n2];"
              f"[m][n1]sidechaincompress=threshold=0.04:ratio=6:attack=15:release=350[duck];"
              f"[n2][duck]amix=inputs=2:duration=first:normalize=0,"
              f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    else:
        af = "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
    args += ["-filter_complex", f"{vf};{af}", "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", FPS,
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out.name]
    ffmpeg.run(args, cwd=item_dir, duration=total, on_progress=on_progress)
    silent.unlink(missing_ok=True)
