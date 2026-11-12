import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { safeArea } from "../theme";

/** Entrada/salida global de la capa: aparece en ~6 frames y se va en los últimos ~10. */
export const useLayerOpacity = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  return interpolate(frame, [0, 6, durationInFrames - 10, durationInFrames - 1], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
};

/** Oscurece suavemente la parte superior del video para que el texto destaque. */
export const Scrim: React.FC<{ strength?: number }> = ({ strength = 0.55 }) => {
  const { width, height } = useVideoConfig();
  const portrait = height > width;
  return (
    <AbsoluteFill
      style={{
        background: portrait
          ? `linear-gradient(to bottom, rgba(0,0,0,${strength}) 0%, rgba(0,0,0,${strength * 0.75}) 45%, rgba(0,0,0,0) 68%)`
          : `radial-gradient(ellipse at 50% 42%, rgba(0,0,0,${strength * 0.85}) 0%, rgba(0,0,0,${strength * 0.4}) 55%, rgba(0,0,0,0) 80%)`,
      }}
    />
  );
};

/** Contenedor centrado dentro de la zona segura. */
export const Safe: React.FC<{ children: React.ReactNode; align?: "center" | "flex-start" }> = ({
  children,
  align = "center",
}) => {
  const { width, height } = useVideoConfig();
  const s = safeArea(width, height);
  return (
    <AbsoluteFill
      style={{
        top: s.top,
        bottom: s.bottom,
        left: s.side,
        right: s.side,
        height: "auto",
        width: "auto",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: align,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};
