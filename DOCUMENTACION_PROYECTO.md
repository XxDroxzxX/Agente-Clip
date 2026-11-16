# Agente de Clips — Documentación

Sistema que investiga tendencias de un nicho, escribe un guion con IA y produce un **video largo horizontal** más varios **Shorts verticales**, con narración neural, clips de video por escena, subtítulos animados y música. Puede publicarlos en YouTube, TikTok y Facebook y aprende de las métricas qué estilo de gancho funciona mejor.

Todo se maneja desde una **interfaz web local** (`http://localhost:8585`) con seguimiento en tiempo real.

> **Seguridad:** este documento no contiene credenciales y nunca debe contenerlas. Las claves se ingresan en la interfaz y se guardan en el **Administrador de credenciales de Windows**, no en archivos del proyecto.

---

## 1. Cómo funciona un run

| # | Paso | Qué hace | Servicio |
|---|------|----------|----------|
| 1 | Investigación | Busca videos **recientes** del nicho y los puntúa por vistas/día y engagement (normalizados) | YouTube Data API |
| 2 | Guion | Escribe un plan estructurado: video largo + N Shorts, cada uno dividido en escenas con narración, descripción visual y animaciones | Claude API, Gemini API (gratis) u Ollama local |
| 3 | Narración | Voz neural por escena, con tiempos por palabra | edge-tts (gratis) |
| 4 | Material visual | Una toma cada ~5 s: clip de video real por escena (elegido con visión por IA), o video IA encadenado | Pixabay / Pexels (gratis) + Gemini o Claude; fal.ai (pago) o ComfyUI local en tu GPU (gratis) |
| 4b | Animaciones | Gráficos animados (gancho, listas, cifras, frases, cierre) como capas transparentes sobre algunas tomas | Remotion (local) |
| 5 | Montaje | Une tomas, quema subtítulos karaoke, mezcla voz + música con *ducking*, normaliza volumen (-14 LUFS) | ffmpeg (incluido) |
| 6 | Publicación | YouTube (largo + Shorts), TikTok (Shorts), Facebook (video + Reels) | APIs oficiales |
| 7 | Métricas | Mide lo publicado en los últimos 30 días y actualiza el aprendizaje | YouTube / Graph API |

**Video IA encadenado (opcional):** con fal.ai (nube) o ComfyUI (local), cada segmento se genera a partir del **último fotograma** del anterior (*image-to-video*), lo que da continuidad visual. Si un segmento falla, se usan clips de stock como respaldo.

**Modo mixto (por defecto con fal.ai o ComfyUI):** el guion marca qué escenas necesitan video IA (el personaje de la historia, un momento concreto, algo que no existe en los bancos de video) y solo esas se generan; las escenas genéricas (paisajes, ciudades, comida, objetos) usan clips gratis de Pixabay/Pexels elegidos con visión. Si para una escena el stock no tiene nada que encaje, esa escena también pasa a la IA. *Máximo de tomas con IA por video* fija un tope de tiempo o de costo. En *Qué escenas van con IA* también se puede elegir «las primeras tomas» o «todas».

