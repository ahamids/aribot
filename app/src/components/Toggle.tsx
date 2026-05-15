// Toggle — sticker-shaped on/off pill. Ported from the design's
// components.jsx Toggle (lines 291-307): 56×32 outer pill with a 26×26 white
// thumb that slides between left and right. Mint background when on,
// creamDeep when off. Plum border, plum hard-shadow on the thumb.
//
// Pure on/off. For more complex states (loading, indeterminate) callers
// should disable the toggle and surface their own state outside.

import React, { useEffect, useRef } from 'react';
import {
  AccessibilityProps,
  Animated,
  Easing,
  Pressable,
  View,
} from 'react-native';
import { AT, stickerShadow } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

type Props = {
  value: boolean;
  onValueChange?: (next: boolean) => void;
  disabled?: boolean;
} & AccessibilityProps;

const THUMB_TRAVEL = 24; // 56 outer - 2*1 border - 26 thumb - 2*1 padding ≈ 24

export function Toggle({
  value,
  onValueChange,
  disabled,
  accessibilityLabel,
}: Props) {
  const x = useRef(new Animated.Value(value ? THUMB_TRAVEL : 0)).current;
  const theme = useTheme();

  useEffect(() => {
    Animated.timing(x, {
      toValue: value ? THUMB_TRAVEL : 0,
      duration: 180,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [value, x]);

  return (
    <Pressable
      onPress={() => !disabled && onValueChange?.(!value)}
      disabled={disabled}
      accessibilityRole="switch"
      accessibilityState={{ checked: value, disabled: !!disabled }}
      accessibilityLabel={accessibilityLabel}
      hitSlop={8}
      style={{
        width: 56,
        height: 32,
        borderRadius: AT.rPill,
        borderWidth: AT.ol2,
        borderColor: theme.outline,
        // Off-track flips with the theme (cardAlt); on-track stays mint
        // because it's an affordance hue, not a surface.
        backgroundColor: value ? AT.mint : theme.cardAlt,
        padding: 1,
        justifyContent: 'center',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      <Animated.View
        style={[
          {
            width: 26,
            height: 26,
            borderRadius: 13,
            // Thumb is bright in both modes so it reads against the track.
            backgroundColor: '#fff',
            borderWidth: AT.ol2,
            borderColor: theme.outline,
            transform: [{ translateX: x }],
          },
          stickerShadow(theme.shadowHard),
        ]}
      >
        {/* Inner shine is handled by the sticker shadow recipe; no extra view needed. */}
        <View />
      </Animated.View>
    </Pressable>
  );
}
