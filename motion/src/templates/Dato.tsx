import React from "react";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT, OverlayProps, safeArea, textShadow } from "../theme";
import { Safe, Scrim, useLayerOpacity } from "./common";

/** Separa "73%" en prefijo, número y sufijo para animar el conteo. */
function parseValue(v: string) {
  const m = v.trim().match(/^(.*?)(\d+(?:[.,]\d+)?)(.*)$/);
  if (!m) return null;
  const decSep = m[2].includes(",") ? "," : ".";
  const decimals = (m[2].split(/[.,]/)[1] || "").length;
  return { prefix: m[1], num: parseFloat(m[2].replace(",", ".")), suffix: m[3], decimals, decSep };
}

/** Cifra destacada: el número cuenta desde 0; si es porcentaje, un anillo se llena a la par. */
export const Dato: React.FC<OverlayProps> = ({ value, label, accent, valueFrame }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  // la cifra arranca cuando la voz la dice (o casi al inicio si no se encontró)
  const start = valueFrame !== undefined && valueFrame >= 0 ? Math.min(valueFrame, durationInFrames - 45) : 4;
  const s = safeArea(width, height);
  const u = s.unit;
  const parsed = parseValue(value);
  const p = interpolate(frame, [start, start + fps * 1.1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const pop = spring({ frame: frame - start + 2, fps, config: { damping: 10, stiffness: 140 } });
  const labelIn = spring({ frame: frame - start - fps * 0.9, fps, config: { damping: 16 } });
  const isPct = parsed !== null && parsed.suffix.trim().startsWith("%") && parsed.num <= 100;

  let shown = value;
  if (parsed) {
    const n = (parsed.num * p).toFixed(parsed.decimals).replace(".", parsed.decSep);
    shown = `${parsed.prefix}${n}${parsed.suffix}`;
  }
  const big = (s.portrait ? 24 : 20) * u * (shown.length > 5 ? 5 / shown.length : 1);
  const ring = (s.portrait ? 62 : 46) * u;
  const stroke = ring * 0.07;
  const r = (ring - stroke) / 2;
  const circ = 2 * Math.PI * r;

  return (
    <AbsoluteFill style={{ opacity: useLayerOpacity() }}>
      <Scrim strength={0.6} />
      <Safe>
        <div
          style={{
            position: "relative",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: isPct ? ring : "auto",
            height: isPct ? ring : "auto",
            flex: "none",
          }}
        >
          {isPct && (
            <svg width={ring} height={ring} style={{ position: "absolute", inset: 0, opacity: Math.min(1, pop * 1.5), transform: `rotate(-90deg) scale(${pop})` }}>
              <circle cx={ring / 2} cy={ring / 2} r={r} stroke="rgba(255,255,255,.18)" strokeWidth={stroke} fill="rgba(10,10,18,.35)" />
              <circle
                cx={ring / 2}
                cy={ring / 2}
                r={r}
                stroke={accent}
                strokeWidth={stroke}
                fill="none"
                strokeLinecap="round"
                strokeDasharray={circ}
                strokeDashoffset={circ * (1 - (parsed!.num / 100) * p)}
              />
            </svg>
          )}
          <div
            style={{
              fontFamily: FONT,
              fontSize: big,
              color: isPct ? "#fff" : accent,
              textShadow: textShadow(u * 1.2),
              transform: `scale(${0.5 + 0.5 * pop})`,
              opacity: Math.min(1, pop * 1.5),
              fontVariantNumeric: "tabular-nums",
              lineHeight: 1,
              padding: isPct ? 0 : `${u * 2}px 0`,
              whiteSpace: "nowrap",
            }}
          >
            {shown}
          </div>
        </div>
        {label && (
          <div
            style={{
              marginTop: isPct ? u * 3 : u * 1.5,
              fontFamily: FONT,
              fontSize: (s.portrait ? 6 : 5) * u,
              color: "#fff",
              textAlign: "center",
              textTransform: "uppercase",
              textShadow: textShadow(u * 0.7),
              opacity: labelIn,
              transform: `translateY(${(1 - labelIn) * u * 4}px)`,
              maxWidth: "100%",
            }}
          >
            {label}
          </div>
        )}
      </Safe>
    </AbsoluteFill>
  );
};
