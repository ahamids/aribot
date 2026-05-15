// Row — single labeled value row, sized to live inside a padding-0 Card.
// Ported from screens-main.jsx Row (lines 213-224).
//
// Visual: left side is the label (15pt 700), right side is the value (14pt 600
// muted, or any ReactNode like a Toggle / chip / link). Dashed bottom divider
// unless `last` is true.
//
// `danger` styles the value in pure red — used for "Sign out" rows. The text
// label color stays normal; only the right-side value flips. This matches the
// design's Settings → Account → "Sign out" row.
//
// `onPress` makes the entire row tappable; absent and it's a static row.

import React from 'react';
import { Pressable, StyleProp, Text, View, ViewStyle } from 'react-native';
import { AT } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

type Props = {
  left: React.ReactNode;
  right?: React.ReactNode;
  last?: boolean;
  danger?: boolean;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
};

export function Row({ left, right, last, danger, onPress, style }: Props) {
  const theme = useTheme();
  const content = (
    <View
      style={[
        {
          paddingVertical: 14,
          paddingHorizontal: 16,
          flexDirection: 'row',
          alignItems: 'center',
          gap: 12,
          borderBottomWidth: last ? 0 : 1.5,
          borderBottomColor: theme.divider,
          borderStyle: 'dashed',
        },
        style,
      ]}
    >
      <View style={{ flex: 1 }}>
        {typeof left === 'string' ? (
          <Text style={{ fontSize: 15, fontWeight: '700', color: theme.text }}>{left}</Text>
        ) : (
          left
        )}
      </View>
      <View>
        {typeof right === 'string' ? (
          <Text
            style={{
              fontSize: 14,
              color: danger ? AT.pnlRed : theme.textMid,
              fontWeight: danger ? '800' : '600',
            }}
          >
            {right}
          </Text>
        ) : (
          right
        )}
      </View>
    </View>
  );
  if (onPress) {
    return (
      <Pressable
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel={typeof left === 'string' ? left : undefined}
      >
        {content}
      </Pressable>
    );
  }
  return content;
}
