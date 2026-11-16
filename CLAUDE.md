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

| | PC principal (sesiones anteriores) | PC con GPU (verificado el 2026-11-13) |
|---|---|---|
| Hardware | Portátil i7-8550U, sin GPU NVIDIA, 16 GB RAM | Portátil Ryzen 5 8645HS, **RTX 4050 Laptop 6 GB** (Ada, cc 8.9), 15 GB RAM, ~50 GB libres en C: |
| Rol | Pipeline completo en CPU | Igual + **video IA local con ComfyUI** |
| Python | 3.14 (venv en `venv/`) | venv con **Python 3.12** (funciona; las pruebas pasan) |

- El pipeline base debe seguir funcionando solo con CPU (Windows, Python 3.12+). Lo que necesite GPU es opcional.
- El plan original suponía una RTX 5060 de 8 GB; la real es de 6 GB. Con 6 GB y 15 GB de RAM, los modelos de 14B
  quedan descartados en la práctica; se usa Wan 2.2 TI2V-5B cuantizado (GGUF Q5_K_M) a 480p.
- ComfyUI portable está **fuera del repo**, en `%USERPROFILE%\ComfyUI_windows_portable` (v0.45.0, Python 3.13
  embebido, PyTorch 2.14 + CUDA 13.0), con el nodo `custom_nodes/ComfyUI-GGUF`.

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
  Si la página está en un portafolio comercial (Business Suite), `/me/accounts` viene vacío: se usan los ids de
  `granular_scopes` del token (`facebook._granted_pages`). Síntoma del error: Instagram decía «nonexisting field
  (instagram_business_account)» porque el token apuntaba al perfil personal.
- Facebook video largo: subida por partes (`upload_phase` start/transfer/finish); en una sola petición, 177 MB
  devolvían una página de error («Expecting value»). Instagram (2026-11-15): `ProcessingFailedError` (rupload) y
  2207076 (`video_url`) son fallos intermitentes de Meta: en pruebas fallaban los Reels largos, pero luego un Short de
  55 s subió bien y otro siguió fallando. No es el archivo ni el transporte; se explica en el error y se reintenta con
  «Publicar». Segunda vía (`publish.meta_fallback`, por defecto activa; `pipeline._instagram` / `_facebook`):
  si la API falla, Instagram se publica por navegador (`browser.upload_instagram`, éxito confirmado con la respuesta
  de `/api/v1/media/configure`, activa «Agregar etiqueta de IA» si el video tiene tomas IA) y un Reel de Facebook se
  sube como video de página; el video largo se reintenta una vez. Nunca se reintenta si la orden de publicar quedó
  sin respuesta (`instagram.UncertainPublish`, error «(publicación)» de Facebook). Verificado 2026-11-15: la API
  falló con short_2 y el respaldo lo publicó.
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
- Gemini TTS sigue el idioma de la instrucción de estilo: con estilo en español y guion en inglés traducía frases
  enteras. `catalog.reading_instruction` manda el estilo en el idioma del guion con la orden de no traducir.
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
- `catalog.py`: listas cerradas (regiones de YouTube, voces por país, estilos visuales y de lectura, voces de Gemini).
  `settings.validate` (al guardar) corrige enums, rangos, región (acepta USA→US), voz de otro idioma y versión de
  Graph; la interfaz muestra los avisos. En la interfaz: `choiceField` (lista + «Personalizado…») y `numSelect`.
  `util.redact` quita claves y tokens de todo lo que se escribe en `runs/` (antes un error 400 guardaba la key).
