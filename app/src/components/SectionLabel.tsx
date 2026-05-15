// SectionLabel — uppercase tracking-out label that sits above a grouped Card
// in Settings. Ported from screens-main.jsx SectionLabel (lines 208-210).

import React from 'react';
import { Text } from 'react-native';
import { useTheme } from '@/theme/useTheme';

type Props = {
  children: React.ReactNode;
};

export function SectionLabel({ children }: Props) {
  const theme = useTheme();
  return (
    <Text
      style={{
        fontSize: 11,
        fontWeight: '800',
        letterSpacing: 0.8,
        color: theme.textMid,
        margin: 4,
        marginBottom: 8,
      }}
    >
      {children}
    </Text>
  );
}
