"""Listas cerradas de la configuración: la interfaz las muestra como opciones y settings.validate las usa para
rechazar valores que harían fallar un run (región inexistente, voz de otro idioma, números fuera de rango…)."""
from __future__ import annotations

LANGUAGES = {"es": "Español", "en": "Inglés", "pt": "Portugués"}

COUNTRIES = {  # ISO 3166-1 → nombre en español (regiones de YouTube y países de las voces)
    "AR": "Argentina", "AU": "Australia", "BO": "Bolivia", "BR": "Brasil", "CA": "Canadá", "CL": "Chile",
    "CO": "Colombia", "CR": "Costa Rica", "CU": "Cuba", "DO": "República Dominicana", "EC": "Ecuador",
    "ES": "España", "GB": "Reino Unido", "GQ": "Guinea Ecuatorial", "GT": "Guatemala", "HK": "Hong Kong",
    "HN": "Honduras", "IE": "Irlanda", "IN": "India", "KE": "Kenia", "MX": "México", "NG": "Nigeria",
    "NI": "Nicaragua", "NZ": "Nueva Zelanda", "PA": "Panamá", "PE": "Perú", "PH": "Filipinas", "PR": "Puerto Rico",
    "PT": "Portugal", "PY": "Paraguay", "SG": "Singapur", "SV": "El Salvador", "TZ": "Tanzania",
    "US": "Estados Unidos", "UY": "Uruguay", "VE": "Venezuela", "ZA": "Sudáfrica",
}

# Regiones de tendencias de YouTube: países hispanohablantes primero, luego el resto
_HISPANIC = ["MX", "CO", "AR", "ES", "CL", "PE", "VE", "EC", "GT", "CU", "BO", "DO", "HN", "PY", "SV", "NI", "CR",
             "PA", "PR", "UY"]
REGIONS = [("", "Global (todos los países)")] + \
          [(c, COUNTRIES[c]) for c in sorted(_HISPANIC, key=lambda c: COUNTRIES[c])] + \
          [(c, COUNTRIES[c]) for c in sorted(set(COUNTRIES) - set(_HISPANIC) - {"GQ"}, key=lambda c: COUNTRIES[c])]

ALPHA3 = {"USA": "US", "MEX": "MX", "COL": "CO", "ARG": "AR", "ESP": "ES", "CHL": "CL", "PER": "PE", "VEN": "VE",
          "ECU": "EC", "GTM": "GT", "BOL": "BO", "DOM": "DO", "URY": "UY", "PRY": "PY", "BRA": "BR", "PRT": "PT",
          "GBR": "GB", "CAN": "CA", "UK": "GB"}  # códigos que la gente suele escribir → el de 2 letras que pide YouTube

DEFAULT_VOICE = {"es": "es-MX-JorgeNeural", "en": "en-US-AndrewNeural", "pt": "pt-BR-AntonioNeural"}

# Estilo visual para el video IA (se agrega en inglés a cada prompt)
VISUAL_STYLES = [
    ("", "Ninguno (realista, según cada escena)"),
    ("cinematic, film grain, shallow depth of field, dramatic lighting", "Cinematográfico"),
    ("photorealistic, sharp details, natural colors, high detail", "Fotorrealista"),
    ("documentary footage, natural light, handheld camera", "Documental"),
    ("dark horror atmosphere, low-key lighting, desaturated colors, eerie fog", "Terror / oscuro"),
    ("found footage, security camera look, grainy night vision", "Cámara de seguridad / metraje encontrado"),
    ("anime style, studio quality, vibrant colors, clean line art", "Anime"),
    ("3D animated film style, soft lighting, colorful, expressive characters", "Animación 3D"),
    ("vintage 1980s VHS look, retro colors, analog film noise", "Retro VHS"),
    ("watercolor illustration style, soft pastel colors", "Acuarela"),
]

# Estilo de lectura de Gemini TTS (instrucción en el idioma del guion)
READING_STYLES = [
    ("cercano y con energía, como un creador de contenido latino, ritmo ágil", "Creador de contenido (cercano y enérgico)"),
    ("narrador de misterio, voz grave y pausada, que crea suspenso", "Misterio / terror (grave y pausado)"),
    ("tranquilo y cálido, como un documental de naturaleza", "Documental (sereno y cálido)"),
    ("didáctico y claro, como un profesor amable", "Educativo (claro y amable)"),
    ("entusiasta y rápido, como un anuncio emocionante", "Promocional (entusiasta)"),
    ("tono neutro y profesional, como un presentador de noticias", "Noticias (neutro y profesional)"),
]

# Voces de Gemini TTS: carácter según la documentación de Google
GEMINI_VOICE_INFO = {
    "Puck": "animada", "Kore": "firme", "Charon": "informativa", "Fenrir": "enérgica", "Aoede": "ligera",
    "Leda": "juvenil", "Orus": "firme", "Zephyr": "brillante", "Enceladus": "susurrante", "Iapetus": "clara",
    "Umbriel": "relajada", "Algieba": "suave", "Despina": "suave", "Erinome": "clara", "Achird": "amigable",
    "Sadachbia": "vivaz", "Sulafat": "cálida",
}

GRAPH_VERSIONS = ["v24.0"]  # recomendada; se acepta otra con el formato vNN.0


def voice_label(short_name: str) -> str:
    """«es-MX-JorgeNeural» → «Jorge»."""
    parts = short_name.split("-")
    name = parts[-1] if len(parts) >= 3 else short_name
    for suffix in ("MultilingualNeural", "Neural"):
        if name.endswith(suffix):
            name = name[: -len(suffix)] + (" (multilingüe)" if suffix.startswith("Multi") else "")
    return name


def locale_label(locale: str) -> str:
    """«es-MX» → «México»."""
    cc = locale.split("-")[-1].upper()
    return COUNTRIES.get(cc, cc)


def for_ui() -> dict:
    return {"languages": list(LANGUAGES.items()), "regions": REGIONS, "visual_styles": VISUAL_STYLES,
            "reading_styles": READING_STYLES, "gemini_voice_info": GEMINI_VOICE_INFO, "graph_versions": GRAPH_VERSIONS,
            "default_voice": DEFAULT_VOICE}