- `publish/browser.py`: publicación por navegador (por defecto para YouTube y TikTok: `youtube_method`/`tiktok_method`
  = browser|api). Patchright + Chrome instalado, perfil persistente en `data/navegador/<plataforma>` (login visible una
  vez: `python -m agente.publish.browser login youtube`), subidas con ventana fuera de pantalla (`browser_visible`).
  Motivo: la Data API sin auditoría deja los videos en privado y TikTok sin auditoría solo «Solo yo». Selectores por
  atributos (interfaz en español), verificación de privacidad antes de publicar, captura en `data/navegador/errores/`.
  Basado en social-auto-upload (MIT). Verificado 2026-11-15: YouTube sube y publica en privado (27 s); TikTok
  Studio verificado en ensayo (`dry_run=True`): sigue el idioma de la cuenta (ignora `?lang=`), las cuentas nuevas
  muestran un tour (react-joyride) que tapa los clics (`_tt_dismiss_tour`), privacidad = combobox en
  `video_visibility_container` con opciones «Todo el mundo / Amigos / Solo tú» (ya no hay «Seguidores»). Publicación
  real «Solo yo» verificada (19 s). El id se busca por el texto (`_tt_find_post`): un video anclado sale primero.

## Métricas y audiencia (2026-11-16)

- Métricas de Meta: sin `read_insights` (Facebook) ni `instagram_manage_insights` (Instagram) la API rechaza las
  vistas; antes se guardaban como 0 y habrían enseñado mal al aprendizaje. Ahora quedan desconocidas (`views=None`,
  no cuentan) y `metrics.collect` avisa qué permiso falta. Instagram por navegador guarda el id de la API
  (`instagram.media_id_for` por el código del enlace).
- Métricas de TikTok sin API aprobada: `browser.tiktok_stats` abre TikTok Studio con la sesión guardada y lee la
  respuesta `/tiktok/creator/manage/item_list/v1/` (item_id, play_count, like_count, comment_count, share_count,
  favorite_count). En el aprendizaje, compartir y guardar valen el doble que un «me gusta» (`learning.reward`).
  Primeras cifras reales (17 h): TikTok e Instagram 86-135 vistas por Short, Facebook 25-39, YouTube 1-3 (subidos
  en privado por la configuración del usuario y abiertos a mano después).
- Investigación: el nicho se traduce al idioma de la audiencia (`research.search_query`, caché en
  `data/cache/search_query.json`, o `content.search_query` manual); con «Historias de terror» en un canal en inglés
  salían tendencias en español.
- Guion: compuertas de retención (gancho de 5-8 palabras en los 2 primeros s, primera escena ≤ 14 palabras,
  confirmación antes de los 5 s, cierre en bucle), Shorts de 70-100 palabras (salían de 54-56 s), títulos ≤ 60
  caracteres con el término de búsqueda y descripción con él en los primeros 160. `gemini-4-hydrogen` a veces corta
  la respuesta (JSON válido sin Shorts): `scriptgen._gaps` lo detecta y se reintenta hasta 2 veces con el siguiente
  modelo de la cadena.

- Decisiones del usuario (2026-11-16): **no** declarar contenido IA en las publicaciones (`publish.ai_label`, por
  defecto apagado). Siempre `#parati` (+ `#fyp` en inglés/portugués) y `#shorts` en Shorts
  (`scriptgen.finalize_hashtags`), más los hashtags más usados del nicho (`research.top_hashtags`, pesados por
  vistas/día). Instagram por navegador elige «Original» en «Recortar» (por defecto recorta a 1:1) y lo comprueba con
  la forma de la vista previa. Apagado automático (`general.shutdown_after`): solo en la ejecución diaria
  (`run_day.ps1` pasa `--scheduled`), `shutdown /s /t 120`, cancelable con `shutdown /a`.
- Hora de publicación (`publish.publish_time`, «HH:MM» del PC): con publicación automática, los videos listos
  esperan (`pipeline.wait_publish_time`) y salen en todas las redes a la vez; si ya pasó la hora, enseguida.
- Imagen con personaje de referencia («Nano Banana», `gemini-3.1-flash-image` y similares): la key del usuario los
  ve, pero el plan gratuito responde 429 (requiere facturación). Alternativa local por probar: un modelo de edición
  de imagen con referencia en ComfyUI (p. ej. Flux Kontext GGUF), pesado para 6 GB.
