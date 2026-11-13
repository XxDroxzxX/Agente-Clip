import React from "react";
import { AbsoluteFill, Img } from "remotion";
import { FONT, INK, isHighlighted } from "../theme";

export type MiniaturaProps = {
  width: number;
  height: number;
  bg: string; // imagen de fondo (data URL)
  headline: string; // 2-5 palabras
  highlight: string; // palabra resaltada
  accent: string;
  badge: string; // etiqueta pequeña opcional (ej. "10 MIN")
};

export const miniaturaDefaults: MiniaturaProps = {
  width: 1280,
  height: 720,
  bg: "",
  headline: "Adiós al huevo para siempre",
  highlight: "huevo",
  accent: "#FFD633",
  badge: "",
};

/** Miniatura de YouTube: foto a sangre, texto gigante a la izquierda con contorno grueso y una palabra en caja de color. */
export const Miniatura: React.FC<MiniaturaProps> = ({ width, height, bg, headline, highlight, accent, badge }) => {
  const u = height / 100;
  const words = headline.trim().toUpperCase().split(/\s+/).filter(Boolean).slice(0, 6);
  const longest = Math.max(...words.map((w) => w.length), 4);
  // tamaño según la palabra más larga: siempre cabe en ~58 % del ancho
  const size = Math.min(17 * u, (width * 0.58) / (longest * 0.62));
  const stroke = size * 0.07;
  return (
    <AbsoluteFill style={{ background: INK }}>
      {bg ? (
        <Img
          src={bg}
          style={{ width: "100%", height: "100%", objectFit: "cover", filter: "saturate(1.25) contrast(1.08)" }}
        />
      ) : null}
      <AbsoluteFill
        style={{
          background: "linear-gradient(90deg, rgba(0,0,0,.78) 0%, rgba(0,0,0,.55) 42%, rgba(0,0,0,0) 72%)",
        }}
      />
      <AbsoluteFill
        style={{
          left: 5 * u,
          right: width * 0.36,
          width: "auto",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          gap: size * 0.08,
        }}
      >
        {badge ? (
          <div
            style={{
              alignSelf: "flex-start",
              fontFamily: FONT,
              fontSize: size * 0.32,
              color: INK,
              background: accent,
              padding: `${size * 0.04}px ${size * 0.16}px`,
              borderRadius: size * 0.08,
              marginBottom: size * 0.1,
            }}
          >
            {badge.toUpperCase()}
          </div>
        ) : null}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: `${size * 0.04}px ${size * 0.22}px`,
            fontFamily: FONT,
            fontSize: size,
            lineHeight: 1.0,
            letterSpacing: -size * 0.01,
          }}
        >
          {words.map((w, i) => {
            const hl = isHighlighted(w, highlight);
            return (
              <span
                key={i}
                style={{
                  color: hl ? INK : "#ffffff",
                  background: hl ? accent : "transparent",
                  padding: hl ? `0 ${size * 0.12}px` : 0,
                  borderRadius: hl ? size * 0.1 : 0,
                  transform: hl ? "rotate(-2deg)" : undefined,
                  WebkitTextStroke: hl ? undefined : `${stroke}px ${INK}`,
                  paintOrder: "stroke fill",
                  textShadow: `0 ${u * 0.8}px ${u * 2.5}px rgba(0,0,0,.6)`,
                }}
              >
                {w}
              </span>
            );
          })}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