**Video IA local con ComfyUI (opcional, requiere GPU NVIDIA):** genera las tomas en tu propia tarjeta con **Wan 2.2 TI2V-5B** (licencia Apache 2.0), sin costo por video. Como es lento, por defecto solo las **primeras 2 tomas** de cada Short (el gancho) se generan con IA y el resto usa clips de stock elegidos con visión. Referencia medida en una RTX 4050 Laptop de 6 GB a 480p: **~8 min por toma de 5 s** (la primera del run ~11,5 min, porque carga los modelos); un Short con 2 tomas IA suma ~20 min. Con *Tomas con IA por video = 0* todo el video es IA encadenada: un Short de 36 s tardó 63 min de punta a punta (≈1,6 min de GPU por segundo de video), así que un video de 10 min tomaría unas 16-17 horas. Los empalmes entre tomas no muestran saltos (se enlaza el último cuadro exacto, sin pérdida, y se quita el cuadro repetido), pero en cadenas largas la imagen tiende a quedarse en el mismo ambiente y a alejarse de la narración. Para evitarlo hay un **director de continuidad**: el guion incluye una *ficha visual* (personaje, lugar y estilo) que se agrega a cada prompt; la cadena se reinicia en cada escena nueva (*Encadenar: por escena*); y una IA con visión revisa cada toma y regenera una vez la que no muestra lo que dice la narración (*Director IA*, nota mínima configurable). Con todo esto, un Short de 33 s todo IA tardó 81 min (3 tomas regeneradas) y el mismo personaje aparece de principio a fin. Además, con *Imagen clave primero* (activado por defecto) cada escena arranca de una imagen fija (~1 min) que el director revisa y repite si hace falta antes de animarla, así los reintentos cuestan un minuto y no una toma completa; cuando una toma de video se regenera, se comparan ambas versiones y se queda la mejor. Entre los videos de un mismo run ComfyUI no se cierra, para no volver a cargar los modelos. Resultado medido: un Short de 35 s todo IA tardó 70 min (antes 81), con nota 9/10 y el personaje visible en todas las tomas. Límite actual: la cara del personaje puede cambiar de una escena a otra. Durante la carga la RAM queda casi llena con 16 GB: conviene no tener abiertos programas pesados. Se configura en *Video y voz → Material visual*: tomas con IA por video, resolución, estilo visual (p. ej. `cinematic, film grain` o `anime style`), pasos y carpeta de ComfyUI. Si ComfyUI está cerrado y se indicó su carpeta, el run lo abre solo y lo cierra al terminar (libera la memoria). Cancelar un run detiene también la toma en curso, y **Reintentar** reutiliza las tomas IA ya generadas.

Instalación (una vez, ~20 GB):
1. Descarga `ComfyUI_windows_portable_nvidia.7z` desde github.com/Comfy-Org/ComfyUI/releases y extráelo (p. ej. en tu carpeta de usuario).
2. En `ComfyUI\custom_nodes`: `git clone https://github.com/city96/ComfyUI-GGUF` y luego `..\..\python_embeded\python.exe -s -m pip install -r ComfyUI-GGUF\requirements.txt`.
3. Coloca los modelos:
   - `models\unet\Wan2.2-TI2V-5B-Q5_K_M.gguf` (huggingface.co/QuantStack/Wan2.2-TI2V-5B-GGUF)
   - `models\text_encoders\umt5-xxl-encoder-Q5_K_M.gguf` (huggingface.co/city96/umt5-xxl-encoder-gguf)
   - `models\vae\wan2.2_vae.safetensors` (huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged, carpeta `split_files/vae`)
4. En la interfaz elige *Video IA local en tu GPU (ComfyUI)* e indica la carpeta de ComfyUI portable.

El workflow está en `agente/workflows/wan22_ti2v_5b.json` (formato API de ComfyUI). Puedes usar otro (por ejemplo, con un LoRA de estilo anime) exportándolo con *Export (API)* y poniendo los marcadores `{{prompt}}`, `{{seed}}`, `{{width}}`, `{{height}}`, `{{frames}}`, `{{fps}}`, `{{steps}}` y `{{start_image}}` (este último en un nodo LoadImage conectado a una entrada opcional).

**Selección inteligente de clips:** por cada escena se buscan varios candidatos y una IA con visión mira sus miniaturas y los ordena según lo que dice la narración (que muestre la acción concreta, calidad, sin marcas de agua). Usa Gemini (gratis) si hay clave, o Claude Haiku. Si no hay ninguna o se agota la cuota, se usa el orden del banco de clips. Se configura en *Video y voz → Selección inteligente de clips*.

