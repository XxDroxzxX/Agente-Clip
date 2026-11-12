import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT, OverlayProps, isHighlighted, safeArea, timeline } from "../theme";
import { Safe, Scrim, useLayerOpacity } from "./common";

/** Frase clave en una tarjeta: comillas que caen, palabras que se revelan y subrayado de la palabra clave. */
export const Frase: React.FC<OverlayProps> = ({ headline, highlight, accent, wordFrames }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const s = safeArea(width, height);
  const u = s.unit;
  const words = headline.trim().split(/\s+/).filter(Boolean);
  const size = (s.portrait ? 7.4 : 6.2) * u * (words.length > 9 ? 0.82 : 1);
  const at = timeline(wordFrames, words.length, 8, 2.5, durationInFrames - 25);
  const card = spring({ frame: frame - 1, fps, config: { damping: 15, stiffness: 130 } });
  const quote = spring({ frame: frame - 6, fps, config: { damping: 8, stiffness: 120 } });

  return (
    <AbsoluteFill style={{ opacity: useLayerOpacity() }}>
      <Scrim strength={0.45} />
      <Safe>
        <div
          style={{
            position: "relative",
            background: "rgba(14,14,24,.72)",
            border: `${Math.max(2, u * 0.3)}px solid rgba(255,255,255,.14)`,
            borderLeft: `${u * 1.4}px solid ${accent}`,
            borderRadius: u * 3,
            padding: `${size * 0.9}px ${size * 0.8}px ${size * 0.8}px`,
            transform: `translateY(${(1 - card) * u * 10}px) scale(${0.9 + 0.1 * card})`,
            opacity: card,
            boxShadow: `0 ${u}px ${u * 4}px rgba(0,0,0,.45)`,
          }}
        >
          <div
            style={{
              position: "absolute",
              top: -size * 0.95,
              left: size * 0.4,
              fontFamily: "Georgia, serif",
              fontSize: size * 3,
              lineHeight: 1,
              color: accent,
              transform: `translateY(${(1 - quote) * -u * 12}px) rotate(${(1 - quote) * -20}deg)`,
              opacity: Math.min(1, quote * 1.3),
            }}
          >
            “
          </div>
          <div style={{ fontFamily: FONT, fontSize: size, lineHeight: 1.18, color: "#fff" }}>
            {words.map((w, i) => {
              const a = interpolate(frame - at[i], [0, 7], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              });
              const hl = isHighlighted(w, highlight);
              const line = interpolate(frame - at[i] - 6, [0, 10], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              });
              return (
                <span key={i} style={{ position: "relative", display: "inline-block", marginRight: size * 0.26, opacity: a, transform: `translateY(${(1 - a) * size * 0.3}px)`, color: hl ? accent : "#fff" }}>
                  {w}
                  {hl && (
                    <span
                      style={{
                        position: "absolute",
                        left: 0,
                        right: 0,
                        bottom: -size * 0.08,
                        height: size * 0.12,
                        borderRadius: size,
                        background: accent,
                        transform: `scaleX(${line})`,
                        transformOrigin: "left",
                      }}
                    />
                  )}
                </span>
              );
            })}
          </div>
        </div>
      </Safe>
    </AbsoluteFill>
  );
};
