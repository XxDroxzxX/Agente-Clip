#!/usr/bin/env python
"""Orchestrator for the daily IA video workflow.
It sequentially runs the steps:
1. fetch_videos.py – gathers top videos of the configured niche.
2. analyse.py – statistical analysis and selects the winning strategy.
3. generate_script.py – creates a video script using a local LLM.
4. make_video.py – renders images with Stable Diffusion, synthesizes speech, and builds the final MP4.
5. upload.py – uploads the full video to YouTube, TikTok and Facebook.
6. clips.py – extracts high‑engagement short clips and uploads them.
7. metrics_loop.py – pulls analytics and updates the learning model.

Each module writes its intermediate results to the `data/` folder as CSV/JSON so the next step can consume them.

The script expects a `config.yaml` file in the project root (see the template in the repo).
"""

import subprocess
import sys
import yaml
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

def run_module(module_path: Path):
    """Run a Python module located under `scripts/` and forward stdout/stderr.
    Returns the exit code.
    """
    result = subprocess.run([sys.executable, str(module_path)], cwd=PROJECT_ROOT)
    return result.returncode

def main():
    # Load config (just to ensure it exists)
    cfg_path = PROJECT_ROOT / "config.yaml"
    if not cfg_path.is_file():
        print("[ERROR] config.yaml not found – copy config.yaml.example and fill the values.")
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    steps = [
        "scripts/fetch_videos.py",
        "scripts/analyse.py",
        "scripts/generate_script.py",
        "scripts/make_video.py",
        "scripts/upload.py",
        "scripts/clips.py",
        "scripts/metrics_loop.py",
    ]

    for step in steps:
        print(f"[INFO] Running {step} …")
        rc = run_module(PROJECT_ROOT / step)
        if rc != 0:
            print(f"[ERROR] Step {step} failed with code {rc}. Stopping pipeline.")
            sys.exit(rc)
    print("[INFO] Daily workflow completed successfully.")

if __name__ == "__main__":
    main()