**Animaciones (Remotion):** el guion marca qué escenas llevan un gráfico animado y con qué texto. Hay cinco plantillas en `motion/src/templates`: *titulo* (gancho con palabras que rebotan y una palabra resaltada), *lista* (elementos numerados que entran escalonados), *dato* (cifra que cuenta desde 0; si es porcentaje, un anillo se llena), *frase* (idea clave en tarjeta) y *cta* (cierre con botón que late). Cada parte de la animación entra **cuando la voz la dice** (las palabras se buscan en los tiempos de la narración): cada elemento de una lista aparece al nombrarlo y la cifra empieza a contar al pronunciarla. Una escena animada usa una sola toma, para que la animación la acompañe completa. Se renderizan como capas transparentes que respetan la zona de los subtítulos y se superponen a la toma con ffmpeg. En un i7 de 8.ª generación cada capa de 5 s tarda unos 25 s a 1080p. Si Remotion falla, el video sale igual, sin esa animación.

Para ver y editar las plantillas en vivo: `cd motion` y `npm run studio`.

**Aprendizaje:** cada guion usa un *estilo de gancho* (pregunta, dato sorprendente, error común, historia, promesa, contraintuitivo). Cuando las métricas de un video tienen 48 h o más, se calcula una recompensa `log(vistas) × (1 + 5 × engagement)`, normalizada por plataforma. Los estilos con mejor promedio se eligen con más frecuencia (*epsilon-greedy*, 30 % de exploración por defecto).

---

## 2. Requisitos

- Windows 10/11, Python **3.11 o superior** (probado con 3.14) en el PATH.
- ~1 GB libre (más el espacio de los videos generados en `runs/`).
- No requiere GPU (solo el video IA local con ComfyUI usa una NVIDIA de 6 GB o más). ffmpeg viene incluido en las dependencias (`imageio-ffmpeg`).
- **Node.js LTS** (nodejs.org) para las animaciones. Sin Node el agente funciona igual, pero sin animaciones.
- Remotion es gratis para personas y empresas de hasta 3 empleados; empresas más grandes necesitan una *Company License* (remotion.dev/license).

---

## 3. Instalación y arranque

**Doble clic en `AgenteDeClips.exe`** (en la raíz del proyecto). El ejecutable:

1. Si es la primera vez, o si cambió `requirements.txt`, ejecuta `setup.ps1` en una ventana visible (crea el `venv` e instala dependencias, incluido ffmpeg).
2. Levanta el servidor (backend FastAPI + interfaz web) en segundo plano, sin ventana de consola.
3. Abre `http://localhost:8585` en el navegador cuando el servidor responde.
4. Queda como **icono en la bandeja del sistema** (junto al reloj). Con doble clic se abre la interfaz; con clic derecho aparece el menú:

| Opción | Qué hace |
|---|---|
| Abrir interfaz | Abre el navegador en la interfaz |
| Ver registro del servidor | Abre `data/server.log` |
| Abrir carpeta del proyecto | Abre la carpeta en el Explorador |
| Reiniciar servidor | Útil tras actualizar el código |
| Iniciar con Windows | Arranca el servidor al iniciar sesión, sin abrir el navegador |
| Crear acceso directo en el escritorio | Crea un acceso directo con el icono |
| Detener y salir | Apaga el servidor. Si hay un run en curso, pregunta si cancelarlo o dejarlo terminar en segundo plano |

Si se vuelve a abrir el ejecutable mientras ya está corriendo, solo abre la interfaz. Si el servidor se cae, aparece una notificación para reiniciarlo.

Lo único que se necesita instalado de antemano es **Python** en el PATH.

**Recompilar el ejecutable** (solo si se modifica `launcher/AgenteDeClips.cs`): `.\launcher\build.ps1`. Usa el compilador de C# que trae Windows, así que no hay que instalar nada.

