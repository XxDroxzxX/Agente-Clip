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
| 4 | Material visual | Una toma cada ~5 s: clip de video real por escena (elegido con visión por IA), o video IA encadenado | Pixabay / Pexels (gratis) + Gemini o Claude; o fal.ai (pago) |
| 4b | Animaciones | Gráficos animados (gancho, listas, cifras, frases, cierre) como capas transparentes sobre algunas tomas | Remotion (local) |
| 5 | Montaje | Une tomas, quema subtítulos karaoke, mezcla voz + música con *ducking*, normaliza volumen (-14 LUFS) | ffmpeg (incluido) |
| 6 | Publicación | YouTube (largo + Shorts), TikTok (Shorts), Facebook (video + Reels) | APIs oficiales |
| 7 | Métricas | Mide lo publicado en los últimos 30 días y actualiza el aprendizaje | YouTube / Graph API |

**Video IA encadenado (opcional):** con el proveedor fal.ai, cada segmento se genera a partir del **último fotograma** del anterior (*image-to-video*), lo que da continuidad visual. Si un segmento falla, se usan clips de stock como respaldo.

**Selección inteligente de clips:** por cada escena se buscan varios candidatos y una IA con visión mira sus miniaturas y los ordena según lo que dice la narración (que muestre la acción concreta, calidad, sin marcas de agua). Usa Gemini (gratis) si hay clave, o Claude Haiku. Si no hay ninguna o se agota la cuota, se usa el orden del banco de clips. Se configura en *Video y voz → Selección inteligente de clips*.

**Animaciones (Remotion):** el guion marca qué escenas llevan un gráfico animado y con qué texto. Hay cinco plantillas en `motion/src/templates`: *titulo* (gancho con palabras que rebotan y una palabra resaltada), *lista* (elementos numerados que entran escalonados), *dato* (cifra que cuenta desde 0; si es porcentaje, un anillo se llena), *frase* (idea clave en tarjeta) y *cta* (cierre con botón que late). Cada parte de la animación entra **cuando la voz la dice** (las palabras se buscan en los tiempos de la narración): cada elemento de una lista aparece al nombrarlo y la cifra empieza a contar al pronunciarla. Una escena animada usa una sola toma, para que la animación la acompañe completa. Se renderizan como capas transparentes que respetan la zona de los subtítulos y se superponen a la toma con ffmpeg. En un i7 de 8.ª generación cada capa de 5 s tarda unos 25 s a 1080p. Si Remotion falla, el video sale igual, sin esa animación.

Para ver y editar las plantillas en vivo: `cd motion` y `npm run studio`.

**Aprendizaje:** cada guion usa un *estilo de gancho* (pregunta, dato sorprendente, error común, historia, promesa, contraintuitivo). Cuando las métricas de un video tienen 48 h o más, se calcula una recompensa `log(vistas) × (1 + 5 × engagement)`, normalizada por plataforma. Los estilos con mejor promedio se eligen con más frecuencia (*epsilon-greedy*, 30 % de exploración por defecto).

---

## 2. Requisitos

- Windows 10/11, Python **3.11 o superior** (probado con 3.14) en el PATH.
- ~1 GB libre (más el espacio de los videos generados en `runs/`).
- No requiere GPU. ffmpeg viene incluido en las dependencias (`imageio-ffmpeg`).
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

- **YouTube:** guarda el OAuth client y pulsa *Conectar YouTube*; autoriza en la pestaña que se abre.
- **Facebook:** no usa ventana de autorización; basta con guardar el *Page access token* en Credenciales. La sección Conexiones muestra el nombre de la página o el problema del token.
- **TikTok:** en tu app de TikTok registra la *Redirect URI* `http://localhost:8585/callback`, activa *Login Kit* y *Content Posting API*, y pulsa *Conectar TikTok*. El token se renueva solo.

### Música

Coloca archivos `.mp3` libres de derechos en `assets/music/`. Se elige uno al azar por video.

---

## 5. Uso diario

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

- **YouTube:** los proyectos de API **sin auditoría** de Google solo pueden subir videos **privados**, aunque se pida «público». Hay que solicitar la auditoría de la YouTube API para publicar públicamente. Cuota por defecto: 10 000 unidades/día.
- **TikTok:** las apps sin auditoría solo publican como «Solo yo». El modo *borrador* envía el video a la bandeja de la app para terminar la publicación a mano. La API no ofrece métricas, así que TikTok no entra en el aprendizaje.
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
│   ├── visuals.py        Pixabay / Pexels / fal.ai (encadenado por fotograma)
│   ├── render.py         Montaje, subtítulos, mezcla de audio
│   ├── motion.py         Puente con Remotion (capas animadas)
│   ├── learning.py       Historial y aprendizaje de ganchos
│   ├── metrics.py        Recolección de métricas
│   └── publish/          youtube.py, tiktok.py, facebook.py
├── motion/               Animaciones Remotion: plantillas (src/templates) y render.mjs
├── app/                  Interfaz web (FastAPI + HTML/JS)
├── assets/music/         Música de fondo (tuya)
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
| «Ningún modelo gratuito de Gemini respondió» | Se agotó la cuota gratuita diaria de todos los modelos; se renueva cada día. Mientras tanto usa Claude u Ollama |
| Ollama no responde / «Iniciar run» deshabilitado con Ollama | Instala Ollama desde ollama.com, ábrelo, ejecuta `ollama pull qwen2.5:7b` y verifica con *Probar Ollama* |