- Imagen y video de Google con clave aparte (`gemini_media_api_key`, «Gemini API key (imagen y video)»;
  `agente/gemini_media.py`): Nano Banana crea una imagen de referencia del personaje por video
  (`attach_character`, `character.png` en la carpeta de fuentes) y cada imagen clave de escena sale de ella
  (`video.character_ref`, funciona con ComfyUI y Veo). Proveedor visual `veo` (`VeoVideo`, `predictLongRunning`,
  duraciones 4/6/8 s, variante «fast» por defecto; con Veo el director solo revisa imágenes clave, no regenera
  video). El botón «Probar» lista los modelos sin generar (no confirma cuota).
- Investigación de nicho (`agente/niche.py`, Configuración → Investigar un nicho): la IA propone 6 nichos, cada uno se
  mide en YouTube (mediana de vistas/día, interacción, vistas por suscriptor, % de canales pequeños, % cortos;
  ~105 unidades de cuota por nicho) y la IA recomienda configuración; «Usar este nicho» la aplica (si recomienda
  ComfyUI y no está configurado, deja stock).

## Cómo verificar (método acordado)

- Pruebas sin red: `venv\Scripts\python.exe -m unittest discover -s tests`.
- **Ver**: hojas de contacto con ffmpeg (`-vf "fps=1/3,scale=270:-1,tile=6x2" -frames:v 1`) del `final.mp4` y leer el JPG.
- **Escuchar**: enviar el audio (mp3) a Gemini y pedir crítica de productor; `review.py` ya lo hace. Su oído no es
  preciso para tiempos (se adelanta ~0,5 s incluso con tiempos exactos de Edge).
- **Prueba de punta a punta** sin tocar la configuración del usuario: un script que reemplaza `settings.load` en memoria
  (1 Short, sin video largo) y llama `pipeline.main(["--no-publish", "--run-id", "zz-prueba"])`. Borrar `runs/zz-*` al final.
- Avisa al usuario antes de pruebas que gasten cuota o dinero; nunca publiques en sus cuentas sin que lo pida.

## Video IA local (hecho en el PC con GPU)

Objetivo del usuario: video de calidad profesional tipo cine o anime generado **localmente**.

- Proveedor visual **`comfyui`** (`agente/comfyui.py`, `ComfyVideo`, misma interfaz que `FalVideo`): texto→video e
  imagen→video desde el último fotograma de la toma anterior, por la API HTTP de ComfyUI (`/upload/image`, `/prompt`,
  `/history`, `/view`, `/interrupt`, `/free`). Workflow en `agente/workflows/wan22_ti2v_5b.json` (formato API, con
  marcadores `{{prompt}}`, `{{width}}`… que reemplaza `comfyui.fill`; sin imagen se borra el nodo `{{start_image}}`).
- En `SaveVideo` (ComfyUI ≥ 0.45) los combos anidados van con punto en la API: `"format": "mp4", "format.codec": "h264"`.
- Modelo: Wan 2.2 TI2V-5B GGUF Q5_K_M + UMT5 GGUF Q5_K_M + `wan2.2_vae`, a 832x480 (múltiplos de 32), 24 fps, 4n+1 cuadros.
  Tiempo medido (2026-11-13, RTX 4050 6 GB): ~19 s por paso, ~8 min por toma de 5 s (la primera ~11,5 min por la
  carga), 20 pasos. La continuidad imagen→video funciona; con 16 GB la RAM libre baja a ~1 GB al cargar los modelos.
  Run de punta a punta (2026-11-14, Short de 36 s, 10 segmentos IA encadenados, comfy_max_shots=0): 63 min, revisión
  IA 9/10, sin saltos en los empalmes (medido con `scdet`). Ritmo ≈ 1,6 min de GPU por segundo de video → 10 min ≈ 16-17 h.
  Problema visto: la cadena mantiene el ambiente pero se aleja de la narración (el sujeto casi no aparece). Enlace:
  último cuadro exacto en PNG (`visuals.last_frame`) y se recorta el 1.er cuadro de cada toma encadenada.
