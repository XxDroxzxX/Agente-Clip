import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT, INK, OverlayProps, isHighlighted, safeArea, textShadow, timeline } from "../theme";
import { Safe, Scrim, useLayerOpacity } from "./common";

/** Gancho: las palabras entran una a una con rebote; la palabra clave lleva un marcador de color. */
export const Titulo: React.FC<OverlayProps> = ({ headline, highlight, accent, wordFrames }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const s = safeArea(width, height);
  const u = s.unit;
  const words = headline.trim().split(/\s+/).filter(Boolean);
  const size = (s.portrait ? 11 : 9.5) * u * (words.length > 6 ? 0.8 : 1);
  const at = timeline(wordFrames, words.length, 3, 4, durationInFrames - 25);

  return (
    <AbsoluteFill style={{ opacity: useLayerOpacity() }}>
      <Scrim />
      <Safe>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "center",
            gap: `${size * 0.12}px ${size * 0.26}px`,
            fontFamily: FONT,
            fontSize: size,
            lineHeight: 1.05,
            textTransform: "uppercase",
            textAlign: "center",
          }}
        >
          {words.map((w, i) => {
            const t = spring({ frame: frame - at[i], fps, config: { damping: 11, stiffness: 170, mass: 0.7 } });
            const hl = isHighlighted(w, highlight);
            const sweep = interpolate(frame - at[i] - 7, [0, 8], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <span
                key={i}
                style={{
                  position: "relative",
                  display: "inline-block",
                  opacity: Math.min(1, t * 1.4),
                  transform: `translateY(${(1 - t) * size * 0.55}px) scale(${0.55 + 0.45 * t}) rotate(${(1 - t) * (i % 2 ? 6 : -6)}deg)`,
                  color: hl ? INK : "#fff",
                  textShadow: hl ? "none" : textShadow(u),
                  padding: hl ? `0 ${size * 0.12}px` : 0,
                }}
              >
                {hl && (
                  <span
                    style={{
                      position: "absolute",
                      inset: `${size * 0.06}px 0`,
                      background: accent,
                      borderRadius: size * 0.12,
                      transform: `scaleX(${sweep}) rotate(-2deg)`,
                      transformOrigin: "left center",
                      zIndex: -1,
                      boxShadow: `0 ${u * 0.4}px ${u * 1.4}px rgba(0,0,0,.35)`,
                    }}
                  />
                )}
                {w}
              </span>
            );
          })}
        </div>
      </Safe>
    </AbsoluteFill>
  );
};
