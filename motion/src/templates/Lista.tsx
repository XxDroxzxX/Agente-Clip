import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT, INK, OverlayProps, safeArea, textShadow, timeline } from "../theme";
import { Safe, Scrim, useLayerOpacity } from "./common";

/** Enumeración: título en etiqueta y elementos numerados que entran escalonados a lo largo de la toma. */
export const Lista: React.FC<OverlayProps> = ({ headline, items, accent, itemFrames }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const s = safeArea(width, height);
  const u = s.unit;
  const list = items.filter(Boolean).slice(0, 5);
  const n = Math.max(1, list.length);
  // reparte la entrada de los elementos en el 60 % inicial de la toma
  const stagger = Math.max(6, Math.min(30, (durationInFrames * 0.6 - 12) / n));
  const at = timeline(itemFrames, n, 10, stagger, durationInFrames - 25);
  const itemSize = (s.portrait ? 6.2 : 5.4) * u * (n > 3 ? 0.88 : 1);
  const titleIn = spring({ frame: frame - 2, fps, config: { damping: 14, stiffness: 160 } });

  return (
    <AbsoluteFill style={{ opacity: useLayerOpacity() }}>
      <Scrim strength={0.6} />
      <Safe>
        {headline && (
          <div
            style={{
              fontFamily: FONT,
              fontSize: itemSize * 0.78,
              textTransform: "uppercase",
              color: INK,
              background: accent,
              padding: `${itemSize * 0.18}px ${itemSize * 0.5}px`,
              borderRadius: itemSize * 0.3,
              marginBottom: itemSize * 0.7,
              transform: `scale(${titleIn}) rotate(${(1 - titleIn) * -8}deg)`,
              boxShadow: `0 ${u * 0.5}px ${u * 1.6}px rgba(0,0,0,.4)`,
              textAlign: "center",
            }}
          >
            {headline}
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: itemSize * 0.42, width: "100%" }}>
          {list.map((it, i) => {
            const t = spring({ frame: frame - at[i], fps, config: { damping: 13, stiffness: 150 } });
            const glow = interpolate(frame - at[i], [0, 6, 18], [0, 1, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: itemSize * 0.45,
                  opacity: Math.min(1, t * 1.5),
                  transform: `translateX(${(1 - t) * -width * 0.35}px)`,
                  background: "rgba(12,12,20,.62)",
                  border: `${Math.max(2, u * 0.25)}px solid rgba(255,255,255,${0.1 + glow * 0.5})`,
                  borderRadius: itemSize * 0.45,
                  padding: `${itemSize * 0.32}px ${itemSize * 0.5}px`,
                }}
              >
                <div
                  style={{
                    flex: "none",
                    width: itemSize * 1.25,
                    height: itemSize * 1.25,
                    borderRadius: "50%",
                    background: accent,
                    color: INK,
                    fontFamily: FONT,
                    fontSize: itemSize * 0.75,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    transform: `scale(${0.6 + 0.4 * t + glow * 0.15})`,
                  }}
                >
                  {i + 1}
                </div>
                <div
                  style={{
                    fontFamily: FONT,
                    fontSize: itemSize,
                    lineHeight: 1.1,
                    color: "#fff",
                    textShadow: textShadow(u * 0.6),
                  }}
                >
                  {it}
                </div>
              </div>
            );
          })}
        </div>
      </Safe>
    </AbsoluteFill>
  );
};