- **Director de continuidad** (contra esa deriva): el guion trae `visual_bible` (personaje, lugar, estilo; va al final
  de cada prompt IA y los `visual_prompt` nombran al sujeto con las mismas palabras); `comfy_chain="scene"` encadena
  solo dentro de cada escena y corta al cambiar (`"all"` = una sola cadena); `comfy_director` (por defecto activo):
  `vision.judge_shot` mira el cuadro medio y el final con Gemini/Claude y, si la nota < `comfy_director_min` (6),
  regenera la toma una vez desde texto con `better_prompt`. El punch-in solo se aplica en cortes reales.
  Run 2026-11-14 (Short de 33 s, todo IA): 81 min, 3 tomas regeneradas, revisión 8/10; el mismo personaje se ve
  en todo el video y sigue la historia. Gemini a veces entra en bucle repitiendo palabras: por eso
  `gemini.generate(max_tokens=…)` (`max_output_tokens`) y `judge_shot` rescata la nota de un JSON cortado.
- **Imagen clave primero** (`comfy_keyframes`, por defecto activo): cada arranque de cadena genera 1 cuadro con el
  mismo Wan (`ComfyVideo.keyframe`, length=1, ~1 min frente a 5-8 min de una toma), el director lo revisa (hasta 3
  intentos con `better_prompt`, se queda la mejor) y luego se anima con imagen→video. Si una toma de video reprueba,
  se regenera una vez y el director compara ambas versiones (se queda la de mejor nota). ComfyUI queda abierto entre
  los videos del run (`fetch_for_item(release=False)` + `visuals.release_ai` al final del paso visual).
  Run 2026-11-14 con imagen clave (Short de 35 s, todo IA): 70 min, revisión 9/10, sujeto visible en todos los
  cuadros, sin saltos (`scdet`). 1 imagen clave repetida y 2 tomas re-animadas (4-5/10 → 9/10). Límite pendiente:
  la cara del personaje cambia entre escenas (cada imagen clave sale de texto); haría falta una imagen de
  referencia (IP-Adapter/PuLID o LoRA del personaje), que Wan 2.2 5B no trae.
- Modo mixto (`ai_select`, vale para ComfyUI y fal.ai): `smart` (por defecto) = IA en las escenas que el guion marca
  `needs_ai` (personaje, momento concreto, algo inexistente) y stock con visión en las genéricas; si la visión rechaza
  todo el stock de una escena, `assign_stock(rescue=…)` la pasa a la IA. `hook` = las primeras N; `all` = todas.
  `comfy_max_shots` es el tope de tomas IA por video (0 = sin tope), contado por escenas completas
  (`visuals.fetch_for_item`). La cadena de fotogramas solo sigue entre tomas IA consecutivas. Si `comfy_path` está
  configurado y ComfyUI está cerrado, el run lo abre y lo cierra al terminar; si ya estaba abierto, solo pide `/free`.
- Ideas siguientes: LoRA de estilo anime o Wan 2.2 14B (no cabe bien en 6 GB), imagen clave primero (texto→imagen) y
  luego imagen→video para personajes consistentes, publicación programada en YouTube (`publishAt`), voz clonada local,
  subtítulos con alineación forzada local (Whisper) para la voz de Gemini.

## Convenciones

- Mensajes al usuario y textos de la interfaz en español, claros y sin jerga; errores siempre traducidos a pasos concretos.
- Nada debe tumbar un run por un extra (música, efectos, miniatura, revisión): capturar y avisar con `run.warn`.
- Commits en español, con la línea de coautoría que indique el entorno.
