"""Rutas del proyecto."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"
CACHE_DIR = DATA_DIR / "cache"
ASSETS_DIR = ROOT / "assets"
MUSIC_DIR = ASSETS_DIR / "music"

SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.json"        # publicaciones realizadas
METRICS_FILE = DATA_DIR / "metrics.jsonl"       # snapshots de métricas
LEARNING_FILE = DATA_DIR / "learning.json"      # estado del aprendizaje
LOCK_FILE = RUNS_DIR / ".active"                # run en curso

for d in (DATA_DIR, RUNS_DIR, CACHE_DIR, MUSIC_DIR):
    d.mkdir(parents=True, exist_ok=True)
