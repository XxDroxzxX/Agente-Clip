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


def pid_alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            return code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
