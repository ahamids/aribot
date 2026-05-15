// Bear — placeholder mascot. Ported pose-for-pose from the design's mascot.jsx.
// Designed as a SLOT (see MascotSlot.tsx) so the character can be swapped later
// without touching any screen.

import React from 'react';
import Svg, {
  Circle,
  Ellipse,
  G,
  Path,
  Text as SvgText,
} from 'react-native-svg';

const BEAR_FUR = '#E8A576';
const BEAR_INNER_EAR = '#FFD7B0';
const BEAR_SNOUT = '#FFEBD2';
const BEAR_OUTLINE = '#2D1F47';
const BEAR_BLUSH = '#FF8B66';

export type BearPose =
  | 'alert'
  | 'sleeping'
  | 'napping'
  | 'panicked'
  | 'sad'
  | 'questioning'
  | 'serious'
  | 'wink'
  | 'happy'
  | 'thumbsup'
  | 'waving';

function Eyes({ pose }: { pose: BearPose }) {
  const O = BEAR_OUTLINE;
  switch (pose) {
    case 'sleeping':
    case 'napping':
      return (
        <G stroke={O} strokeWidth={4} strokeLinecap="round" fill="none">
          <Path d="M68 96 Q78 102 88 96" />
          <Path d="M112 96 Q122 102 132 96" />
        </G>
      );
    case 'panicked':
      return (
        <G stroke={O} strokeWidth={4} strokeLinecap="round" fill="none">
          <Path d="M70 90 L86 102 M86 90 L70 102" />
          <Path d="M114 90 L130 102 M130 90 L114 102" />
        </G>
      );
    case 'sad':
      return (
        <G fill={O}>
          <Circle cx={78} cy={98} r={5} />
          <Circle cx={122} cy={98} r={5} />
        </G>
      );
    case 'questioning':
      return (
        <G>
          <Circle cx={78} cy={96} r={6} fill={O} />
          <Circle cx={76} cy={94} r={2} fill="#fff" />
          <Circle cx={122} cy={96} r={6} fill={O} />
          <Circle cx={120} cy={94} r={2} fill="#fff" />
        </G>
      );
    case 'serious':
      return (
        <G>
          <Ellipse cx={78} cy={96} rx={6} ry={4} fill={O} />
          <Ellipse cx={122} cy={96} rx={6} ry={4} fill={O} />
        </G>
      );
    case 'wink':
      return (
        <G>
          <Path
            d="M70 96 Q78 102 88 96"
            stroke={O}
            strokeWidth={4}
            strokeLinecap="round"
            fill="none"
          />
          <Circle cx={122} cy={96} r={6} fill={O} />
          <Circle cx={120} cy={94} r={2} fill="#fff" />
        </G>
      );
    case 'alert':
    case 'thumbsup':
    case 'waving':
    case 'happy':
    default:
      return (
        <G>
          <Circle cx={78} cy={96} r={7} fill={O} />
          <Circle cx={76} cy={94} r={2.5} fill="#fff" />
          <Circle cx={122} cy={96} r={7} fill={O} />
          <Circle cx={120} cy={94} r={2.5} fill="#fff" />
        </G>
      );
  }
}

function Mouth({ pose }: { pose: BearPose }) {
  const O = BEAR_OUTLINE;
  switch (pose) {
    case 'sleeping':
    case 'napping':
      return <Ellipse cx={100} cy={138} rx={6} ry={4} fill={O} />;
    case 'panicked':
      return (
        <Path
          d="M86 138 Q92 130 100 138 T114 138"
          stroke={O}
          strokeWidth={3.5}
          fill="none"
          strokeLinecap="round"
        />
      );
    case 'serious':
      return (
        <Path
          d="M86 138 L114 138"
          stroke={O}
          strokeWidth={4}
          strokeLinecap="round"
        />
      );
    case 'sad':
      return (
        <Path
          d="M86 142 Q100 132 114 142"
          stroke={O}
          strokeWidth={3.5}
          fill="none"
          strokeLinecap="round"
        />
      );
    case 'questioning':
      return (
        <Path
          d="M88 138 Q100 140 112 138"
          stroke={O}
          strokeWidth={3.5}
          fill="none"
          strokeLinecap="round"
        />
      );
    case 'thumbsup':
    case 'happy':
    case 'waving':
    case 'wink':
      return (
        <Path
          d="M84 132 Q100 150 116 132"
          stroke={O}
          strokeWidth={3.5}
          fill="none"
          strokeLinecap="round"
        />
      );
    case 'alert':
    default:
      return (
        <Path
          d="M88 134 Q100 144 112 134"
          stroke={O}
          strokeWidth={3.5}
          fill="none"
          strokeLinecap="round"
        />
      );
  }
}

