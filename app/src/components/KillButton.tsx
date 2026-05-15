// KillButton — hold-to-activate kill switch.
//
// Ported from the design's KillButton (mascot.jsx-adjacent in screens-main.jsx).
// Visual: 72×40 sticker pill, pure-red border (reservation rule: kill switch is
// one of the few places pure red is allowed), pnlRedSoft track, pure-red fill
// scaling left-to-right as the user holds.
//
// Gesture rules from the design:
//   - Hold 1.5 seconds to fire.
//   - Release early -> animation snaps back, never fires.
//   - A tap (press release before any progress) is explicitly NOT a trigger.
//
// Implementation: RN's built-in Animated.Value, NOT react-native-reanimated.
// Expo Go on SDK 54 doesn't ship reanimated v4's worklets turbo module, so
// importing reanimated crashes at app start with `installTurboModule` failing.
// The fire moment is detected by a setTimeout that gets cancelled on release;
// callback-based firing through animation completion is unreliable and the
// timeout approach is robust either way.

import React, { useEffect, useRef, useState } from 'react';
import {
  AccessibilityProps,
  Animated,
  Easing,
  Pressable,
  Text,
  View,
} from 'react-native';
import { AT, stickerShadow } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

const HOLD_MS = 1500;
// Visible interior width of the pill (96 outer - 3px border each side).
const FILL_WIDTH = 90;

type Props = {
  onConfirm: () => void;
  disabled?: boolean;
  label?: string;
} & AccessibilityProps;

export function KillButton({
  onConfirm,
  disabled,
  label = 'HOLD 1.5s',
  accessibilityLabel,
}: Props) {
  // progress drives both the visual fill AND the label color via an
  // interpolation. Animated.Value.useNativeDriver works for transform/opacity
  // — that's all we use here.
  const progress = useRef(new Animated.Value(0)).current;
  const [holding, setHolding] = useState(false);
  const startedAt = useRef<number | null>(null);
  const fireTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fillAnim = useRef<Animated.CompositeAnimation | null>(null);
  const theme = useTheme();

  function startHold() {
    if (disabled) return;
    setHolding(true);
    startedAt.current = Date.now();

    if (fillAnim.current) fillAnim.current.stop();
    fillAnim.current = Animated.timing(progress, {
      toValue: 1,
      duration: HOLD_MS,
      easing: Easing.linear,
      useNativeDriver: true,
    });
    fillAnim.current.start();

    fireTimer.current = setTimeout(() => {
      // Verify the user is still holding — releaseHold clears startedAt
      // before this timer can fire, so a stale callback no-ops.
      if (startedAt.current !== null) {
        startedAt.current = null;
        setHolding(false);
        // Defer onConfirm so callers' state updates (e.g. modals) don't
        // race the gesture cleanup.
        setTimeout(onConfirm, 0);
      }
    }, HOLD_MS);
  }

  function releaseHold() {
    if (startedAt.current === null) return; // already fired
    startedAt.current = null;
    setHolding(false);
    if (fireTimer.current) {
      clearTimeout(fireTimer.current);
      fireTimer.current = null;
    }
    if (fillAnim.current) {
      fillAnim.current.stop();
      fillAnim.current = null;
    }
    Animated.timing(progress, {
      toValue: 0,
      duration: 180,
      easing: Easing.out(Easing.quad),
      useNativeDriver: true,
    }).start();
  }

  useEffect(() => () => {
    if (fireTimer.current) clearTimeout(fireTimer.current);
    if (fillAnim.current) fillAnim.current.stop();
  }, []);

  // scaleX from the center pushes outward in both directions; we want a
  // left-to-right fill, so we translate by half the missing width before
  // scaling. translateX runs from -FILL_WIDTH/2 (at progress 0) to 0 (at 1).
  const translateX = progress.interpolate({
    inputRange: [0, 1],
    outputRange: [-FILL_WIDTH / 2, 0],
  });

  return (
    <Pressable
      onPressIn={startHold}
      onPressOut={releaseHold}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? `Kill switch, hold ${HOLD_MS / 1000} seconds`}
      accessibilityState={{ disabled: !!disabled, busy: holding }}
      accessibilityHint="Press and hold to trip the kill switch"
      style={[
        {
          width: 96,
          height: 44,
          borderRadius: AT.rPill,
          backgroundColor: AT.pnlRedSoft,
          borderWidth: 3,
          borderColor: AT.pnlRed,
          overflow: 'hidden',
          opacity: disabled ? 0.5 : 1,
        },
        stickerShadow(theme.shadowHard),
      ]}
    >
      {/* Progress fill — translated + scaled so it grows from the left edge. */}
      <Animated.View
        pointerEvents="none"
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          bottom: 0,
          right: 0,
          backgroundColor: AT.pnlRed,
          transform: [{ translateX }, { scaleX: progress }],
        }}
      />
      {/* Label centered on top. */}
      <View
        pointerEvents="none"
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: 0,
          right: 0,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text
          style={{
            fontSize: 11,
            fontWeight: '900',
            // Label always reads dark on the soft-red background. When the
            // user holds, the bg flips to pure red so we flip to white.
            // Pure-red bg works in both light and dark mode, so the literal
            // AT.plum text is fine before-hold either way.
            color: holding ? '#fff' : AT.plum,
            letterSpacing: 0.5,
          }}
        >
          {label}
        </Text>
      </View>
    </Pressable>
  );
}
