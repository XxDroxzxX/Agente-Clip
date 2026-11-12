"""make_video.py – Renderiza el video final usando Stable Diffusion y TTS.
Salida: data/final_video.mp4
"""
import os, sys
from pathlib import Path
import yaml, json
import subprocess
from diffusers import StableDiffusionPipeline
import torch
from TTS.api import TTS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

def load_config():
    cfg_path = PROJECT_ROOT / "config.yaml"
    if not cfg_path.is_file():
        print("[ERROR] config.yaml not found")
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_script():
    script_path = DATA_DIR / "script.txt"
    if not script_path.is_file():
        print("[ERROR] script.txt not found – run generate_script first.")
        sys.exit(1)
    return script_path.read_text(encoding="utf-8")

def generate_image(prompt, output_path, model_name="runwayml/stable-diffusion-v1-5"):
    pipe = StableDiffusionPipeline.from_pretrained(model_name, torch_dtype=torch.float16)
    pipe = pipe.to("cuda" if torch.cuda.is_available() else "cpu")
    image = pipe(prompt).images[0]
    image.save(output_path)

def synthesize_speech(text, output_path, tts_model="tts_models/es/css10/vits"):
    tts = TTS(tts_model)
    tts.tts_to_file(text=text, file_path=str(output_path))

def build_video(image_path, audio_path, video_path, fps=1):
    # Use ffmpeg to create a video from a single image (loop) and add audio
    cmd = [
        "ffmpeg",
        "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(video_path),
    ]
    subprocess.run(cmd, check=True)

def main():
    cfg = load_config()
    script = load_script()
    # Simplify: use first sentence as SD prompt, whole script as TTS.
    sd_prompt = script.split("\n")[0][:200]
    image_path = DATA_DIR / "cover.png"
    audio_path = DATA_DIR / "narration.wav"
    video_path = DATA_DIR / "final_video.mp4"

    print("[INFO] Generating cover image with Stable Diffusion …")
    generate_image(sd_prompt, image_path)

    print("[INFO] Synthesizing voice with Coqui TTS …")
    synthesize_speech(script, audio_path)

    print("[INFO] Building final MP4 …")
    build_video(image_path, audio_path, video_path)

    print(f"[INFO] Video saved to {video_path}")

if __name__ == "__main__":
    main()