**Alternativa por consola:**

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup.ps1      # crea venv, instala dependencias y carpetas
.\run_ui.ps1     # servidor en esta consola (Ctrl+C para detener)
```

**Migrar a otro equipo:** copia la carpeta **sin** `venv/` y abre `AgenteDeClips.exe`, que reinstala todo solo. Las credenciales **no viajan con la carpeta**, porque están en el Administrador de credenciales de Windows: vuelve a ingresarlas en la nueva máquina. Para conservar el historial y el aprendizaje, copia también `data/` y `runs/`.

---

## 4. Configuración inicial (desde la interfaz → Configuración)

### Credenciales

| Credencial | Para qué | Dónde se obtiene | Costo |
|---|---|---|---|
| Gemini API key | Guiones y selección de clips con visión | aistudio.google.com/apikey (cuenta de Google) | **Gratis, sin tarjeta**, con pocas solicitudes diarias por modelo (si se agota uno, se prueba el siguiente). En el plan gratuito Google puede usar los datos enviados para mejorar sus productos |
| Claude API key | Escribir guiones | console.anthropic.com → API Keys | Pago por uso (centavos por guion). **No incluida en la suscripción Pro de claude.ai.** |
| Pixabay API key | Clips de video por escena | Crea una cuenta en pixabay.com; la clave aparece en pixabay.com/api/docs | Gratis (100 solicitudes/minuto) |
| Pexels API key (opcional) | Segunda fuente de clips | pexels.com/api. **Pexels pausó la emisión de claves nuevas** (nov. 2026); con Pixabay basta | Gratis (200 solicitudes/hora) |
| YouTube Data API key | Investigar tendencias | Google Cloud Console → Credenciales | Gratis (cuota diaria) |
| YouTube OAuth client (JSON) | Subir videos | Google Cloud Console → Credenciales → ID de cliente OAuth (app de escritorio) | Gratis |
| TikTok client key / secret | Publicar en TikTok | developers.tiktok.com → tu app | Gratis |
| Facebook Page token | Publicar en tu página | Meta for Developers (permisos `pages_manage_posts`, `publish_video`) | Gratis |
| fal.ai API key | Video generado con IA (opcional) | fal.ai | Pago por segundo de video |

Cada credencial tiene botón **Probar** para verificarla. Si hay clave de Pixabay y de Pexels, se usan ambas (primero Pexels); una clave inválida se omite durante el run con un aviso.

### Conexiones (una sola vez)

- **YouTube y TikTok por navegador (recomendado, opción por defecto):** en *Conexiones* pulsa *Iniciar sesión en YouTube* o *Iniciar sesión en TikTok*. Se abre Google Chrome con un perfil propio de la app (`data/navegador/`); inicias sesión como siempre y la ventana se cierra sola al detectar la sesión. Desde ahí cada publicación abre Chrome fuera de la pantalla (o visible, con *Ver la ventana del navegador al publicar*), sube el video y lo publica con la privacidad elegida. No hace falta crear proyectos en Google Cloud ni apps de desarrollador, y los videos pueden salir públicos. Requiere Google Chrome instalado. Si algo falla, el error indica qué pasó y deja una captura en `data/navegador/errores/`. **Riesgos:** YouTube y TikTok no permiten oficialmente automatizar sus páginas; puede aparecer un captcha o una advertencia en la cuenta, y un cambio en sus páginas puede romper la publicación hasta actualizar la app. Publica pocas veces al día. Basado en la técnica de [social-auto-upload](https://github.com/dreammis/social-auto-upload) (MIT).
- Las opciones por API siguen disponibles en *Publicación → Cómo se conecta*:
- **YouTube:** guarda el OAuth client y pulsa *Conectar YouTube*; autoriza en la pestaña que se abre.
  - **«Acceso bloqueado: la app no completó la verificación»:** en Google Cloud → *Google Auth Platform → Público*, pulsa **Publicar app** (recomendado). Al conectar verás «Google no verificó esta app»: *Configuración avanzada → Ir a … (no seguro)*. Es seguro porque la app es tuya, y la autorización no vence. La otra opción es dejarla en *Prueba* y agregar tu correo en **Usuarios de prueba**, pero en ese modo Google vence la autorización **cada 7 días**.
  - Si la autorización vence o se revoca, Conexiones muestra «Hay que reconectar».
- **Facebook:** no usa ventana de autorización; basta con guardar el token en Credenciales. Para que **no venza**, genera un token de *usuario* en el Explorador de la Graph API, extiéndelo en el *Depurador de tokens* (*Extend Access Token*) y pega ese token largo: la app obtiene sola el token de tu página, que no vence. Si pegas un token de página corto, deja de funcionar a las pocas horas («Session has expired»).
- **Segunda vía para Meta:** la API de Meta a veces rechaza un video por un fallo suyo (`ProcessingFailedError`). Con *Publicación → Segunda vía si falla Meta* (activada por defecto), Instagram se publica por navegador con la sesión de *Conexiones → Instagram · respaldo* (inicias sesión una vez) y un Reel de Facebook que falle se sube como video de la página. Si el video tiene tomas generadas con IA, se activa la etiqueta de IA que Instagram exige. Nunca se reintenta si hay duda de que ya se publicó.
- **Instagram Reels:** usa el mismo token. Tu Instagram debe ser profesional (empresa o creador), estar vinculado a la página y el token debe incluir `instagram_basic` e `instagram_content_publish`. Solo se publican los Shorts.
- **TikTok:** en tu app de TikTok registra la *Redirect URI* `http://localhost:8585/callback`, activa *Login Kit* y *Content Posting API*, y pulsa *Conectar TikTok*. El token se renueva solo.

