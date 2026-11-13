# CLAUDE.md — contexto para Claude Code

Este archivo se carga automáticamente al abrir Claude Code en esta carpeta. Resume el estado del
proyecto y las decisiones tomadas en las sesiones anteriores (hechas en otro PC), para continuar sin
repetir el trabajo. El repositorio es **público**: nunca escribas aquí claves, tokens, correos ni datos personales.

Documentación para el usuario: `DOCUMENTACION_PROYECTO.md` (detallada) y `README.md`.

## Qué es

Agente de Clips: pipeline en Python que cada día investiga tendencias de YouTube de un nicho, escribe guiones
con IA, narra, arma videos (1 largo horizontal + N Shorts verticales) con clips de stock, animaciones Remotion,
subtítulos, música y efectos, los revisa con IA y los publica (YouTube, TikTok, Facebook, Instagram Reels).
Aprende de las métricas qué ganchos y rasgos rinden mejor. Interfaz web local (FastAPI) en 127.0.0.1:8585,
lanzada por `AgenteDeClips.exe` (C#, `launcher/`).

El usuario escribe en español y espera respuestas en español. Quiere la mejor solución para el proyecto, no una
implementación literal, y prefiere opciones gratuitas y sin instalación junto a las de pago.

## Dos equipos

| | PC principal (sesiones anteriores) | PC con GPU (este, si estás aquí por primera vez) |
|---|---|---|
| Hardware | Portátil i7-8550U, sin GPU NVIDIA, 16 GB RAM | Ryzen 7 serie 8000, **RTX 5060 8 GB** (Blackwell), 16 GB RAM |
| Rol | Pipeline completo en CPU | Igual + **modelos locales de video IA** |
| Python | 3.14 (venv en `venv/`) | Instalar Python 3.14 y ejecutar `setup.ps1` o abrir `AgenteDeClips.exe` |

- El pipeline base debe seguir funcionando solo con CPU (Windows, Python 3.14). Lo que necesite GPU es opcional.
- RTX 5060 = Blackwell: PyTorch necesita CUDA 12.8 o superior.
- Con 8 GB de VRAM y 16 GB de RAM, los modelos de 14B solo caben cuantizados (GGUF/fp8) con descarga a RAM, que queda justa.

## Credenciales (importante en un PC nuevo)

- Todas las claves viven en el **Administrador de credenciales de Windows** (keyring, servicio `AgenteDeClips`),
  y se ingresan desde la interfaz (Configuración → Credenciales). **No viajan con git**: en el PC nuevo hay que
  ingresarlas otra vez. Nunca las escribas en archivos del proyecto ni las imprimas.
- `data/` (settings.json, historial, métricas, aprendizaje) y `runs/` están en `.gitignore`: tampoco viajan.
  Si el usuario quiere conservar historial y aprendizaje, debe copiar `data/` a mano entre equipos.
- `config.yaml` y `client_secret.json` son archivos antiguos con claves filtradas; están ignorados por git.
  El usuario debe rotar esas claves y borrarlos (botón en Configuración).
- Facebook/Instagram: usar un token de **usuario de larga duración** (Depurador de tokens → Extend); la app
  lo convierte sola en token de página que no vence (`facebook.normalize_token`).
- YouTube: si Google muestra «Acceso bloqueado», publicar la app OAuth (Google Auth Platform → Público → Publicar app).

## Arquitectura (agente/)

- `pipeline.py`: orquestador y CLI (`--no-publish`, `--publish-only RUN_ID`, `--metrics-only`, `--resume RUN_ID`).
  Pasos: research → script → voice → visuals → render (+miniatura +revisión IA) → publish → metrics.
  Guarda `audio.json` y `shots.json` por video para que «Reintentar» (`--resume`) reutilice lo hecho.
- `scriptgen.py`: guion estructurado (Pydantic) con Claude API, Gemini o Ollama. Campos clave por escena:
  `narration`, `visual_query` (inglés, stock), `visual_prompt` (inglés, para video IA), `animation`;
  por video: `music` (mood + prompt), `thumbnail_text`; por paquete: `broll_queries`.
- `gemini.py`: Gemini API gratuita, **Interactions API** (`POST /v1beta/interactions`, header `Api-Revision: 2026-05-20`,
  `x-goog-api-key`). `interact()` reintenta 503 y cae al siguiente modelo gratis. Acepta texto, imagen y audio.
- `tts.py`: Edge TTS (tiempos exactos por palabra) o Gemini TTS (`gemini-3.8-flash-tts`, gratis; tiempos estimados
  alineando frases con pausas reales: `align_words`). En paralelo; si Gemini falla, el video entero usa Edge.
- `visuals.py` + `vision.py`: Pixabay/Pexels; una IA con visión ordena candidatos y **descarta** los sin relación o que
  contradicen el nicho; si faltan, `broll_queries` + `rank_pool`; si aún faltan, funde tomas. También fal.ai encadenado.
- `motion.py` + `motion/`: Remotion 4.0.539 (Node 24). Capas transparentes ProRes 4444 (composición `Overlay`,
  plantillas titulo/lista/dato/frase/cta sincronizadas con la voz) y miniatura fija (composición `Miniatura`).
- `render.py`: ffmpeg (imageio-ffmpeg). Mezcla voz + música (ducking) + efectos, ganancia fija hacia -14 LUFS +
  limitador (no usar `loudnorm`: daba NaN). «Punch-in» con zoompan al cambiar de escena.
- `music.py`: compositor procedural con numpy (7 moods, buses, reverb por convolución, EQ, sidechain), Lyria (pago) o carpeta.
- `sfx.py`, `review.py` (Gemini mira 10 cuadros y escucha el audio; nota 1-10), `thumbnail.py`, `cleanup.py`,
  `notify.py` (toast de Windows), `learning.py` (bandido sobre ganchos + rasgos), `publish/` (youtube, tiktok, facebook, instagram).
- `app/server.py` + `app/static/`: interfaz en tiempo real (SSE). Token de sesión y chequeo de Host.

## Cómo verificar (método acordado)

- Pruebas sin red: `venv\Scripts\python.exe -m unittest discover -s tests`.
- **Ver**: hojas de contacto con ffmpeg (`-vf "fps=1/3,scale=270:-1,tile=6x2" -frames:v 1`) del `final.mp4` y leer el JPG.
- **Escuchar**: enviar el audio (mp3) a Gemini y pedir crítica de productor; `review.py` ya lo hace. Su oído no es
  preciso para tiempos (se adelanta ~0,5 s incluso con tiempos exactos de Edge).
- **Prueba de punta a punta** sin tocar la configuración del usuario: un script que reemplaza `settings.load` en memoria
  (1 Short, sin video largo) y llama `pipeline.main(["--no-publish", "--run-id", "zz-prueba"])`. Borrar `runs/zz-*` al final.
- Avisa al usuario antes de pruebas que gasten cuota o dinero; nunca publiques en sus cuentas sin que lo pida.

## Lo que sigue en el PC con GPU (plan acordado)

Objetivo del usuario: video de calidad profesional tipo cine o anime generado **localmente**.

1. Instalar **ComfyUI** en el PC con GPU (PyTorch CUDA 12.8+), como servicio en la red local o en el mismo PC.
2. Modelos candidatos (verificar requisitos actuales antes de descargar):
   - **Wan 2.2 TI2V-5B**: recomendado; 720p, cabe en 8 GB con descarga a RAM. Apache 2.0.
   - Wan 2.2 14B GGUF + LoRA Lightx2v: mejor movimiento; ~2-3 min por clip de 5 s a 480p según usuarios.
   - **Index-AniSora** (Bilibili, basado en Wan) para anime; su versión liviana pide 12 GB (no confirmado en 8 GB).
   - LTX-2 / 2.3 GGUF: video con audio, ~540p en 8 GB según usuarios. HunyuanVideo 1.5 pide 14 GB: descartado.
   - Anime con estilo/personajes consistentes: Wan 2.2 + LoRA de estilo, o imagen clave primero y luego imagen→video.
3. Agregar un proveedor visual **`comfyui`** en `visuals.py` junto a `pexels` y `fal` (misma interfaz que `FalVideo`:
   texto→video e imagen→video encadenando el último fotograma), usando el `visual_prompt` de cada escena y la API HTTP
   de ComfyUI con un workflow JSON guardado en el repo. Ajustes en `settings.py` (URL, workflow, alcance) y en la UI.
4. Por tiempos (un Short de 40 s ≈ 8 clips ≈ 20 min), usar IA en el gancho y escenas clave, y stock en el resto.

Otras ideas pendientes (no pedidas aún): publicación programada en YouTube (`publishAt`), voz clonada local,
subtítulos con alineación forzada local (p. ej. Whisper) para la voz de Gemini en la GPU.

## Convenciones

- Mensajes al usuario y textos de la interfaz en español, claros y sin jerga; errores siempre traducidos a pasos concretos.
- Nada debe tumbar un run por un extra (música, efectos, miniatura, revisión): capturar y avisar con `run.warn`.
- Commits en español, con la línea de coautoría que indique el entorno.
