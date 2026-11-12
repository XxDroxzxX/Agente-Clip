"""tiktok_refresh.py – Renueva el access_token de TikTok usando el refresh_token.

Uso:
    python scripts/tiktok_refresh.py

El access_token de TikTok expira cada ~2 horas.
El refresh_token dura ~180 dias.
Este script lee el refresh_token de config.yaml, solicita un nuevo access_token
y actualiza config.yaml automaticamente.
"""

import json
import sys
from pathlib import Path

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def main():
    if not CONFIG_PATH.is_file():
        print("[ERROR] config.yaml no encontrado.")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    tk = cfg.get("tiktok", {})
    client_key = tk.get("client_key")
    client_secret = tk.get("client_secret")
    refresh_token = tk.get("refresh_token")

    if not all([client_key, client_secret, refresh_token]):
        print("[ERROR] Faltan client_key, client_secret o refresh_token en config.yaml")
        print("        Ejecuta primero: python scripts/tiktok_auth.py")
        sys.exit(1)

    print("[INFO] Renovando access_token de TikTok...")
    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    payload = {
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(token_url, data=payload, headers=headers)

    if resp.status_code != 200:
        print(f"[ERROR] Fallo con status {resp.status_code}")
        print(resp.text)
        sys.exit(1)

    data = resp.json()
    new_access = data.get("access_token")
    new_refresh = data.get("refresh_token")

    if not new_access:
        print(f"[ERROR] No se obtuvo nuevo access_token: {json.dumps(data, indent=2)}")
        sys.exit(1)

    cfg["tiktok"]["access_token"] = new_access
    if new_refresh:
        cfg["tiktok"]["refresh_token"] = new_refresh

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

    print(f"[INFO] Nuevo access_token: {new_access[:30]}...")
    print(f"[INFO] Guardado en {CONFIG_PATH}")


if __name__ == "__main__":
    main()
