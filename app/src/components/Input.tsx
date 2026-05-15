// Input — chunky rounded field. Supports secure entry with eye toggle, monospace
// mode for keys/URLs, error state, optional left icon.

import React, { ReactNode, useState } from 'react';
import {
  Pressable,
  StyleProp,
  Text,
  TextInput,
  TextInputProps,
  View,
  ViewStyle,
} from 'react-native';
import { AT, TYPE } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Icon } from './Icon';

type Props = {
  label?: string;
  value?: string;
  onChangeText?: (s: string) => void;
  placeholder?: string;
  hint?: string;
  secure?: boolean;
  icon?: ReactNode;
  error?: boolean;
  monospace?: boolean;
  autoCapitalize?: TextInputProps['autoCapitalize'];
  autoComplete?: TextInputProps['autoComplete'];
  keyboardType?: TextInputProps['keyboardType'];
  textContentType?: TextInputProps['textContentType'];
  style?: StyleProp<ViewStyle>;
};

export function Input({
  label,
  value,
  onChangeText,
  placeholder,
  hint,
  secure,
  icon,
  error,
  monospace,
  autoCapitalize = 'none',
  autoComplete,
  keyboardType,
  textContentType,
  style,
}: Props) {
  const [show, setShow] = useState(!secure);
  const theme = useTheme();

  return (
    <View style={[{ alignSelf: 'stretch' }, style]}>
      {label ? (
        <Text style={[TYPE.label, { marginBottom: 8, color: theme.textMid }]}>{label}</Text>
      ) : null}
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: 10,
          paddingVertical: 14,
          paddingHorizontal: 16,
          backgroundColor: theme.card,
          borderRadius: AT.rL,
          borderWidth: error ? AT.ol3 : AT.ol2,
          borderColor: error ? AT.pnlRed : theme.outline,
        }}
      >
        {icon ? <View>{icon}</View> : null}
        <TextInput
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={theme.textSoft}
          secureTextEntry={secure && !show}
          autoCapitalize={autoCapitalize}
          autoComplete={autoComplete}
          autoCorrect={false}
          keyboardType={keyboardType}
          textContentType={textContentType}
          style={{
            flex: 1,
            fontSize: 16,
            fontWeight: '600',
            color: theme.text,
            fontFamily: monospace ? 'Courier' : undefined,
            letterSpacing: monospace ? 0.5 : 0,
            paddingVertical: 0,
          }}
        />
        {secure ? (
          <Pressable
            onPress={() => setShow(s => !s)}
            accessibilityRole="button"
            accessibilityLabel={show ? 'Hide value' : 'Show value'}
            hitSlop={10}
          >
            <Icon name={show ? 'eye' : 'eyeOff'} size={20} color={theme.textMid} />
          </Pressable>
        ) : null}
      </View>
      {hint ? (
        <Text
          style={{
            fontSize: 12,
            marginTop: 6,
            color: error ? AT.pnlRed : theme.textMid,
          }}
        >
          {hint}
        </Text>
      ) : null}
    </View>
  );
}
