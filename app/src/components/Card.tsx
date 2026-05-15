// Card — sticker container. Outlined + dual shadow by default. Color is the
// background. Use `hard` to keep the offset shadow (default true).

import React, { ReactNode } from 'react';
import { StyleProp, View, ViewStyle } from 'react-native';
import { AT, ambientShadow, stickerShadow } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

type Props = {
  children: ReactNode;
  // Background color. If omitted, uses the current theme's card surface.
  // Pass an explicit color (e.g. AT.pnlRedSoft for error states) to override.
  color?: string;
  outlined?: boolean;
  hard?: boolean;
  padding?: number;
  radius?: number;
  style?: StyleProp<ViewStyle>;
};

export function Card({
  children,
  color,
  outlined = true,
  hard = true,
  padding = 20,
  radius = AT.rL,
  style,
}: Props) {
  const theme = useTheme();
  const bg = color ?? theme.card;
  return (
    <View
      style={[
        {
          backgroundColor: bg,
          borderRadius: radius,
          padding,
          borderWidth: outlined ? AT.ol2 : 0,
          borderColor: theme.outline,
        },
        outlined && hard ? stickerShadow(theme.shadowHard) : ambientShadow(),
        style,
      ]}
    >
      {children}
    </View>
  );
}
