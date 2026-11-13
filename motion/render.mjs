// Renderiza en lote las capas animadas de un run.
//   node render.mjs <jobs.json>
// jobs.json: [{ "out": "C:/.../overlay_003.mov", "props": { ...OverlayProps } }, ...]
// Escribe una línea JSON por evento en stdout: log | progress | done | error.
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { renderMedia, renderStill, selectComposition } from "@remotion/renderer";

const here = path.dirname(fileURLToPath(import.meta.url));
const emit = (o) => process.stdout.write(JSON.stringify(o) + "\n");

function srcHash() {
  const h = createHash("sha1");
  const walk = (d) => {
    for (const f of readdirSync(d).sort()) {
      const p = path.join(d, f);
      if (statSync(p).isDirectory()) walk(p);
      else h.update(f).update(readFileSync(p));
    }
  };
  walk(path.join(here, "src"));
  h.update(readFileSync(path.join(here, "package.json")));
  return h.digest("hex").slice(0, 12);
}

async function getBundle() {
  const outDir = path.join(here, ".bundle", srcHash());
  if (existsSync(path.join(outDir, "index.html"))) return outDir;
  emit({ type: "log", msg: "Preparando plantillas de animación (solo cuando cambian)…" });
  return bundle({ entryPoint: path.join(here, "src", "index.ts"), outDir, enableCaching: true });
}

const jobs = JSON.parse(readFileSync(process.argv[2], "utf8"));
const concurrency = Math.max(1, Math.min(8, Math.floor(os.cpus().length / 2)));

try {
  const serveUrl = await getBundle();
  for (let i = 0; i < jobs.length; i++) {
    const { out, props, composition: compId = "Overlay", still = false } = jobs[i];
    try {
      const composition = await selectComposition({ serveUrl, id: compId, inputProps: props });
      if (still) {
        await renderStill({ composition, serveUrl, inputProps: props, output: out, imageFormat: "jpeg", jpegQuality: 92 });
        emit({ type: "done", job: i, out });
        continue;
      }
      await renderMedia({
        composition,
        serveUrl,
        inputProps: props,
        outputLocation: out,
        codec: "prores",
        proResProfile: "4444",
        imageFormat: "png",
        pixelFormat: "yuva444p10le",
        muted: true,
        concurrency,
        onProgress: ({ progress }) => emit({ type: "progress", job: i, progress }),
      });
      emit({ type: "done", job: i, out });
    } catch (e) {
      emit({ type: "error", job: i, msg: String(e?.message || e).slice(0, 400) });
    }
  }
} catch (e) {
  emit({ type: "fatal", msg: String(e?.message || e).slice(0, 400) });
  process.exit(1);
}
