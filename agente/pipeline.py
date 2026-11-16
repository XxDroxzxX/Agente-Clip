"""Pipeline diario del Agente de Clips.

Uso:
    python -m agente.pipeline                 # run completo (publica según configuración)
    python -m agente.pipeline --publish       # fuerza publicar
    python -m agente.pipeline --no-publish    # genera sin publicar
    python -m agente.pipeline --publish-only RUN_ID
    python -m agente.pipeline --metrics-only
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback

from . import music as music_mod
from . import learning, metrics, render, research, scriptgen
from . import settings as S
from . import tts, visuals
from . import ffmpeg
from .events import Run, new_run_id
from .paths import LOCK_FILE
from .util import pid_alive, read_json, write_json


class StepFailed(Exception):
    pass


def _acquire_lock(run_id: str):
    lock = read_json(LOCK_FILE)
    if lock and pid_alive(lock.get("pid", 0)):
        print(f"[ERROR] Ya hay un proceso en curso (run {lock.get('run_id')}).", flush=True)
        sys.exit(2)
    import os
    write_json(LOCK_FILE, {"run_id": run_id, "pid": os.getpid(), "since": time.time()})


def _release_lock():
    LOCK_FILE.unlink(missing_ok=True)


def _items(pkg: scriptgen.ScriptPackage, cfg: dict):
    items = []
    if cfg["video"]["long_enabled"]:
        items.append(("long", pkg.long_video, False))
    for i, sh in enumerate(pkg.shorts, 1):
        items.append((f"short_{i}", sh, True))
    return items


def _plan_from_script(run: Run, key: str) -> scriptgen.VideoPlan:
    pkg = scriptgen.ScriptPackage.model_validate_json(run.path("script.json").read_text(encoding="utf-8"))
    if key == "long":
        return pkg.long_video
    return pkg.shorts[int(key.split("_")[1]) - 1]


# ── pasos ──────────────────────────────────────────────

def step_research(run: Run, cfg: dict) -> dict:
    run.step_start("research", "Consultando YouTube")
    try:
        data = research.research(run, cfg)
        run.path("research.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        top = [{"title": v["title"], "views_per_day": v["views_per_day"], "engagement": v["engagement"],
                "video_id": v["video_id"]} for v in data["videos"][:5]]
        run.artifact("research", top=top)
        run.step_end("research", "done", f"{len(data['videos'])} videos analizados" if data["videos"] else "Sin datos de tendencias")
        return data
    except Exception as e:
        run.warn(f"Investigación falló ({e}); se continúa solo con el nicho.", "research")
        run.step_end("research", "skipped", "Omitido por error")
        return {"niche": cfg["content"]["niche"], "videos": []}


def step_script(run: Run, cfg: dict, data: dict) -> scriptgen.ScriptPackage:
    hook, why = learning.choose_hook_style(cfg["metrics"]["exploration"])
    run.step_start("script", f"Gancho: {hook}")
    run.info(f"Estilo de gancho elegido: «{hook}» ({why}).", "script")
    try:
        pkg = scriptgen.generate(run, cfg, data, hook)
    except Exception as e:
        run.error(str(e), "script")
        run.step_end("script", "failed", str(e))
        raise StepFailed(str(e))
    run.set(title=pkg.long_video.title if cfg["video"]["long_enabled"] else pkg.shorts[0].title,
            topic=pkg.topic, hook_style=hook)
    run.artifact("script", data=pkg.model_dump(), hook_style=hook)
    run.step_end("script", "done", pkg.topic)
    return pkg


def step_voice(run: Run, cfg: dict, items) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    vc = cfg["voice"]
    engine = vc.get("engine", "edge")
    run.step_start("voice", f"Voz {vc.get('gemini_voice') if engine == 'gemini' else vc['name']}"
                            f"{' (Gemini)' if engine == 'gemini' else ''}")
    total = sum(len(p.scenes) for _, p, _ in items)
    done = 0
    audio = {}
    import threading
    lock = threading.Lock()

    def synth_all(key, plan, d, eng):
        nonlocal done
        workers = 2 if eng == "gemini" else 5  # varias escenas a la vez (Gemini gratis limita por minuto)

        def one(i_sc):
            nonlocal done
            i, sc = i_sc
            r = tts.synthesize_scene(sc.narration, vc, d, i, engine=eng, lang=cfg["content"]["language"])
            with lock:  # varias escenas terminan a la vez
                done += 1
                run.step_progress("voice", min(1.0, done / total), f"{key}: {done}/{total} escenas")
            return r

        with ThreadPoolExecutor(workers) as ex:
            return list(ex.map(one, enumerate(plan.scenes)))

    try:
        for key, plan, _ in items:
            d = run.path(key, "audio", "x").parent
            before = done
            try:
                scenes = synth_all(key, plan, d, engine)
            except Exception as e:
                if engine != "gemini":
                    raise
                # mejor una voz consistente en todo el video que mezclar dos voces
                run.warn(f"{key}: Gemini TTS falló ({e}); se usa la voz de Edge en este video.", "voice")
                done = before
                scenes = synth_all(key, plan, d, "edge")
            narration = run.path(key, "narration.wav")
            dur = tts.concat_wavs([s.wav for s in scenes], narration)
            audio[key] = scenes
            run.path(key, "audio.json").write_text(json.dumps({"scenes": [
                {"wav": run.rel(s.wav), "duration": s.duration, "words": [[w.text, w.start, w.end] for w in s.words]}
                for s in scenes]}, ensure_ascii=False), encoding="utf-8")
            run.set_item(key, duration=round(dur, 1), title=plan.title, portrait=key != "long")
            run.artifact("audio", key, narration, duration=round(dur, 1))
            run.info(f"{key}: narración de {dur:.0f} s", "voice")
    except Exception as e:
        run.error(f"Error en la narración: {e}", "voice")
        run.step_end("voice", "failed", str(e))
        raise StepFailed(str(e))
    run.step_end("voice", "done", f"{len(items)} narraciones")
    return audio


def step_visuals(run: Run, cfg: dict, items, audio) -> dict:
    v = cfg["video"]
    run.step_start("visuals", {"fal": "IA (fal.ai)", "comfyui": "IA local (ComfyUI) + stock"}.get(v["visual_provider"], "Clips de stock"))
    all_shots = {}
    n_items = len(items)
    try:
        broll = scriptgen.ScriptPackage.model_validate_json(run.path("script.json").read_text(encoding="utf-8")).broll_queries
    except Exception:
        broll = []
    try:
        for idx, (key, plan, portrait) in enumerate(items):
            W, H = render.RESOLUTIONS[(v["quality"], portrait)]
            shots = visuals.plan_shots(plan.scenes, [s.duration for s in audio[key]], getattr(plan, "visual_bible", ""))
            use_ai = v["visual_provider"] in ("fal", "comfyui") and (v["fal_scope"] == "all" or portrait)
            src_dir = run.path(key, "sources", "x").parent

            def prog(p, idx=idx):
                run.step_progress("visuals", (idx + p * 0.5) / n_items, f"{key}: buscando material")

            def log(msg, level="info"):
                run.log(msg, level, "visuals")

            visuals.fetch_for_item(shots, portrait, min(W, H), cfg, use_ai, src_dir, log, prog, broll,
                                   release=False)  # ComfyUI sigue cargado para el siguiente video
            if v.get("transitions", True):
                for j, sh in enumerate(shots):
                    prev = shots[j - 1] if j > 0 else None
                    if prev is not None and sh.scene != prev.scene and not sh.chained:  # la cadena IA ya fluye sola
                        sh.punch = 0.08 if portrait else 0.05
            if v.get("animations", True):
                _render_animations(run, key, shots, W, H, v, log, audio[key])

            shot_files = []
            for i, sh in enumerate(shots):
                out = run.path(key, "shots", f"shot_{i:03d}.mp4")
                visuals_norm(sh, W, H, out)
                if sh.overlay:  # la capa ProRes pesa mucho y ya quedó integrada en la toma
                    sh.overlay.unlink(missing_ok=True)
                thumb = ffmpeg.extract_frame(out, run.path(key, "shots", f"shot_{i:03d}.jpg"),
                                             at=sh.duration * 0.6 if sh.anim else min(1.0, sh.duration / 2),
                                             width=240)
                run.artifact("shot", key, thumb, scene=sh.scene, kind_src=sh.kind)
                shot_files.append(out)
                run.step_progress("visuals", (idx + 0.5 + 0.5 * (i + 1) / len(shots)) / n_items,
                                  f"{key}: preparando toma {i+1}/{len(shots)}")
            credits = sorted({s.credit for s in shots if s.credit})
            run.set_item(key, credits=credits, anim_shots=[i for i, s in enumerate(shots) if s.overlay or s.anim])
            all_shots[key] = shot_files
            run.path(key, "shots.json").write_text(json.dumps([run.rel(f) for f in shot_files]), encoding="utf-8")
    except Exception as e:
        run.error(f"Error preparando el material visual: {e}", "visuals")
        run.step_end("visuals", "failed", str(e))
        raise StepFailed(str(e))
    finally:
        try:
            visuals.release_ai(cfg)  # libera la GPU (cierra ComfyUI si el run lo abrió)
        except Exception:
            pass
    run.step_end("visuals", "done", f"{sum(len(x) for x in all_shots.values())} tomas")
    return all_shots


def _render_animations(run: Run, key: str, shots, W: int, H: int, v: dict, log, scene_audio) -> None:
    from . import motion
    todo = [(i, sh) for i, sh in enumerate(shots) if sh.anim and sh.anim.get("type") in motion.TYPES]
    if not todo:
        return
    fps = int(render.FPS)
    jobs = []
    for i, sh in todo:
        # inicio de la toma dentro de su escena (las tomas previas de la misma escena)
        offset = sum(s.duration for s in shots[:i] if s.scene == sh.scene)
        props = motion.overlay_props(sh.anim, W, H, sh.duration, fps, v.get("anim_color") or "#FFD633")
        props.update(motion.sync_frames(sh.anim, scene_audio[sh.scene].words, offset, fps))
        jobs.append({"out": run.path(key, "anim", f"anim_{i:03d}.mov"), "props": props})
    run.step_progress("visuals", run.state["steps"]["visuals"]["progress"], f"{key}: animando {len(jobs)} gráficos", force=True)
    log(f"{key}: renderizando {len(jobs)} animaciones con Remotion…")
    done = motion.render(jobs, run.path(key, "anim", "jobs.json"), log, lambda p: None)
    for j, (i, sh) in enumerate(todo):
        if j in done:
            sh.overlay = jobs[j]["out"]
    if done:
        log(f"{key}: {len(done)}/{len(jobs)} animaciones listas.")


def visuals_norm(shot, W, H, out):
    render.normalize_shot(shot, W, H, out)


def step_render(run: Run, cfg: dict, items, audio, shot_files) -> None:
    v = cfg["video"]
    run.step_start("render", "Uniendo tomas, voz y subtítulos")
    n = len(items)
    try:
        for idx, (key, plan, portrait) in enumerate(items):
            item_dir = run.dir / key
            W, H = render.RESOLUTIONS[(v["quality"], portrait)]
            scenes = audio[key]
            offsets, t = [], 0.0
            for s in scenes:
                offsets.append(t)
                t += s.duration
            total = t + 0.3
            subs = None
            if v["subtitles"]:
                font = render.prepare_font(item_dir / "fonts")
                subs = item_dir / "subs.ass"
                render.write_ass([s.words for s in scenes], offsets, W, H, portrait, font, subs)
            music = None
            if v["music"]:
                try:
                    music = music_mod.for_item(cfg, getattr(plan, "music", None), total, item_dir, f"{run.id}/{key}",
                                               lambda m, lvl="info": run.log(f"{key}: {m}", lvl, "render"))
                except Exception as e:  # la música nunca debe tumbar el montaje
                    run.warn(f"{key}: no se pudo preparar la música ({e}); el video sale sin música.", "render")
            fx = None
            if v.get("sfx", True):
                try:
                    from . import sfx
                    fx = sfx.build_track(sfx.events_for(plan, offsets, portrait), total, item_dir / "sfx.wav")
                except Exception as e:
                    run.warn(f"{key}: efectos de sonido omitidos ({e}).", "render")
            out = item_dir / "final.mp4"
            run.step_progress("render", idx / n, f"{key}: codificando", force=True)
            render.assemble(item_dir, shot_files[key], item_dir / "narration.wav", total, subs, music,
                            float(v["music_volume"]), out,
                            lambda p, idx=idx, key=key: run.step_progress("render", (idx + p) / n, f"{key}: codificando {p*100:.0f}%"),
                            sfx=fx)
            thumb = ffmpeg.extract_frame(out, item_dir / "thumb.jpg", at=min(1.5, total / 3), width=480)
            run.artifact("thumb", key, thumb)
            size_mb = out.stat().st_size / 1e6
            run.artifact("video", key, out, duration=round(total, 1), size_mb=round(size_mb, 1),
                         title=plan.title, portrait=portrait)
            run.info(f"{key}: video listo ({total:.0f} s, {size_mb:.1f} MB)", "render")
            if key == "long" and v.get("thumbnail", True):
                run.step_progress("render", (idx + 0.95) / n, f"{key}: diseñando la miniatura", force=True)
                try:
                    from . import thumbnail
                    th = thumbnail.make(cfg, item_dir, plan, shot_files[key],
                                        set(run.state["items"].get(key, {}).get("anim_shots", [])),
                                        lambda m, lvl="info": run.log(m, lvl, "render"))
                    if th:
                        run.set_item(key, thumbnail=run.rel(th))
                        run.artifact("thumbnail", key, th)
                        run.info(f"{key}: miniatura lista para YouTube.", "render")
                except Exception as e:
                    run.warn(f"{key}: no se pudo crear la miniatura ({e}).", "render")
            _review(run, cfg, key, out, plan, total, portrait, idx, n)
    except Exception as e:
        run.error(f"Error en el montaje: {e}", "render")
        run.step_end("render", "failed", str(e))
        raise StepFailed(str(e))
    run.step_end("render", "done", f"{n} videos")


def _review(run: Run, cfg: dict, key: str, video, plan, total: float, portrait: bool, idx: int, n: int) -> None:
    """Control de calidad con IA; nunca detiene el montaje."""
    from . import review
    if not review.provider(cfg):
        return
    run.step_progress("render", (idx + 0.97) / n, f"{key}: revisión de calidad con IA", force=True)
    try:
        res = review.review_video(cfg, video, plan, total, portrait, lambda m, lvl="info": run.log(m, lvl, "render"))
    except Exception as e:
        run.warn(f"{key}: no se pudo hacer la revisión con IA ({str(e)[:200]}).", "render")
        return
    if not res:
        return
    run.set_item(key, review=res)
    run.artifact("review", key, data=res)
    high = [i for i in res["issues"] if i["severity"] == "alta"]
    if res["ok"]:
        run.info(f"{key}: revisión IA {res['score']}/10 — {res['summary']}", "render")
    else:
        run.warn(f"{key}: revisión IA {res['score']}/10, NO aprobado — {res['summary']}", "render")
    for i in high[:5]:
        run.warn(f"{key} [{i['at']}]: {i['problem']}", "render")


def step_publish(run: Run, cfg: dict, respect_review: bool = False) -> None:
    from .publish import browser, facebook, instagram, tiktok, youtube

    p = cfg["publish"]
    run.step_start("publish", "Subiendo a las plataformas")
    items = [k for k in run.state.get("items", {}) if (run.dir / k / "final.mp4").is_file()]
    if respect_review and cfg["video"].get("review_block", True):
        blocked = [k for k in items if (run.state["items"][k].get("review") or {}).get("ok") is False]
        for k in blocked:
            run.warn(f"{k} no se publica automáticamente: la revisión con IA lo reprobó. Revísalo y publícalo a mano si está bien.", "publish")
        items = [k for k in items if k not in blocked]
    targets = []
    for key in items:
        is_short = key != "long"
        if p["youtube"]:
            targets.append((key, "youtube"))
        if p["tiktok"] and is_short:
            targets.append((key, "tiktok"))
        if p["facebook"]:
            targets.append((key, "facebook"))
        if p.get("instagram") and is_short:
            targets.append((key, "instagram"))
    if not targets:
        run.step_end("publish", "skipped", "No hay plataformas activas")
        return
    done_keys = {(u["item"], u["platform"]) for u in run.state.get("uploads", []) if u.get("platform_id")}
    hook = run.state.get("hook_style")
    ok, failed, history = 0, 0, []
    for n, (key, platform) in enumerate(targets):
        if (key, platform) in done_keys:
            run.info(f"{key} ya estaba publicado en {platform}; se omite.", "publish")
            continue
        plan = _plan_from_script(run, key)
        video = run.dir / key / "final.mp4"
        credits = run.state["items"].get(key, {}).get("credits", [])
        tags = " ".join(plan.hashtags)
        desc = f"{plan.description}\n\n{tags}"
        if credits:
            desc += "\n\nMaterial visual: " + "; ".join(credits[:6])
        base = n / len(targets)

        def prog(x, base=base):
            run.step_progress("publish", base + x / len(targets), f"{platform}: {key} {x*100:.0f}%")

        run.step_progress("publish", base, f"{platform}: subiendo {key}", force=True)
        try:
            visible = bool(p.get("browser_visible"))
            if platform == "youtube" and p.get("youtube_method", "browser") == "browser":
                thumb = run.dir / key / "thumbnail.jpg"
                res = browser.upload_youtube(video, plan.title, desc, plan.hashtags, p["youtube_privacy"], key != "long",
                                             prog, thumbnail=thumb if thumb.is_file() else None, visible=visible)
            elif platform == "youtube":
                thumb = run.dir / key / "thumbnail.jpg"
                res = youtube.upload(video, plan.title, desc, plan.hashtags, p["youtube_privacy"],
                                     p["youtube_category"], cfg["content"]["language"], key != "long", prog,
                                     thumbnail=thumb if thumb.is_file() else None)
            elif platform == "tiktok" and p.get("tiktok_method", "browser") == "browser":
                res = browser.upload_tiktok(video, f"{plan.title} {tags}", p["tiktok_privacy"], prog, visible=visible)
            elif platform == "tiktok":
                res = tiktok.upload(video, f"{plan.title} {tags}", p["tiktok_mode"], p["tiktok_privacy"], prog)
            elif platform == "instagram":
                res = instagram.upload_reel(video, f"{plan.title}\n\n{plan.description}\n\n{tags}",
                                            p["facebook_graph_version"], prog)
            else:
                if key == "long":
                    res = facebook.upload_video(video, plan.title, desc, p["facebook_graph_version"], prog)
                else:
                    res = facebook.upload_reel(video, f"{plan.title}\n\n{tags}", p["facebook_graph_version"], prog)
            rec = {"item": key, "platform": platform, "title": plan.title, **res}
            run.add_upload(rec)
            item = run.state["items"].get(key, {})
            history.append({"run_id": run.id, "item": key, "platform": platform, "platform_id": res["platform_id"],
                            "title": plan.title, "hook_style": hook, "published_at": time.time(), "url": res.get("url", ""),
                            # rasgos del video: el aprendizaje mide cuáles rinden mejor
                            "music_mood": plan.music.mood if getattr(plan, "music", None) else None,
                            "duration": item.get("duration"),
                            "animations": sum(1 for sc in plan.scenes if getattr(sc, "animation", None)),
                            "voice_engine": cfg["voice"].get("engine", "edge"),
                            "format": "short" if key != "long" else "long"})
            run.info(f"{platform}: {key} publicado {res.get('url') or res['platform_id']}", "publish")
            if res.get("note"):
                run.warn(res["note"], "publish")
            ok += 1
        except Exception as e:
            failed += 1
            run.add_upload({"item": key, "platform": platform, "title": plan.title, "platform_id": None, "error": str(e)})
            run.error(f"{platform}: {key} falló — {e}", "publish")
    if history:
        learning.add_history(history)
    # con algún error el paso queda en rojo: el botón «Publicar» reintenta solo lo que falló
    run.step_end("publish", "done" if failed == 0 else "failed", f"{ok} publicados, {failed} con error")


def step_metrics(run: Run, cfg: dict) -> None:
    run.step_start("metrics", "Consultando métricas")
    try:
        res = metrics.collect(run, cfg)
        run.artifact("learning", data=res)
        run.step_end("metrics", "done", f"{res.get('samples', 0)} publicaciones con métricas maduras")
    except Exception as e:
        run.warn(f"Métricas: {e}", "metrics")
        run.step_end("metrics", "skipped", "Omitido por error")


# ── modos ──────────────────────────────────────────────

def full_run(run_id: str, publish: bool) -> int:
    cfg = S.load()
    run = Run(run_id, options={"publish": publish})
    run.info(f"Run {run_id} iniciado — nicho «{cfg['content']['niche']}»")
    try:
        from . import cleanup
        res = cleanup.run(cfg)
        if res["freed_gb"] >= 0.05:
            run.info(f"Limpieza automática: se liberaron {res['freed_gb']:.1f} GB de archivos de trabajo antiguos.")
    except Exception as e:
        run.warn(f"Limpieza automática omitida ({e}).")
    try:
        data = step_research(run, cfg)
        pkg = step_script(run, cfg, data)
        items = _items(pkg, cfg)
        run.set(item_keys=[k for k, _, _ in items])
        audio = step_voice(run, cfg, items)
        shots = step_visuals(run, cfg, items, audio)
        step_render(run, cfg, items, audio, shots)
        if publish:
            step_publish(run, cfg, respect_review=True)
        else:
            run.step_end("publish", "skipped", "Revisa los videos y publica desde la interfaz")
        step_metrics(run, cfg)
        run.finish("done")
        run.info("Run completado.")
        return 0
    except StepFailed as e:
        _skip_pending(run)
        run.finish("failed", str(e))
        return 1
    except Exception as e:
        run.error(f"Error inesperado: {e}\n{traceback.format_exc()}")
        _skip_pending(run)
        run.finish("failed", str(e))
        return 1


def _load_audio(run: Run, items) -> dict | None:
    out = {}
    for key, _, _ in items:
        f = run.dir / key / "audio.json"
        if not f.is_file():
            return None
        scenes = []
        for s in json.loads(f.read_text(encoding="utf-8"))["scenes"]:
            wav = run.dir / s["wav"]
            if not wav.is_file():
                return None
            scenes.append(tts.SceneAudio(wav=wav, duration=s["duration"], words=[tts.Word(*w) for w in s["words"]]))
        if not (run.dir / key / "narration.wav").is_file():
            return None
        out[key] = scenes
    return out


def _load_shots(run: Run, items) -> dict | None:
    out = {}
    for key, _, _ in items:
        f = run.dir / key / "shots.json"
        if not f.is_file():
            return None
        files = [run.dir / p for p in json.loads(f.read_text(encoding="utf-8"))]
        if not files or not all(p.is_file() for p in files):
            return None
        out[key] = files
    return out


def resume(run_id: str) -> int:
    """Retoma un run fallido o cancelado reutilizando lo que ya quedó listo (guion, voces, tomas, videos)."""
    cfg = S.load()
    run = Run(run_id, create=False)
    steps = run.state["steps"]
    for sid, s in steps.items():  # lo que no terminó vuelve a quedar pendiente
        if s["status"] in ("failed", "cancelled", "running") or (s["status"] == "skipped" and sid in ("publish", "metrics")):
            s.update(status="pending", progress=0.0, message="", started=None, finished=None)
    run.set()
    publish = bool(run.state.get("options", {}).get("publish"))
    run.info("Reintentando: se reutiliza todo lo que ya estaba listo.")
    try:
        script_file = run.dir / "script.json"
        if steps["script"]["status"] == "done" and script_file.is_file():
            pkg = scriptgen.ScriptPackage.model_validate_json(script_file.read_text(encoding="utf-8"))
            run.info("Guion: se reutiliza el ya generado.", "script")
        else:
            rf = run.dir / "research.json"
            data = json.loads(rf.read_text(encoding="utf-8")) if rf.is_file() else step_research(run, cfg)
            pkg = step_script(run, cfg, data)
        keys = run.state.get("item_keys") or [k for k, _, _ in _items(pkg, cfg)]
        items = [(k, pkg.long_video if k == "long" else pkg.shorts[int(k.split("_")[1]) - 1], k != "long") for k in keys]
        run.set(item_keys=keys)

        audio = _load_audio(run, items) if steps["voice"]["status"] == "done" else None
        if audio is None:
            audio = step_voice(run, cfg, items)
        else:
            run.info("Narración: se reutilizan las voces ya generadas.", "voice")
        shots = _load_shots(run, items) if steps["visuals"]["status"] == "done" else None
        if shots is None:
            shots = step_visuals(run, cfg, items, audio)
        else:
            run.info("Material visual: se reutilizan las tomas ya preparadas.", "visuals")
        if steps["render"]["status"] != "done" or not all((run.dir / k / "final.mp4").is_file() for k in keys):
            step_render(run, cfg, items, audio, shots)
        if publish:
            step_publish(run, cfg, respect_review=True)
        else:
            run.step_end("publish", "skipped", "Revisa los videos y publica desde la interfaz")
        step_metrics(run, cfg)
        run.finish("done")
        run.info("Run completado.")
        return 0
    except StepFailed as e:
        _skip_pending(run)
        run.finish("failed", str(e))
        return 1
    except Exception as e:
        run.error(f"Error inesperado: {e}\n{traceback.format_exc()}")
        _skip_pending(run)
        run.finish("failed", str(e))
        return 1


def _skip_pending(run: Run):
    for sid, s in run.state["steps"].items():
        if s["status"] == "pending":
            s["status"] = "skipped"
    run.set()


def publish_only(run_id: str) -> int:
    cfg = S.load()
    run = Run(run_id, create=False)
    run.info("Publicación manual iniciada.")
    try:
        step_publish(run, cfg)
        run.finish("done")
        return 0
    except Exception as e:
        run.error(f"Error al publicar: {e}")
        run.finish("failed", str(e))
        return 1


def metrics_only(run_id: str) -> int:
    cfg = S.load()
    run = Run(run_id, options={"mode": "metrics"})
    for sid in list(run.state["steps"]):
        if sid != "metrics":
            run.state["steps"][sid]["status"] = "skipped"
    run.set(title="Actualización de métricas")
    step_metrics(run, cfg)
    run.finish("done")
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # un emoji en un título nunca debe tumbar un paso
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Agente de Clips")
    ap.add_argument("--run-id")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--publish", action="store_true")
    g.add_argument("--no-publish", action="store_true")
    g.add_argument("--publish-only", metavar="RUN_ID")
    g.add_argument("--metrics-only", action="store_true")
    g.add_argument("--resume", metavar="RUN_ID", help="retoma un run fallido desde el paso que falló")
    a = ap.parse_args(argv)

    run_id = a.publish_only or a.resume or a.run_id or new_run_id()
    _acquire_lock(run_id)
    try:
        if a.publish_only:
            return publish_only(run_id)
        if a.metrics_only:
            return metrics_only(run_id)
        if a.resume:
            return _notify(run_id, resume(run_id))
        publish = True if a.publish else False if a.no_publish else S.load()["publish"]["auto_publish"]
        return _notify(run_id, full_run(run_id, publish))
    finally:
        _release_lock()


def _notify(run_id: str, code: int) -> int:
    try:
        if S.load().get("general", {}).get("notify", True):
            from . import notify
            notify.run_finished(read_json(Run(run_id, create=False).dir / "run.json") or {})
    except Exception:
        pass
    return code


if __name__ == "__main__":
    sys.exit(main())
