// Tab layout for the main app. Four tabs: dashboard, positions, history,
// settings. Custom tab bar via Expo Router's Tabs component, restyled to
// match the design's chunky sticker aesthetic.

import React from 'react';
import { View, Text, Pressable } from 'react-native';
import { Tabs } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AT, stickerShadow } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Icon, type IconName } from '@/components/Icon';

const TABS: { name: string; label: string; icon: IconName }[] = [
  { name: 'dashboard', label: 'Home',      icon: 'home' },
  { name: 'positions', label: 'Positions', icon: 'positions' },
  { name: 'history',   label: 'History',   icon: 'history' },
  { name: 'settings',  label: 'Settings',  icon: 'settings' },
];

export default function AppTabsLayout() {
  return (
    <Tabs
      screenOptions={{ headerShown: false }}
      tabBar={props => <AribotTabBar {...props} />}
    >
      {TABS.map(t => (
        <Tabs.Screen key={t.name} name={t.name} options={{ title: t.label }} />
      ))}
    </Tabs>
  );
}

function AribotTabBar({ state, navigation }: any) {
  const insets = useSafeAreaInsets();
  const theme = useTheme();
  const activeRouteName = state.routes[state.index]?.name as string | undefined;

  return (
    <View
      style={[
        {
          position: 'absolute',
          left: 12,
          right: 12,
          bottom: Math.max(insets.bottom, 18),
          backgroundColor: theme.card,
          borderRadius: AT.rXL,
          borderWidth: AT.ol3,
          borderColor: theme.outline,
          paddingVertical: 10,
          paddingHorizontal: 8,
          flexDirection: 'row',
          justifyContent: 'space-around',
        },
        stickerShadow(theme.shadowHard),
      ]}
    >
      {TABS.map(t => {
        const on = activeRouteName === t.name;
        return (
          <Pressable
            key={t.name}
            onPress={() => navigation.navigate(t.name)}
            accessibilityRole="tab"
            accessibilityState={{ selected: on }}
            accessibilityLabel={t.label}
            hitSlop={8}
            style={{
              alignItems: 'center',
              justifyContent: 'center',
              paddingVertical: 6,
              paddingHorizontal: 12,
              borderRadius: AT.rM,
              backgroundColor: on ? AT.coral : 'transparent',
              borderWidth: 2,
              borderColor: on ? theme.outline : 'transparent',
            }}
          >
            <Icon name={t.icon} size={22} color={on ? '#fff' : theme.textMid} />
            <Text
              style={{
                fontSize: 11,
                fontWeight: '800',
                letterSpacing: 0.3,
                color: on ? '#fff' : theme.textMid,
                marginTop: 3,
              }}
            >
              {t.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}
