"""Publicación por navegador (YouTube Studio y TikTok Studio).

Alternativa a las API oficiales, que sin auditoría dejan los videos en privado. Se usa el Chrome instalado con un
perfil propio en data/navegador/<plataforma>: el usuario inicia sesión una vez en una ventana visible y las
subidas siguientes reutilizan esa sesión (Chrome guarda las cookies cifradas con el usuario de Windows).

Técnica y selectores basados en social-auto-upload (MIT, github.com/dreammis/social-auto-upload), adaptados:
perfil persistente en lugar de cookies exportadas, selectores por atributos (sirven con la interfaz en español)
y una comprobación final de privacidad antes de publicar.

Uso por consola:  python -m agente.publish.browser login youtube|tiktok
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from ..paths import DATA_DIR

ROOT = DATA_DIR / "navegador"
PLATFORMS = ("youtube", "tiktok")
LOGIN_URL = {"youtube": "https://studio.youtube.com", "tiktok": "https://www.tiktok.com/login?lang=es"}
SESSION_COOKIE = {"youtube": ("SAPISID", "youtube.com"), "tiktok": ("sessionid", "tiktok.com")}
NAME = {"youtube": "YouTube", "tiktok": "TikTok"}


class BrowserError(RuntimeError):
    pass


def profile_dir(platform: str) -> Path:
    return ROOT / platform


def _status_file(platform: str) -> Path:
    return ROOT / f"{platform}.json"


def status(platform: str) -> dict:
    """Estado guardado por el último inicio de sesión o subida (no abre el navegador)."""
    try:
        return json.loads(_status_file(platform).read_text(encoding="utf-8"))
    except Exception:
        return {"connected": False}


def _save_status(platform: str, **data) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    _status_file(platform).write_text(json.dumps({**status(platform), **data, "updated": time.time()}), encoding="utf-8")


def disconnect(platform: str) -> None:
    shutil.rmtree(profile_dir(platform), ignore_errors=True)
    _status_file(platform).unlink(missing_ok=True)


@contextmanager
def _browser(platform: str, visible: bool):
    """Chrome real con el perfil de la plataforma. Sin ventana visible se abre fuera de la pantalla: el modo
    «headless» es fácil de detectar y TikTok lo bloquea."""
    try:
        from patchright.sync_api import sync_playwright
    except ImportError:
        raise BrowserError("Falta el componente de navegador. Ejecuta: venv\\Scripts\\pip install patchright")
    profile_dir(platform).mkdir(parents=True, exist_ok=True)
    args = ["--window-size=1280,900"] + ([] if visible else ["--window-position=-2400,-2400"])
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(str(profile_dir(platform)), channel="chrome", headless=False,
                                                       no_viewport=True, args=args)
        except Exception as e:
            text = str(e)
            if "ProcessSingleton" in text or "already in use" in text or "lock" in text.lower():
                raise BrowserError(f"El navegador de {NAME[platform]} ya está abierto (¿un inicio de sesión en curso?). "
                                   "Ciérralo y vuelve a intentar.")
            if "chrome" in text.lower() and ("not found" in text.lower() or "executable" in text.lower()):
                raise BrowserError("No se encontró Google Chrome. Instálalo desde google.com/chrome.")
            raise
        try:
            yield ctx
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def _logged_in(ctx, platform: str) -> bool:
    name, domain = SESSION_COOKIE[platform]
    return any(c["name"] == name and domain in c["domain"] and c["value"] for c in ctx.cookies())


def login(platform: str, timeout_s: int = 600) -> bool:
    """Abre una ventana visible para que el usuario inicie sesión; termina sola al detectar la sesión."""
    _save_status(platform, connected=False, pending=True, error=None)
    try:
        with _browser(platform, visible=True) as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(LOGIN_URL[platform], wait_until="domcontentloaded")
            t0 = time.time()
            while time.time() - t0 < timeout_s:
                if _logged_in(ctx, platform) and (platform != "youtube" or "studio.youtube.com" in page.url):
                    page.wait_for_timeout(3000)  # deja que terminen de guardarse las cookies
                    _save_status(platform, connected=True, pending=False, error=None)
                    return True
                if page.is_closed():
                    break
                page.wait_for_timeout(1500)
        _save_status(platform, connected=False, pending=False, error="No se completó el inicio de sesión.")
        return False
    except Exception as e:
        _save_status(platform, connected=False, pending=False, error=str(e)[:300])
        raise


# ── utilidades de página ───────────────────────────────

def _shot(page, platform: str) -> str:
    """Captura de pantalla para diagnosticar un fallo; devuelve la ruta (o '')."""
    try:
        d = ROOT / "errores"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{platform}-{time.strftime('%Y%m%d-%H%M%S')}.png"
        page.screenshot(path=str(f), full_page=True)
        return str(f)
    except Exception:
        return ""


def _fail(page, platform: str, msg: str):
    f = _shot(page, platform)
    raise BrowserError(msg + (f" Captura de la pantalla: {f}" if f else ""))


def _click(page, selector: str, timeout: int = 5000) -> bool:
    try:
        el = page.locator(selector).first
        el.wait_for(state="visible", timeout=timeout)
        el.click()
        return True
    except Exception:
        return False


def _visible(page, selector: str) -> bool:
    try:
        loc = page.locator(selector)
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def _session_expired(page, platform: str) -> bool:
    url = page.url.lower()
    return ("accounts.google.com" in url or "signin" in url) if platform == "youtube" else "/login" in url


# ── YouTube Studio ─────────────────────────────────────

YT_VISIBILITY = {"public": "PUBLIC", "unlisted": "UNLISTED", "private": "PRIVATE"}
_UPLOADING = re.compile(r"(?i)(upload|subiendo|cargando|carga)")
_PERCENT = re.compile(r"(\d{1,3})\s?%")


def _yt_fill(page, selector: str, text: str) -> None:
    """Cuadros de texto enriquecido de Studio: se reemplaza todo de una vez (escribir letra por letra abre el
    autocompletado de # que tapa los botones)."""
    box = page.locator(selector).first
    box.wait_for(state="visible", timeout=30000)
    box.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    try:
        box.fill(text)
    except Exception:
        box.type(text, delay=5)
    page.wait_for_timeout(400)
    page.evaluate("() => document.activeElement && document.activeElement.blur && document.activeElement.blur()")
    if _visible(page, "tp-yt-iron-dropdown:visible"):
        page.keyboard.press("Escape")


def _yt_wait_upload(page, on_progress: Callable[[float], None], limit_s: int = 3600) -> None:
    """Espera a que el archivo termine de subir: si se publica y se cierra el navegador antes, la subida se corta."""
    t0 = time.time()
    while time.time() - t0 < limit_s:
        txt = ""
        for sel in ("ytcp-video-upload-progress .progress-label", ".progress-label", "ytcp-video-upload-progress"):
            try:
                loc = page.locator(sel).first
                if loc.count():
                    txt = (loc.inner_text() or "").strip()
                    if txt:
                        break
            except Exception:
                pass
        m = _PERCENT.search(txt)
        if txt and not (_UPLOADING.search(txt) and m and int(m.group(1)) < 100):
            on_progress(0.9)
            return
        if m:
            on_progress(0.1 + 0.8 * int(m.group(1)) / 100)
        page.wait_for_timeout(3000)
    raise BrowserError("La subida a YouTube no terminó en una hora.")


def upload_youtube(video: Path, title: str, description: str, tags: list[str], privacy: str, is_short: bool,
                   on_progress: Callable[[float], None], thumbnail: Path | None = None, visible: bool = False) -> dict:
    if privacy not in YT_VISIBILITY:
        privacy = "private"
    if is_short and "#shorts" not in title.lower():
        title = f"{title[:90]} #Shorts"
    notes = []
    with _browser("youtube", visible=visible) as ctx:
        if not _logged_in(ctx, "youtube"):
            _save_status("youtube", connected=False)
            raise BrowserError("YouTube no tiene sesión iniciada. Ve a Configuración → Conexiones y pulsa "
                               "«Iniciar sesión en YouTube».")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(60000)
        page.goto("https://www.youtube.com/upload", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        if _session_expired(page, "youtube"):
            _save_status("youtube", connected=False)
            raise BrowserError("La sesión de YouTube venció. Vuelve a iniciar sesión en Configuración → Conexiones.")
        try:
            page.locator('input[type="file"]').first.set_input_files(str(video))
            page.locator("#title-textarea").wait_for(state="visible", timeout=120000)
        except Exception:
            _fail(page, "youtube", "YouTube Studio no abrió el formulario de subida (¿límite diario de subidas o "
                                   "canal sin verificar?).")
        on_progress(0.1)
        _yt_fill(page, "#title-textarea #textbox", title[:100])
        if description.strip():
            _yt_fill(page, "#description-textarea #textbox", description[:4900])
        if thumbnail and Path(thumbnail).is_file() and not is_short:
            try:
                page.locator("ytcp-thumbnail-uploader input[type='file'], #file-loader input[type='file']").first \
                    .set_input_files(str(thumbnail))
                page.wait_for_timeout(2000)
            except Exception:
                notes.append("La miniatura no se aplicó (YouTube exige verificar el canal con tu teléfono).")
        if not _click(page, "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']", 15000):
            _fail(page, "youtube", "No se encontró la opción «No es contenido para niños» en YouTube Studio.")
        if tags:
            try:
                _click(page, "#toggle-button", 5000)
                page.wait_for_timeout(800)
                box = page.locator("#tags-container #text-input, ytcp-form-input-container#tags-container input").first
                box.click()
                box.type(",".join(t.lstrip("#") for t in tags)[:450] + ",", delay=4)
            except Exception:
                notes.append("Las etiquetas no se pudieron cargar (no afecta la publicación).")
        # «Siguiente» hasta llegar a Visibilidad
        target = f"tp-yt-paper-radio-button[name='{YT_VISIBILITY[privacy]}']"
        for _ in range(6):
            if _visible(page, target):
                break
            _click(page, "#next-button", 6000)
            page.wait_for_timeout(1200)
        if not _click(page, target, 10000):
            _fail(page, "youtube", "No se encontró la sección de visibilidad en YouTube Studio.")
        page.wait_for_timeout(600)
        checked = page.locator(target).first.get_attribute("aria-checked")
        if checked not in ("true", None):
            _fail(page, "youtube", f"No se pudo marcar la visibilidad «{privacy}»; no se publicó por seguridad.")
        url = ""
        try:
            link = page.locator("a[href*='youtu.be/'], a[href*='/shorts/'], a[href*='watch?v=']").first
            url = link.get_attribute("href", timeout=10000) or ""
        except Exception:
            pass
        _yt_wait_upload(page, on_progress)
        if not _click(page, "#done-button", 20000):
            _fail(page, "youtube", "No se encontró el botón «Publicar/Guardar» en YouTube Studio.")
        page.wait_for_timeout(5000)
        # aviso de comprobaciones (derechos de autor) que pide confirmar
        _click(page, "ytcp-prechecks-warning-dialog #primary-action-button, ytcp-prechecks-warning-dialog #secondary-action-button", 3000)
        _click(page, "ytcp-video-share-dialog #close-button, ytcp-uploads-still-processing-dialog #close-button", 8000)
        page.wait_for_timeout(2000)
    m = re.search(r"(?:youtu\.be/|/shorts/|v=)([\w-]{11})", url)
    vid = m.group(1) if m else ""
    if vid:
        url = f"https://youtube.com/shorts/{vid}" if is_short else f"https://youtu.be/{vid}"
    else:
        notes.append("No se pudo leer el enlace del video; revisa YouTube Studio.")
    _save_status("youtube", connected=True, error=None)
    on_progress(1.0)
    return {"platform_id": vid or f"yt-browser-{int(time.time())}", "url": url, "privacy": privacy,
            "note": " ".join(notes), "via": "navegador"}


# ── TikTok Studio ──────────────────────────────────────

TT_PRIVACY = {  # textos de «Quién puede ver esta publicación» (TikTok Studio usa el idioma de la cuenta)
    "PUBLIC_TO_EVERYONE": ("Todo el mundo", "Everyone"),
    "MUTUAL_FOLLOW_FRIENDS": ("Amigos", "Friends"),
    "SELF_ONLY": ("Solo tú", "Only you"),
}
TT_VISIBILITY = '[data-e2e="video_visibility_container"] button[role="combobox"], [data-e2e="video_visibility_container"] .Select__trigger'
TT_POST = 'button[data-e2e="post_video_button"]'


def _tt_dismiss_tour(page) -> None:
    """Cuentas nuevas ven un tour de bienvenida cuya capa tapa todos los clics: se cierra paso a paso."""
    for _ in range(6):
        if not _visible(page, ".react-joyride__overlay, .react-joyride__tooltip, .__floater"):
            return
        if not _click(page, '[data-test-id="button-primary"], .react-joyride__tooltip button:has-text("Entendido"), '
                            '.react-joyride__tooltip button:has-text("Got it"), [data-test-id="button-skip"]', 2000):
            page.keyboard.press("Escape")
        page.wait_for_timeout(700)


def _tt_privacy_now(page) -> str:
    try:
        return (page.locator(TT_VISIBILITY).first.inner_text(timeout=5000) or "").strip()
    except Exception:
        return ""


def _tt_set_privacy(page, privacy: str) -> bool:
    """Elige la privacidad y confirma que el selector la muestra (si no, no se publica)."""
    labels = TT_PRIVACY[privacy]
    ok = lambda: any(_tt_privacy_now(page).startswith(t) for t in labels)
    if ok():
        return True
    for _ in range(2):
        _tt_dismiss_tour(page)
        if not _click(page, TT_VISIBILITY, 5000):
            continue
        page.wait_for_timeout(700)
        for text in labels:
            opt = page.locator('[role="option"]').filter(has_text=text).first
            try:
                opt.click(timeout=2500)
                break
            except Exception:
                continue
        page.wait_for_timeout(600)
        if ok():
            return True
        page.keyboard.press("Escape")
    return False


def _tt_find_post(page, caption: str) -> str:
    """Id de la publicación recién hecha. Se busca por su texto: un video anclado siempre aparece primero en la
    lista, así que tomar el primer enlace daría el id de otro video."""
    key = re.sub(r"\s+", " ", caption).strip()[:25]
    for _ in range(10):
        try:
            for a in page.locator('a[href*="/video/"]').all()[:20]:
                text = re.sub(r"\s+", " ", a.inner_text() or "").strip()
                if text and (key.startswith(text[:25]) or text.startswith(key)):
                    m = re.search(r"/video/(\d+)", a.get_attribute("href") or "")
                    if m:
                        return m.group(1)
        except Exception:
            pass
        page.wait_for_timeout(3000)
    return ""


def upload_tiktok(video: Path, caption: str, privacy: str, on_progress: Callable[[float], None],
                  visible: bool = False, dry_run: bool = False) -> dict:
    """dry_run=True hace todo menos pulsar «Publicar» (para probar la conexión sin publicar nada)."""
    if privacy == "FOLLOWER_OF_CREATOR":
        raise BrowserError("TikTok Studio ya no ofrece la privacidad «Seguidores»; elige Público, Amigos o Solo yo.")
    if privacy not in TT_PRIVACY:
        privacy = "SELF_ONLY"
    with _browser("tiktok", visible=visible) as ctx:
        if not _logged_in(ctx, "tiktok"):
            _save_status("tiktok", connected=False)
            raise BrowserError("TikTok no tiene sesión iniciada. Ve a Configuración → Conexiones y pulsa "
                               "«Iniciar sesión en TikTok».")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(60000)
        page.goto("https://www.tiktok.com/tiktokstudio/upload", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        if _session_expired(page, "tiktok"):
            _save_status("tiktok", connected=False)
            raise BrowserError("La sesión de TikTok venció. Vuelve a iniciar sesión en Configuración → Conexiones.")
        try:
            page.locator('input[type="file"][accept*="video"], input[type="file"]').first.set_input_files(str(video))
            editor = page.locator('div.public-DraftEditor-content, div[contenteditable="true"]').first
            editor.wait_for(state="visible", timeout=120000)
        except Exception:
            _fail(page, "tiktok", "TikTok Studio no abrió el formulario de subida.")
        on_progress(0.2)
        page.wait_for_timeout(3000)
        _tt_dismiss_tour(page)
        editor.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        page.keyboard.insert_text(caption[:2200])
        page.wait_for_timeout(800)
        page.keyboard.press("Escape")  # cierra sugerencias de hashtags
        if not _tt_set_privacy(page, privacy):
            _fail(page, "tiktok", f"No se pudo elegir la privacidad «{TT_PRIVACY[privacy][0]}» en TikTok; "
                                  "no se publicó por seguridad.")
        # el botón «Publicar» se habilita cuando termina la subida
        t0 = time.time()
        while time.time() - t0 < 1800:
            btn = page.locator(TT_POST).first
            try:
                if btn.count() and btn.is_enabled() and btn.get_attribute("aria-disabled") != "true" \
                        and btn.get_attribute("data-disabled") != "true":
                    break
            except Exception:
                pass
            on_progress(min(0.85, 0.2 + (time.time() - t0) / 600))
            page.wait_for_timeout(2000)
        else:
            _fail(page, "tiktok", "La subida a TikTok no terminó en 30 minutos.")
        _tt_dismiss_tour(page)
        if not any(_tt_privacy_now(page).startswith(t) for t in TT_PRIVACY[privacy]):  # última comprobación
            _fail(page, "tiktok", "La privacidad cambió antes de publicar; no se publicó por seguridad.")
        if dry_run:
            return {"platform_id": "", "url": "", "privacy": _tt_privacy_now(page), "note": "ensayo: no se publicó",
                    "caption": page.locator('div.public-DraftEditor-content').first.inner_text()[:200],
                    "screenshot": _shot(page, "tiktok-ensayo")}
        page.locator(TT_POST).first.click()
        page.wait_for_timeout(2000)
        _click(page, 'button:has-text("Post now"), button:has-text("Publicar ahora")', 4000)  # aviso de revisión
        try:
            page.wait_for_url(re.compile(r"tiktokstudio/content"), timeout=90000)
        except Exception:
            _fail(page, "tiktok", "TikTok no confirmó la publicación.")
        vid = _tt_find_post(page, caption)
    _save_status("tiktok", connected=True, error=None)
    on_progress(1.0)
    return {"platform_id": vid or f"tt-browser-{int(time.time())}", "url": "", "privacy": privacy,
            "note": "" if vid else "Publicado; TikTok aún procesa el video (el enlace aparecerá en TikTok Studio).",
            "via": "navegador"}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "login" and sys.argv[2] in PLATFORMS:
        ok = login(sys.argv[2])
        print("Sesión guardada." if ok else "No se completó el inicio de sesión.")
        sys.exit(0 if ok else 1)
    print(__doc__)
    sys.exit(2)
