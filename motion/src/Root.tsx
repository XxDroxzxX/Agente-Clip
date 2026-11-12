import React from "react";
import { Composition } from "remotion";
import { OverlayProps, defaultProps } from "./theme";
import { Cta } from "./templates/Cta";
import { Dato } from "./templates/Dato";
import { Frase } from "./templates/Frase";
import { Lista } from "./templates/Lista";
import { Titulo } from "./templates/Titulo";

const TEMPLATES = { titulo: Titulo, lista: Lista, dato: Dato, frase: Frase, cta: Cta };

const Overlay: React.FC<OverlayProps> = (props) => {
  const C = TEMPLATES[props.type] ?? Titulo;
  return <C {...props} />;
};

export const Root: React.FC = () => (
  <>
    {/* Una sola composición; tamaño y duración vienen de las props de cada toma. */}
    <Composition
      id="Overlay"
      component={Overlay}
      defaultProps={defaultProps}
      width={defaultProps.width}
      height={defaultProps.height}
      fps={defaultProps.fps}
      durationInFrames={defaultProps.durationInFrames}
      calculateMetadata={({ props }) => ({
        width: props.width,
        height: props.height,
        fps: props.fps,
        durationInFrames: Math.max(1, Math.round(props.durationInFrames)),
      })}
    />
  </>
);