### Música

No hace falta agregar nada. La IA del guion elige un estado de ánimo para cada video (energético, alegre, inspirador, tranquilo, misterioso, emotivo o tecnológico) y la música se crea con la duración exacta del video. En *Video y voz → Origen de la música* se elige:

| Origen | Cómo funciona | Costo |
|---|---|---|
| Generada (por defecto) | Compositor propio: progresión de acordes, bajo, colchón, arpegios con eco y batería según el estado de ánimo, con intro, desarrollo y cierre | Gratis, sin conexión y sin derechos de autor |
| Lyria (Google) | Música con IA a partir de una descripción que escribe la IA del guion. Usa la Gemini API key con facturación activa | ~US$0.04 (≤30 s) a US$0.08 por video |
| Carpeta | Un archivo al azar de `assets/music/` | — |

Si Lyria falla o la carpeta está vacía, se usa la música generada. La música generada lleva variaciones de intensidad y tiempo nota a nota, reverb de sala, ecualización que deja espacio a la voz (baja 2–4 kHz y 300 Hz), «bombeo» rítmico con el bombo y redobles cada 4 compases.

### Voz

| Motor | Ventajas | Notas |
|---|---|---|
| Microsoft Edge (por defecto) | Tiempos exactos por palabra para subtítulos y animaciones | Gratis, sin clave |
| Gemini TTS | Más expresiva; el «Estilo de lectura» se describe con palabras | Gratis con la Gemini API key. Los tiempos por palabra se estiman alineando el texto con las pausas reales del audio. Si falla, ese video usa la voz de Edge |

Las escenas se narran en paralelo (varias a la vez).

### Calidad automática

- **Selección de clips:** la IA con visión descarta los clips sin relación con la narración o que contradicen el tema del canal (p. ej. carne en un canal vegano). Si una escena se queda sin clip, se buscan tomas genéricas del nicho que el guion propone; si aun así faltan, las tomas de esa escena se funden en vez de usar relleno.
- **Revisión con IA:** al terminar cada video, Gemini mira 10 cuadros y **escucha el audio completo** (Claude solo mira cuadros). Da una nota de 1 a 10 y lista los problemas con su momento. La publicación automática se salta los videos reprobados; se pueden publicar a mano.
- **Ritmo:** efectos de sonido sintetizados (whoosh con cada animación, golpe en el gancho, barrido suave en los cambios de escena de los Shorts) y un acercamiento rápido al cambiar de escena.
- **Miniatura de YouTube:** para el video largo, la IA elige el mejor cuadro y Remotion compone la miniatura con un texto corto que escribe el guion. YouTube exige verificar el canal con tu teléfono (youtube.com/verify) para aceptar miniaturas personalizadas.

### Espacio y avisos

Los archivos de trabajo de cada run (tomas, fuentes, capas animadas, audios intermedios) se borran solos pasados 7 días (configurable); la caché de clips se limita a 5 GB. Los videos finales, miniaturas y guiones se conservan. Al terminar o fallar un run aparece una notificación de Windows.

---

## 5. Uso diario

