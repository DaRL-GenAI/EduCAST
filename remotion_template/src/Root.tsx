import React from "react";
import { Composition } from "remotion";
import { SceneBeat, sceneBeatDefaultProps, type SceneBeatProps } from "./SceneBeat";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="SceneBeat"
      component={SceneBeat}
      durationInFrames={240}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={sceneBeatDefaultProps}
      calculateMetadata={({ props }: { props: SceneBeatProps }) => {
        const seconds = Math.max(2, Number(props.durationInSeconds) || 8);
        const width = Number(props.style?.layout?.width) || 1920;
        const height = Number(props.style?.layout?.height) || 1080;
        return {
          durationInFrames: Math.round(seconds * 30),
          width,
          height,
        };
      }}
    />
  );
};
