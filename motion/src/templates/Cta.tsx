import React from "react";
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT, INK, OverlayProps, safeArea, textShadow } from "../theme";
import { Safe, Scrim, useLayerOpacity } from "./common";

/** Cierre: llamada a la acción con un botón genérico que late y ondas expansivas. */
export const Cta: React.FC<OverlayProps> = ({ headline, label, accent }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const s = safeArea(width, height);
  const u = s.unit;
  const inT = spring({ frame: frame - 2, fps, config: { damping: 12, stiffness: 150 } });
  const btnT = spring({ frame: frame - 12, fps, config: { damping: 9, stiffness: 170 } });
  const beat = 1 + 0.045 * Math.max(0, Math.sin(((frame - 20) / fps) * Math.PI * 2.2)) * (frame > 20 ? 1 : 0);
  const size = (s.portrait ? 8.2 : 7) * u;
  const btn = label || "Sígueme";

  return (
    <AbsoluteFill style={{ opacity: useLayerOpacity() }}>
      <Scrim strength={0.5} />
      <Safe>
        <div
          style={{
            fontFamily: FONT,
            fontSize: size,
            lineHeight: 1.08,
            color: "#fff",
            textAlign: "center",
            textTransform: "uppercase",
            textShadow: textShadow(u),
            transform: `translateY(${(1 - inT) * u * 10}px)`,
            opacity: inT,
            marginBottom: size * 0.75,
          }}
        >
          {headline}
        </div>
        <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
          {[0, 1].map((k) => {
            const ph = ((frame - 20 - k * 18) % 36) / 36;
            const on = frame > 20 + k * 18;
            return (
              <div
                key={k}
                style={{
                  position: "absolute",
                  inset: 0,
                  borderRadius: size,
                  border: `${u * 0.5}px solid ${accent}`,
                  transform: `scale(${1 + ph * 0.45})`,
                  opacity: on ? 0.7 * (1 - ph) : 0,
                }}
              />
            );
          })}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: size * 0.35,
              background: accent,
              color: INK,
              fontFamily: FONT,
              fontSize: size * 0.8,
              padding: `${size * 0.32}px ${size * 0.8}px`,
              borderRadius: size,
              transform: `scale(${btnT * beat})`,
              boxShadow: `0 ${u}px ${u * 3}px rgba(0,0,0,.45)`,
              textTransform: "uppercase",
            }}
          >
            <svg width={size * 0.7} height={size * 0.7} viewBox="0 0 24 24">
              <path d="M12 5v14M5 12h14" stroke={INK} strokeWidth={3.4} strokeLinecap="round" />
            </svg>
            {btn}
          </div>
        </div>
      </Safe>
    </AbsoluteFill>
  );
};