function Extras({ pose }: { pose: BearPose }) {
  const O = BEAR_OUTLINE;
  if (pose === 'sleeping' || pose === 'napping') {
    return (
      <G fill={O}>
        <SvgText x={148} y={56} fontSize={18} fontWeight="800">
          z
        </SvgText>
        <SvgText x={162} y={42} fontSize={22} fontWeight="800">
          Z
        </SvgText>
        <SvgText x={178} y={26} fontSize={26} fontWeight="800">
          Z
        </SvgText>
      </G>
    );
  }
  if (pose === 'questioning') {
    return (
      <G stroke={O} strokeWidth={2.5}>
        <Circle cx={158} cy={48} r={14} fill="#FFC93C" />
        <SvgText
          x={153}
          y={55}
          fontSize={18}
          fontWeight="900"
          fill={O}
          stroke="none"
        >
          ?
        </SvgText>
      </G>
    );
  }
  if (pose === 'panicked') {
    return (
      <G>
        <Ellipse
          cx={44}
          cy={78}
          rx={6}
          ry={9}
          fill="#8B9DFF"
          stroke={O}
          strokeWidth={2}
        />
        <Ellipse
          cx={156}
          cy={78}
          rx={6}
          ry={9}
          fill="#8B9DFF"
          stroke={O}
          strokeWidth={2}
        />
      </G>
    );
  }
  return null;
}

function Arms({ pose }: { pose: BearPose }) {
  const O = BEAR_OUTLINE;
  if (pose === 'thumbsup') {
    return (
      <G stroke={O} strokeWidth={3} strokeLinejoin="round">
        <Path d="M156 130 L172 100 L168 88 L156 86 L150 100 Z" fill={BEAR_FUR} />
        <Circle cx={170} cy={92} r={8} fill={BEAR_FUR} />
        <Path d="M168 88 L172 80" strokeLinecap="round" />
      </G>
    );
  }
  if (pose === 'waving') {
    return (
      <G stroke={O} strokeWidth={3} strokeLinejoin="round">
        <Path d="M156 122 L178 96 L168 84 L150 94 Z" fill={BEAR_FUR} />
        <Circle cx={178} cy={92} r={10} fill={BEAR_FUR} />
        <Path
          d="M192 80 L198 76 M192 92 L200 92 M194 104 L200 108"
          strokeLinecap="round"
          strokeWidth={2.5}
        />
      </G>
    );
  }
  if (pose === 'questioning') {
    return (
      <G stroke={O} strokeWidth={3} strokeLinejoin="round">
        <Path d="M138 64 L132 44 L120 38 L114 50 Z" fill={BEAR_FUR} />
        <Circle cx={125} cy={40} r={8} fill={BEAR_FUR} />
      </G>
    );
  }
  return null;
}

export function Bear({ pose = 'alert' as BearPose }: { pose?: BearPose }) {
  const O = BEAR_OUTLINE;
  return (
    <Svg viewBox="0 0 200 200" width="100%" height="100%">
      {/* Ears */}
      <G stroke={O} strokeWidth={4}>
        <Circle cx={52} cy={52} r={22} fill={BEAR_FUR} />
        <Circle cx={148} cy={52} r={22} fill={BEAR_FUR} />
        <Circle cx={52} cy={52} r={11} fill={BEAR_INNER_EAR} stroke="none" />
        <Circle cx={148} cy={52} r={11} fill={BEAR_INNER_EAR} stroke="none" />
      </G>
      {/* Head */}
      <Ellipse
        cx={100}
        cy={105}
        rx={62}
        ry={58}
        fill={BEAR_FUR}
        stroke={O}
        strokeWidth={4}
      />
      {/* Snout */}
      <Ellipse
        cx={100}
        cy={130}
        rx={34}
        ry={24}
        fill={BEAR_SNOUT}
        stroke={O}
        strokeWidth={3}
      />
      {/* Cheeks */}
      <Ellipse cx={62} cy={124} rx={9} ry={5} fill={BEAR_BLUSH} opacity={0.55} />
      <Ellipse cx={138} cy={124} rx={9} ry={5} fill={BEAR_BLUSH} opacity={0.55} />
      {/* Nose */}
      <Ellipse cx={100} cy={116} rx={9} ry={6.5} fill={O} />
      <Ellipse cx={97} cy={113} rx={2} ry={1.5} fill="#fff" opacity={0.8} />

      <Eyes pose={pose} />
      <Mouth pose={pose} />
      <Arms pose={pose} />
      <Extras pose={pose} />
    </Svg>
  );
}
