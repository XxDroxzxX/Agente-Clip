"""Cliente mínimo de la API de Gemini (Google AI Studio), plan gratuito.

Usa la API Interactions (POST /v1beta/interactions, Api-Revision 2026-05-20).
El plan gratuito no pide tarjeta, pero tiene pocas solicitudes diarias por modelo:
si un modelo responde 429 (cuota agotada) se prueba el siguiente de la lista.
En el plan gratuito Google puede usar el contenido enviado para mejorar sus productos.
"""
from __future__ import annotations

import copy
from typing import Callable

import requests

from . import settings as S

API = "https://generativelanguage.googleapis.com/v1beta"
REVISION = "2026-05-20"

# Modelos sin costo en el plan gratuito (aistudio.google.com/docs/pricing, nov. 2026), de mejor a más liviano.
FREE_MODELS = ["gemini-4-hydrogen", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
LITE_FIRST = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash", "gemini-4-hydrogen"]


class GeminiError(RuntimeError):
    pass


def api_key() -> str:
    k = S.get_secret("gemini_api_key")
    if not k:
        raise GeminiError("Falta la Gemini API key (Configuración → Credenciales).")
    return k


def chain(first: str | None, base: list[str] = FREE_MODELS) -> list[str]:
    return list(dict.fromkeys([m for m in [first, *base] if m]))


def clean_schema(schema: dict) -> dict:
    """Quita «title» y «default», que no aportan a la salida estructurada."""
    s = copy.deepcopy(schema)

    def walk(o):
        if isinstance(o, dict):
            for k in ("title", "default"):
                if k in o and not isinstance(o[k], dict):
                    o.pop(k)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(s)
    return s


def _error_msg(r: requests.Response) -> str:
    try:
        data = r.json()
    except ValueError:
        return r.text[:200]
    if isinstance(data, list):  # algunos errores llegan como [{"error": {...}}]
        data = data[0] if data and isinstance(data[0], dict) else {}
    err = data.get("error") if isinstance(data, dict) else None
    msg = err.get("message", "") if isinstance(err, dict) else str(err or "")
    return msg or r.text[:200]


def _output_text(data: dict) -> str:
    for step in reversed(data.get("steps") or []):
        if step.get("type") in ("thought", "user_input", "function_call", "function_result"):
            continue
        texts = [c.get("text", "") for c in (step.get("content") or [])
                 if isinstance(c, dict) and c.get("type", "text") == "text" and c.get("text")]
        if texts:
            return "".join(texts)
    if data.get("output_text"):
        return data["output_text"]
    raise GeminiError("Gemini no devolvió texto en la respuesta.")


def generate(models: list[str], input, system: str | None = None, schema: dict | None = None,
             thinking: str | None = None, timeout: int = 600,
             log: Callable[[str], None] | None = None) -> tuple[str, str]:
    """Devuelve (texto, modelo_usado). Recorre `models` mientras haya cuota agotada o modelo no disponible."""
    key = api_key()
    last = ""
    for m in models:
        body: dict = {"model": m, "input": input}
        if system:
            body["system_instruction"] = system
        if schema:
            body["response_format"] = {"type": "text", "mime_type": "application/json", "schema": clean_schema(schema)}
        if thinking:
            body["generation_config"] = {"thinking_level": thinking}
        try:
            r = requests.post(f"{API}/interactions", json=body, timeout=timeout,
                              headers={"x-goog-api-key": key, "Api-Revision": REVISION})
        except requests.ConnectionError:
            raise GeminiError("No hay conexión con la API de Gemini.")
        except requests.Timeout:
            last = f"{m}: tardó demasiado"
            continue
        if r.ok:
            return _output_text(r.json()), m
        msg = _error_msg(r)
        if r.status_code in (401, 403) or "api key not valid" in msg.lower():
            raise GeminiError("La Gemini API key no es válida. Revísala en Configuración → Credenciales.")
        if r.status_code in (404, 429) or r.status_code >= 500:
            last = f"{m}: {'cuota gratuita agotada' if r.status_code == 429 else f'error {r.status_code}'}"
            if log:
                log(f"Gemini {last}; probando otro modelo.")
            continue
        raise GeminiError(f"Gemini rechazó la solicitud ({r.status_code}): {msg[:200]}")
    raise GeminiError("Ningún modelo gratuito de Gemini respondió "
                      f"({last}). La cuota gratuita se renueva cada día; también puedes usar Claude u Ollama.")


def list_models() -> list[str]:
    """Valida la clave sin gastar cuota: lista los modelos disponibles para la cuenta."""
    r = requests.get(f"{API}/models", params={"pageSize": 200}, headers={"x-goog-api-key": api_key()}, timeout=20)
    if not r.ok:
        msg = _error_msg(r)
        if r.status_code in (400, 401, 403):
            raise GeminiError("La Gemini API key no es válida." if "key" in msg.lower() else f"Gemini: {msg[:200]}")
        raise GeminiError(f"Gemini respondió con error {r.status_code}.")
    return [m.get("name", "").removeprefix("models/") for m in r.json().get("models", [])]
