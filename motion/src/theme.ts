// Tokens visuales compartidos por todas las plantillas.
// Las animaciones se renderizan con fondo TRANSPARENTE y se superponen a la toma
// en ffmpeg, así que deben dejar libre la zona inferior donde van los subtítulos.

export type AnimType = "titulo" | "lista" | "dato" | "frase" | "cta";

export type OverlayProps = {
  type: AnimType;
  width: number;
  height: number;
  durationInFrames: number;
  fps: number;
  accent: string; // color de resaltado (por defecto el mismo amarillo de los subtítulos)
  headline: string;
  highlight: string;
  items: string[];
  value: string;
  label: string;
  wordFrames?: number[]; // cuadro en que la voz dice cada palabra de headline
  itemFrames?: number[]; // ídem para cada elemento de la lista
  valueFrame?: number; // ídem para la cifra
};

export const defaultProps: OverlayProps = {
  type: "titulo",
  width: 1080,
  height: 1920,
  durationInFrames: 150,
  fps: 30,
  accent: "#FFD633",
  headline: "El error que arruina tus lentejas",
  highlight: "arruina",
  items: ["Remojo de 4 horas", "Sal al final", "Fuego medio"],
  value: "73%",
  label: "de la gente lo hace mal",
};

export const FONT = '"Segoe UI Black", "Arial Black", "Segoe UI", system-ui, sans-serif';
export const INK = "#0d0d14";

/** Zona segura (en px) donde puede ir texto sin tapar los subtítulos ni la interfaz de la app. */
export function safeArea(width: number, height: number) {
  const portrait = height > width;
  return portrait
    ? { top: height * 0.13, bottom: height * 0.38, side: width * 0.07, unit: width / 100, portrait }
    : { top: height * 0.1, bottom: height * 0.26, side: width * 0.08, unit: height / 100, portrait };
}

/** Sombra/contorno para que el texto se lea sobre cualquier video. */
export const textShadow = (u: number) =>
  `0 ${u * 0.35}px ${u * 1.2}px rgba(0,0,0,.55), 0 0 ${u * 0.25}px rgba(0,0,0,.8)`;

export const isHighlighted = (word: string, highlight: string) => {
  const clean = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}%]/gu, "");
  const h = highlight.split(/\s+/).map(clean).filter(Boolean);
  return h.length > 0 && h.includes(clean(word));
};

/** Cuadro de entrada de cada elemento. `frames` viene de Python (sincronizado con la voz; -1 = sin dato).
 * Los elementos sin dato se reparten alrededor de los que sí lo tienen; sin ningún dato se usa start + i·step. */
export function timeline(frames: number[] | undefined, n: number, start: number, step: number, max: number): number[] {
  const f = Array.from({ length: n }, (_, i) => (frames && frames[i] !== undefined ? frames[i] : -1));
  const first = f.findIndex((x) => x >= 0);
  const out: number[] = [];
  let prev = -Infinity;
  for (let i = 0; i < n; i++) {
    let t: number;
    if (f[i] >= 0) t = f[i];
    else if (first < 0) t = start + i * step;
    else if (i < first) t = Math.max(0, f[first] - (first - i) * Math.min(step, 3));
    else t = prev + step;
    t = Math.min(Math.max(t, prev), max);
    out.push(t);
    prev = t;
  }
  return out;
}