- **Aprendizaje:** además del estilo de gancho, mide qué música, duración, cantidad de animaciones y motor de voz rinden mejor, y se lo indica al guionista cuando hay datos suficientes.
- **Si un run falla o lo cancelas:** pulsa **Reintentar**. Retoma desde el paso que falló y reutiliza el guion, las voces y las tomas que ya estaban listos.
- **Manual:** en *En vivo*, pulsa **Iniciar run**. Verás cada paso, la actividad, el guion, las tomas a medida que se preparan y los videos terminados. Si «Publicar al terminar» está apagado, revisa los videos y pulsa **Publicar**.
- **Automático:** en *Configuración → Ejecución diaria*, activa la tarea programada (usa el Programador de tareas de Windows y `run_day.ps1`). Publica solo si *Publicar automáticamente* está activo. Los runs automáticos aparecen en *Historial* y se pueden seguir en vivo si la interfaz está abierta.
- **Línea de comandos:**
  ```powershell
  venv\Scripts\python.exe -m agente.pipeline --no-publish
  venv\Scripts\python.exe -m agente.pipeline --publish-only 20261112-094829
  venv\Scripts\python.exe -m agente.pipeline --metrics-only
  ```

Duración típica en un portátil i7 de 8.ª generación: unos 10–20 minutos por run a 1080p (720p es más rápido).

---

## 6. Limitaciones de las plataformas

- **Publicación por navegador:** evita las limitaciones de las API sin auditoría, pero depende de que YouTube Studio y TikTok Studio no cambien su página y de que la sesión siga abierta (si vence, la app pide volver a iniciar sesión). Con TikTok publicado por navegador tampoco hay métricas.

- **YouTube (por API):** los proyectos de API **sin auditoría** de Google solo pueden subir videos **privados**, aunque se pida «público». Hay que solicitar la auditoría de la YouTube API para publicar públicamente. Cuota por defecto: 10 000 unidades/día.
- **TikTok (por API):** las apps sin auditoría solo publican como «Solo yo». El modo *borrador* envía el video a la bandeja de la app para terminar la publicación a mano. La API no ofrece métricas, así que TikTok no entra en el aprendizaje.
- **Facebook:** la versión de Graph API se configura en la interfaz (por defecto `v24.0`); actualízala cuando Meta la deje obsoleta. Los Reels deben durar entre 3 y 90 s.
- **edge-tts** usa el servicio de lectura en voz alta de Microsoft Edge; es gratuito pero no es una API oficial con garantías.

---

## 7. Estructura

```text
Agente de Clips/
├── AgenteDeClips.exe     Lanzador: instala, levanta el servidor y abre la interfaz
├── launcher/             Código fuente del lanzador (C#), icono y build.ps1
├── run_ui.ps1            Abre la interfaz desde consola
├── run_day.ps1           Run sin interfaz (tarea programada)
├── setup.ps1             Instalación
├── requirements.txt
├── agente/               Pipeline
│   ├── pipeline.py       Orquestador y CLI
│   ├── settings.py       Configuración + credenciales (keyring)
│   ├── events.py         Estado y eventos en tiempo real de cada run
│   ├── research.py       Tendencias de YouTube
│   ├── scriptgen.py      Guion estructurado (Claude / Gemini / Ollama)
│   ├── gemini.py         Cliente de la API gratuita de Gemini
│   ├── vision.py         Selección de clips con visión (Gemini / Claude)
│   ├── tts.py            Narración y tiempos por palabra
│   ├── visuals.py        Pixabay / Pexels / video IA (fal.ai o ComfyUI, encadenado por fotograma)
│   ├── comfyui.py        Cliente de ComfyUI local (workflows en agente/workflows/)
│   ├── render.py         Montaje, subtítulos, mezcla de audio
│   ├── motion.py         Puente con Remotion (capas animadas)
│   ├── music.py          Música de fondo generada / Lyria
│   ├── sfx.py            Efectos de sonido sintetizados
│   ├── review.py         Revisión de calidad con IA (imagen + audio)
│   ├── thumbnail.py      Miniatura de YouTube (Remotion)
│   ├── cleanup.py        Limpieza automática de espacio
│   ├── notify.py         Notificaciones de Windows
│   ├── learning.py       Historial y aprendizaje de ganchos
│   ├── metrics.py        Recolección de métricas
│   └── publish/          youtube.py, tiktok.py, facebook.py, instagram.py
├── motion/               Animaciones Remotion: plantillas (src/templates) y render.mjs
├── app/                  Interfaz web (FastAPI + HTML/JS)
├── assets/music/         Música propia (opcional; por defecto se genera)
├── data/                 settings.json, history.json, metrics.jsonl, learning.json, caché
├── runs/<fecha-hora>/    Cada run: run.json, events.jsonl, script.json, videos y tomas
└── _legacy/              Código anterior (referencia; se puede borrar)
```

