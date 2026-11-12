"""tiktok_auth.py – Script para obtener el Access Token de TikTok.

Este script levanta un servidor local en http://localhost:8585/callback,
abre el navegador para que autorices tu app de TikTok y luego intercambia
el authorization code por un access_token + refresh_token.

Uso:
    python scripts/tiktok_auth.py

Pre-requisitos:
    1. Ve a https://developers.tiktok.com → Tu app → Settings
    2. En "Redirect URI" agrega exactamente:  http://localhost:8585/callback
    3. En "Products" activa:
         - Login Kit
         - Content Posting API (para subir videos)
    4. Guarda los cambios en TikTok Developers.
"""

import http.server
import json
import os
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# ──────────────────────────────────────────────
# 1. Leer client_key y client_secret del config
# ──────────────────────────────────────────────
def load_tiktok_config():
    if not CONFIG_PATH.is_file():
        print("[ERROR] config.yaml no encontrado.")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    tk = cfg.get("tiktok", {})
    client_key = tk.get("client_key")
    client_secret = tk.get("client_secret")
    if not client_key or not client_secret:
        print("[ERROR] Falta client_key o client_secret en config.yaml -> tiktok")
        sys.exit(1)
    return client_key, client_secret


# ──────────────────────────────────────────────
# 2. Servidor local para capturar el callback
# ──────────────────────────────────────────────
REDIRECT_PORT = 8585
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
auth_code_holder = {"code": None}


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Servidor HTTP mínimo que escucha el redirect de TikTok."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            auth_code_holder["code"] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Autorizado correctamente. Puedes cerrar esta ventana.</h2></body></html>"
            )
        elif "error" in params:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = params.get("error_description", ["Error desconocido"])[0]
            self.wfile.write(f"<html><body><h2>Error: {msg}</h2></body></html>".encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass  # Silenciar logs del servidor


# ──────────────────────────────────────────────
# 3. Flujo principal
# ──────────────────────────────────────────────
def main():
    client_key, client_secret = load_tiktok_config()

    # Scopes necesarios para subir y publicar videos
    scopes = "user.info.basic,video.upload,video.publish"

    # URL de autorización
    auth_url = (
        f"https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={client_key}"
        f"&response_type=code"
        f"&scope={scopes}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
    )

    # Levantar servidor local en segundo plano
    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print("=" * 60)
    print("PASO 1: Se abrira tu navegador para autorizar la app de TikTok.")
    print("        Si no se abre automaticamente, copia esta URL:")
    print()
    print(f"  {auth_url}")
    print()
    print("=" * 60)

    webbrowser.open(auth_url)

    # Esperar a que el callback llegue
    thread.join(timeout=120)
    server.server_close()

    if not auth_code_holder["code"]:
        print("[ERROR] No se recibio el authorization code. Tiempo agotado o hubo un error.")
        sys.exit(1)

    code = auth_code_holder["code"]
    print(f"\n[INFO] Authorization code recibido: {code[:20]}...")

    # ──────────────────────────────────────────
    # PASO 2: Intercambiar code → access_token
    # ──────────────────────────────────────────
    print("[INFO] Intercambiando code por access_token...")
    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    payload = {
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(token_url, data=payload, headers=headers)

    if resp.status_code != 200:
        print(f"[ERROR] La solicitud fallo con status {resp.status_code}")
        print(resp.text)
        sys.exit(1)

    data = resp.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in")
    open_id = data.get("open_id")

    if not access_token:
        print(f"[ERROR] No se obtuvo access_token. Respuesta: {json.dumps(data, indent=2)}")
        sys.exit(1)

    print()
    print("=" * 60)
    print("EXITO! Tokens obtenidos:")
    print(f"  access_token:  {access_token[:30]}...")
    print(f"  refresh_token: {refresh_token[:30]}..." if refresh_token else "  refresh_token: (no disponible)")
    print(f"  expires_in:    {expires_in} segundos")
    print(f"  open_id:       {open_id}")
    print("=" * 60)

    # ──────────────────────────────────────────
    # PASO 3: Guardar en config.yaml
    # ──────────────────────────────────────────
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    cfg["tiktok"]["access_token"] = access_token
    if refresh_token:
        cfg["tiktok"]["refresh_token"] = refresh_token

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

    print(f"\n[INFO] access_token y refresh_token guardados en {CONFIG_PATH}")
    print("[INFO] El access_token expira en ~2 horas. Usa el refresh_token para renovarlo.")
    print("[INFO] Listo! Ahora puedes ejecutar el pipeline con ./run_day.ps1")


if __name__ == "__main__":
    main()
