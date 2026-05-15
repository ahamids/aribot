// Bot connection setup. Pings GET /status on the user's VPS to verify the
// host + token before saving. Renders the same three states the design ships:
// idle (initial), success (green card), error (red card).

import React, { useState } from 'react';
import { Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Screen } from '@/components/Screen';
import { Btn } from '@/components/Btn';
import { Input } from '@/components/Input';
import { Card } from '@/components/Card';
import { Icon } from '@/components/Icon';
import { MascotSlot } from '@/mascot/MascotSlot';
import { AT } from '@/theme/tokens';
import {
  pingStatus,
  persistBotConnection,
  pinBotFromHost,
  type BotStatus,
} from '@/lib/botApi';

type CheckState = 'idle' | 'success' | 'error';

export default function BotSetup() {
  const router = useRouter();
  const [host, setHost] = useState('https://');
  const [token, setToken] = useState('');
  const [state, setState] = useState<CheckState>('idle');
  const [info, setInfo] = useState<BotStatus | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onPrimary() {
    if (state === 'success') {
      // "Continue" → persist host/token in SecureStore, TOFU-pin the bot's
      // X25519 identity, then advance to the vault screen which needs the
      // pin in place to seal credentials to the right pubkey.
      setBusy(true);
      try {
        await persistBotConnection({ hostUrl: host, bearerToken: token });
        const pinned = await pinBotFromHost(host);
        if (!pinned.ok) {
          setState('error');
          setErrorMsg(`Could not pin bot identity: ${pinned.error}`);
          return;
        }
        router.push('/(onboarding)/vault');
      } finally {
        setBusy(false);
      }
      return;
    }
    setBusy(true);
    setErrorMsg(null);
    const r = await pingStatus(host, token);
    setBusy(false);
    if (r.ok) {
      setInfo(r.data);
      setState('success');
    } else {
      setErrorMsg(r.error);
      setState('error');
    }
  }

  const pose = state === 'success' ? 'thumbsup' : state === 'error' ? 'questioning' : 'alert';

  return (
    <Screen title="Connect bot" showBack>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14, paddingTop: 4, paddingBottom: 20 }}>
        <MascotSlot size={70} pose={pose} tone="peri" />
        <Text style={{ flex: 1, fontSize: 14, color: AT.plumMid, lineHeight: 20 }}>
          Point the app at your Aribot server. It must be reachable over HTTPS.
        </Text>
      </View>

      <View style={{ gap: 14 }}>
        <Input
          label="HOST URL"
          value={host}
          onChangeText={setHost}
          placeholder="https://aribot.you.dev"
          monospace
          icon={<Icon name="server" size={18} color={AT.plumMid} />}
          autoCapitalize="none"
          keyboardType="url"
        />
        <Input
          label="BEARER TOKEN"
          value={token}
          onChangeText={setToken}
          placeholder="ari_pat_…"
          secure
          monospace
          autoCapitalize="none"
        />

        {state === 'success' && info ? (
          <Card color={AT.pnlGreenSoft} padding={14}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
              <View
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 16,
                  backgroundColor: AT.pnlGreen,
                  borderWidth: AT.ol2,
                  borderColor: AT.plum,
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Icon name="check" size={20} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ fontWeight: '800', fontSize: 14, color: AT.plum }}>
                  Connected · {info.version || 'unknown'}
                </Text>
                <Text style={{ fontSize: 12, color: AT.plumMid }}>
                  Mode: {info.mode ?? '—'} · status {info.status ?? '—'}
                </Text>
              </View>
            </View>
          </Card>
        ) : null}

        {state === 'error' ? (
          <Card color={AT.pnlRedSoft} padding={14}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
              <View
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 16,
                  backgroundColor: AT.pnlRed,
                  borderWidth: AT.ol2,
                  borderColor: AT.plum,
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Icon name="x" size={18} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ fontWeight: '800', fontSize: 14, color: AT.plum }}>
                  Couldn’t reach host
                </Text>
                <Text style={{ fontSize: 12, color: AT.plumMid }}>
                  {errorMsg ?? 'Check the URL and that /status is up.'}
                </Text>
              </View>
            </View>
          </Card>
        ) : null}

        <Btn
          kind="primary"
          icon={<Icon name="plug" size={20} color="#fff" />}
          loading={busy}
          onPress={onPrimary}
          disabled={!host.startsWith('http') || !token}
        >
          {state === 'success' ? 'Continue' : 'Test connection'}
        </Btn>
        <Btn kind="ghost" size="md" onPress={() => { /* future: help drawer */ }}>
          How do I find these?
        </Btn>
      </View>
    </Screen>
  );
}
