// Btn — sticker-shaped button. Bouncy press; chrome only (data never bounces).
// Variants: primary (coral), secondary (yellow), soft (white), mint, danger, ghost.

import React, { ReactNode, useRef } from 'react';
import {
  Animated,
  Pressable,
  StyleProp,
  Text,
  TextStyle,
  View,
  ViewStyle,
  GestureResponderEvent,
} from 'react-native';
import { AT, stickerShadow } from '@/theme/tokens';
import { useTheme, type Theme } from '@/theme/useTheme';

type Kind = 'primary' | 'secondary' | 'soft' | 'mint' | 'danger' | 'ghost';
type Size = 'sm' | 'md' | 'lg';

type Variant = {
  bg: string;
  fg: string;
  border: number;
  borderStyle?: 'solid' | 'dashed';
  borderColor: string;
};

// Variant table is theme-aware. `soft` and `ghost` are the variants whose
// surface color changes in dark mode — the others use fixed accent hues
// (coral/yellow/mint/pnlRed) that stay constant per the design's color
// reservation rule.
function variantsFor(t: Theme): Record<Kind, Variant> {
  return {
    primary:   { bg: AT.coral,    fg: '#fff',   border: AT.ol3, borderColor: t.outline },
    secondary: { bg: AT.yellow,   fg: AT.plum,  border: AT.ol3, borderColor: t.outline },
    soft:      { bg: t.card,      fg: t.text,   border: AT.ol2, borderColor: t.outline },
    mint:      { bg: AT.mint,     fg: AT.plum,  border: AT.ol3, borderColor: t.outline },
    danger:    { bg: AT.pnlRed,   fg: '#fff',   border: AT.ol3, borderColor: t.outline },
    ghost:     { bg: 'transparent', fg: t.text, border: 2, borderStyle: 'dashed', borderColor: t.textMid },
  };
}

type Props = {
  kind?: Kind;
  size?: Size;
  icon?: ReactNode;
  children: ReactNode;
  onPress?: (e: GestureResponderEvent) => void;
  disabled?: boolean;
  loading?: boolean;
  accessibilityLabel?: string;
  style?: StyleProp<ViewStyle>;
};

export function Btn({
  kind = 'primary',
  size = 'lg',
  icon,
  children,
  onPress,
  disabled,
  loading,
  accessibilityLabel,
  style,
}: Props) {
  const scale = useRef(new Animated.Value(1)).current;
  const theme = useTheme();
  const v = variantsFor(theme)[kind];

  const padding =
    size === 'sm'
      ? { paddingVertical: 10, paddingHorizontal: 18 }
      : size === 'md'
        ? { paddingVertical: 14, paddingHorizontal: 22 }
        : { paddingVertical: 18, paddingHorizontal: 28 };
  const fontSize = size === 'sm' ? 15 : size === 'md' ? 17 : 19;
  const radius = size === 'sm' ? AT.rM : AT.rL;

  const onPressIn = () => {
    Animated.spring(scale, {
      toValue: 0.96,
      useNativeDriver: true,
      friction: 6,
      tension: 220,
    }).start();
  };
  const onPressOut = () => {
    Animated.spring(scale, {
      toValue: 1,
      useNativeDriver: true,
      friction: 5,
      tension: 220,
    }).start();
  };

  const textStyle: TextStyle = {
    color: v.fg,
    fontSize,
    fontWeight: '800',
    letterSpacing: 0.2,
  };

  return (
    <Animated.View
      style={[
        { transform: [{ scale }], alignSelf: 'stretch' },
        kind !== 'ghost' && stickerShadow(theme.shadowHard),
        { borderRadius: radius },
        style,
      ]}
    >
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={accessibilityLabel}
        accessibilityState={{ disabled: !!disabled, busy: !!loading }}
        disabled={disabled || loading}
        onPress={onPress}
        onPressIn={onPressIn}
        onPressOut={onPressOut}
        style={[
          {
            backgroundColor: v.bg,
            borderRadius: radius,
            borderWidth: v.border,
            borderColor: v.borderColor,
            borderStyle: v.borderStyle ?? 'solid',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'center',
            opacity: disabled || loading ? 0.55 : 1,
            gap: 10,
          },
          padding,
        ]}
      >
        {icon ? <View>{icon}</View> : null}
        {typeof children === 'string' ? (
          <Text style={textStyle}>{children}</Text>
        ) : (
          children
        )}
      </Pressable>
    </Animated.View>
  );
}
