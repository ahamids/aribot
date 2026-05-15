// Segmented — pill-shaped two/three-state toggle. RN port of the design's
// Segmented from components.jsx. Touch the whole pill; the selected option
// gets a white capsule with a thin plum hard shadow.

import React from 'react';
import { Pressable, Text, View, ViewStyle, StyleProp } from 'react-native';
import { AT } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

type Props<T extends string> = {
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  style?: StyleProp<ViewStyle>;
};

export function Segmented<T extends string>({ options, value, onChange, style }: Props<T>) {
  const theme = useTheme();
  return (
    <View
      style={[
        {
          alignSelf: 'flex-start',
          flexDirection: 'row',
          padding: 4,
          // Track color: cardAlt is creamDeep in light, darkCard in dark.
          backgroundColor: theme.cardAlt,
          borderRadius: AT.rPill,
          borderWidth: AT.ol2,
          borderColor: theme.outline,
        },
        style,
      ]}
    >
      {options.map(o => {
        const on = o === value;
        return (
          <Pressable
            key={o}
            onPress={() => onChange(o)}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
            style={{
              paddingVertical: 8,
              paddingHorizontal: 18,
              borderRadius: AT.rPill,
              // Active pill stands out against the track: white in light,
              // theme text color (a warm cream) in dark.
              backgroundColor: on ? (theme.kind === 'dark' ? theme.text : '#fff') : 'transparent',
              borderWidth: 2,
              borderColor: on ? theme.outline : 'transparent',
            }}
          >
            <Text
              style={{
                fontSize: 14,
                fontWeight: '800',
                letterSpacing: 0.3,
                // Active label always reads dark (the bg is light-ish in both modes).
                // Inactive label is the theme's mid text.
                color: on ? AT.plum : theme.textMid,
              }}
            >
              {o}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}
