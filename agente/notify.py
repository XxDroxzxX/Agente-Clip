"""Notificación de Windows (toast) al terminar un run. Sin dependencias: usa PowerShell + WinRT."""
from __future__ import annotations

import os
import subprocess
from xml.sax.saxutils import escape

APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($env:AGENTE_TOAST_XML)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:AGENTE_TOAST_APP).Show($toast)
"""


def toast(title: str, body: str) -> bool:
    if os.name != "nt":
        return False
    xml = (f"<toast><visual><binding template='ToastGeneric'><text>{escape(title[:120])}</text>"
           f"<text>{escape(body[:250])}</text></binding></visual></toast>")
    env = {**os.environ, "AGENTE_TOAST_XML": xml, "AGENTE_TOAST_APP": APP_ID}
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS], env=env, timeout=20,
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False


def run_finished(state: dict) -> None:
    title = state.get("title") or "Run"
    status = state.get("status")
    items = state.get("items", {})
    if status == "done":
        n = sum(1 for k in items if items[k].get("duration"))
        blocked = [k for k, v in items.items() if (v.get("review") or {}).get("ok") is False]
        ups = [u for u in state.get("uploads", []) if u.get("platform_id")]
        body = f"{n} videos listos" + (f", {len(ups)} publicados" if ups else "")
        if blocked:
            body += f". Revisa: {', '.join(blocked)} (la IA encontró problemas)"
        toast("Agente de Clips: listo ✔", f"{title} — {body}.")
    elif status == "failed":
        toast("Agente de Clips: falló", f"{title} — {(state.get('error') or '')[:150]} Abre la app y pulsa «Reintentar».")
