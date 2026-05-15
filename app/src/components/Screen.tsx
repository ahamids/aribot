// Screen shell — cream background, title, scrollable content area, optional
// back button. Uses SafeAreaView so the real iOS status bar inset is honored
// (we don't fake a status bar like the design's HTML preview does).

import React, { ReactNode } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleProp,
  Text,
  View,
  ViewStyle,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { router } from 'expo-router';
import { AT, TYPE } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Icon } from './Icon';

type Props = {
  children: ReactNode;
  title?: string;
  showBack?: boolean;
  scroll?: boolean;
  contentStyle?: StyleProp<ViewStyle>;
};

export function Screen({
  children,
  title,
  showBack,
  scroll = true,
  contentStyle,
}: Props) {
  const insets = useSafeAreaInsets();
  const Wrapper = scroll ? ScrollView : View;
  const theme = useTheme();

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.bg }} edges={['top', 'left', 'right']}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={insets.top}
      >
        {(showBack || title) && (
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: 12,
              paddingHorizontal: 24,
              paddingTop: 4,
              paddingBottom: title ? 14 : 4,
            }}
          >
            {showBack ? (
              <Pressable
                onPress={() => router.back()}
                accessibilityRole="button"
                accessibilityLabel="Go back"
                hitSlop={10}
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: AT.rPill,
                  borderWidth: AT.ol2,
                  borderColor: theme.outline,
                  backgroundColor: theme.card,
                  alignItems: 'center',
                  justifyContent: 'center',
                  shadowColor: theme.shadowHard,
                  shadowOpacity: 1,
                  shadowOffset: { width: 0, height: 4 },
                  shadowRadius: 0,
                }}
              >
                <Icon name="back" size={22} color={theme.text} />
              </Pressable>
            ) : null}
            {title ? <Text style={[TYPE.h1, { color: theme.text }]}>{title}</Text> : null}
          </View>
        )}

        <Wrapper
          contentContainerStyle={
            scroll
              ? [
                  { paddingHorizontal: 18, paddingBottom: 30 + insets.bottom, flexGrow: 1 },
                  contentStyle,
                ]
              : undefined
          }
          style={
            scroll
              ? undefined
              : [{ flex: 1, paddingHorizontal: 18, paddingBottom: 30 + insets.bottom }, contentStyle]
          }
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          {children}
        </Wrapper>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
