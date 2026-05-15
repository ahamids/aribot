// API key vault. Trust-moment screen: keys are sealed-box encrypted on this
// device before upload. Even the server can't read them. The crypto in
// lib/crypto.ts makes that claim real, not just copy.

import React, { useState } from 'react';
import { Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Screen } from '@/components/Screen';
import { Btn } from '@/components/Btn';
import { Input } from '@/components/Input';
import { Card } from '@/components/Card';
import { Icon } from '@/components/Icon';
import { MascotSlot } from '@/mascot/MascotSlot';
import { MProp } from '@/mascot/MProp';
import { AT } from '@/theme/tokens';
import { saveApiKeysToBot } from '@/lib/vault';
import { useAuth } from '@/lib/auth';

export default function ApiVault() {
  const router = useRouter();
  const { setOnboardingDone } = useAuth();
  const [readKey, setReadKey] = useState('');
  const [readSecret, setReadSecret] = useState('');
  const [tradeKey, setTradeKey] = useState('');
  const [tradeSecret, setTradeSecret] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedOk, setSavedOk] = useState(false);

  const canSubmit =
    readKey.length > 8 && readSecret.length > 8 && tradeKey.length > 8 && tradeSecret.length > 8 && !busy;

  async function save() {
    setBusy(true);
    setError(null);
    // Push directly to the user's bot. The bot validates against Bybit
    // (/v5/user/query-api) and only stores keys that pass — wrong keys
    // surface here as the Bybit retMsg.
    const r = await saveApiKeysToBot({ readKey, readSecret, tradeKey, tradeSecret });
    if (!r.ok) {
      setError(r.error);
      setBusy(false);
      return;
    }
    setSavedOk(true);
    await setOnboardingDone(true);
    setBusy(false);
    router.replace('/(onboarding)/done');
  }

  return (
    <Screen title="Bybit keys" showBack>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14, paddingBottom: 16 }}>
        <MascotSlot size={80} pose="serious" tone="yellow" prop={<MProp kind="vault" />} />
        <View style={{ flex: 1 }}>
          <Text style={{ fontWeight: '900', fontSize: 17, letterSpacing: -0.2, color: AT.plum }}>
            Encrypted on this device.
          </Text>
          <Text style={{ fontSize: 13, color: AT.plumMid, lineHeight: 18 }}>
            We seal with a key only your phone holds. Even we can’t read these.
          </Text>
        </View>
      </View>

      <Card color={AT.peri} padding={14} style={{ marginBottom: 14 }}>
        <View style={{ flexDirection: 'row', gap: 10, alignItems: 'flex-start' }}>
          <View
            style={{
              width: 28,
              height: 28,
              borderRadius: 14,
              backgroundColor: '#fff',
              borderWidth: AT.ol2,
              borderColor: AT.plum,
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Icon name="lock" size={16} color={AT.plum} />
          </View>
          <Text style={{ flex: 1, fontSize: 13, lineHeight: 20, color: '#fff', fontWeight: '600' }}>
            <Text style={{ fontWeight: '900' }}>Sealed-box</Text> ciphertext is sent directly to your bot.
            We never see it. Bot decrypts in memory and discards the bytes on stop.
          </Text>
        </View>
      </Card>

      <View style={{ gap: 12 }}>
        <Text style={{ fontSize: 11, fontWeight: '800', letterSpacing: 0.8, color: AT.plumMid, marginLeft: 4 }}>
          READ-ONLY KEY · for status &amp; positions
        </Text>
        <Input
          label="READ API KEY"
          value={readKey}
          onChangeText={setReadKey}
          monospace
          secure
          placeholder="K-rO8X-…"
        />
        <Input
          label="READ SECRET"
          value={readSecret}
          onChangeText={setReadSecret}
          monospace
          secure
          placeholder="rs_…"
        />

        <Text style={{ fontSize: 11, fontWeight: '800', letterSpacing: 0.8, color: AT.plumMid, marginLeft: 4, marginTop: 10 }}>
          TRADE KEY · scoped to USDT perps
        </Text>
        <Input
          label="TRADE API KEY"
          value={tradeKey}
          onChangeText={setTradeKey}
          monospace
          secure
          placeholder="K-tR3K-…"
        />
        <Input
          label="TRADE SECRET"
          value={tradeSecret}
          onChangeText={setTradeSecret}
          monospace
          secure
          placeholder="ts_…"
        />

        {error ? (
          <Card color={AT.pnlRedSoft} padding={12}>
            <Text style={{ color: AT.plum, fontWeight: '700', fontSize: 13 }}>Couldn’t save.</Text>
            <Text style={{ color: AT.plumMid, fontSize: 12, marginTop: 2 }}>{error}</Text>
          </Card>
        ) : null}

        <Btn
          kind="primary"
          icon={<Icon name="lock" size={20} color="#fff" />}
          onPress={save}
          loading={busy}
          disabled={!canSubmit}
          style={{ marginTop: 8 }}
        >
          {savedOk ? 'Encrypted ✓' : 'Encrypt & save'}
        </Btn>
      </View>
    </Screen>
  );
}