La interfaz solo escucha en `127.0.0.1`, exige un token de sesión en cada llamada y rechaza otros *Host*, así que otras páginas web abiertas en el navegador no pueden controlarla.

---

## 8. Solución de problemas

| Síntoma | Causa probable |
|---|---|
| «Animaciones omitidas: Falta Node.js» | Instala Node.js LTS y vuelve a abrir AgenteDeClips.exe (detecta Node y completa la instalación) |
| El ejecutable muestra «La instalación no terminó» | Falta Python en el PATH o no hay internet; corrige y vuelve a abrirlo |
| El icono avisa «El servidor se detuvo» | Revisa *Ver registro del servidor*; suele ser el puerto 8585 ocupado por otro programa |
| «Iniciar run» deshabilitado | Falta una credencial crítica (ver el aviso del panel) |
| Tomas con borde amarillo en el panel | No se encontró material de stock para esa escena; se usó un fondo de color |
| Botón de conexión dice «Agregar credencial» | Falta la credencial de esa plataforma; el botón te lleva a ella y «¿Cómo lo obtengo?» explica los pasos |
| Video de YouTube queda privado | Proyecto de API sin auditoría (ver sección 6) |
| «Ya hay un proceso en curso» | Hay un run activo (manual o programado); espera o cancélalo |
| TikTok «Estado OAuth inválido» | Pasaron más de 15 minutos o se reinició la interfaz; vuelve a pulsar *Conectar TikTok* |
| YouTube: «Acceso bloqueado» al conectar | La app de Google está en *Prueba* y tu correo no es usuario de prueba: publica la app o agrégalo (sección 4, Conexiones) |
| YouTube: «Hay que reconectar» cada semana | La app está en modo *Prueba* (vence a los 7 días): publícala |
| «Gemini no respondió: la cuota gratuita de hoy se agotó» | Se agotó la cuota diaria de todos los modelos gratuitos; se renueva cada día. Mientras tanto usa Claude u Ollama |
| «Gemini no respondió: los servidores de Google están saturados» | Error 503 temporal de Google (ya se reintentó varias veces). Pulsa **Reintentar** en unos minutos |
| Facebook: «Session has expired» | Pegaste un token corto. Sigue los pasos de la sección 4 para un token que no vence |
| Instagram: «sin permiso» o «no tiene una cuenta vinculada» | Cuenta personal, no vinculada a la página o token sin `instagram_content_publish` |
| La miniatura no se aplicó en YouTube | Verifica el canal con tu teléfono en youtube.com/verify |
| Un video quedó «no aprobado» por la revisión IA | Lee los problemas en su tarjeta; si está bien, publícalo a mano. La nota mínima se ajusta en *Video y voz* |
| Ollama no responde / «Iniciar run» deshabilitado con Ollama | Instala Ollama desde ollama.com, ábrelo, ejecuta `ollama pull qwen2.5:7b` y verifica con *Probar Ollama* |
| «ComfyUI no responde» | Abre `run_nvidia_gpu.bat` de ComfyUI o indica su carpeta en *Material visual* para que el run lo inicie solo |
| «ComfyUI no encuentra el archivo …» | Falta un modelo: colócalo en la carpeta `models\…` que indica el mensaje y reinicia ComfyUI |
| «La GPU se quedó sin memoria» | Usa resolución IA 480p, menos segundos por segmento o cierra otros programas que usen la GPU |
