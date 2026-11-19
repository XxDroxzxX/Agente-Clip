"""Utilidades comunes."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path


_SECRET_PATTERNS = [
    (re.compile(r"((?:key|api_key|access_token|token|client_secret|refresh_token)=)[^&\s\"'<>]+", re.I), r"\1***"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "AIza***"),            # claves de Google
    (re.compile(r"sk-ant-[0-9A-Za-z_\-]{10,}"), "sk-ant-***"),       # claves de Anthropic
    (re.compile(r"\bEAA[0-9A-Za-z]{30,}"), "EAA***"),                # tokens de Facebook
    (re.compile(r"(Bearer|OAuth|Key)\s+[0-9A-Za-z._\-]{20,}"), r"\1 ***"),
]


def redact(text: str) -> str:
    """Quita claves y tokens de un texto (mensajes de error, registros): nunca deben quedar escritos en disco."""
    for pat, rep in _SECRET_PATTERNS:
        text = pat.sub(rep, text)
    return text


def atomic_write_text(path: Path, text: str) -> None:
    """Escritura atómica tolerante a lectores concurrentes en Windows."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    for attempt in range(10):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.05 * (attempt + 1))
    return default


def write_json(path: Path, data) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def keep_awake(on: bool = True) -> None:
    """Impide que Windows suspenda el equipo mientras dura un run (la pantalla sí puede apagarse)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def gpu_temperature() -> float | None:
    """Temperatura de la GPU NVIDIA en °C (None si no hay nvidia-smi)."""
    import subprocess
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=0x08000000 if os.name == "nt" else 0).stdout
        return float(out.strip().splitlines()[0])
    except Exception:
        return None


def pid_alive(pid: int, since: float | None = None) -> bool:
    """¿Sigue vivo el proceso? Con `since` (cuándo empezó nuestro proceso) se descarta otro programa que, tras
    reiniciar el PC, recibió el mismo número de proceso: si nació después de `since`, no es el nuestro."""
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            k32.GetExitCodeProcess(h, ctypes.byref(code))
            if code.value != STILL_ACTIVE:
                return False
            if since:
                created, t1, t2, t3 = (ctypes.c_ulonglong() for _ in range(4))
                if k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(t1), ctypes.byref(t2), ctypes.byref(t3)):
                    started = created.value / 1e7 - 11644473600  # FILETIME (desde 1601) → segundos Unix
                    if started > since + 60:
                        return False
            return True
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
