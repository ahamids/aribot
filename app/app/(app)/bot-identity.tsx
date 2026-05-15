// Settings → Bot identity. Shows the pinned X25519 fingerprint, the
// current credential vault state on the bot, and admin actions:
//   - re-push credentials (navigates to a fresh entry of the vault form)
//   - wipe credentials on the bot (DELETE /credentials)
//   - unpin the bot's identity (force re-TOFU on next push)

import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Text, View } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { Screen } from '@/components/Screen';
import { Card } from '@/components/Card';
import { Btn } from '@/components/Btn';
import { Icon } from '@/components/Icon';
import { SectionLabel } from '@/components/SectionLabel';
import { Row } from '@/components/Row';
import { AT } from '@/theme/tokens';
import {
  fetchCredentialsStatus,
  forgetCredentialsOnBot,
  type CredentialsStatus,
} from '@/lib/botApi';
import { getPinnedBot, unpinBot } from '@/lib/crypto';

type PinState = { fingerprint: string; tlsCertSha256?: string | null } | null;

function MonoValue({ text }: { text: string }) {
  return (
    <Text style={{ fontSize: 12, fontFamily: 'Menlo', color: AT.plumMid, maxWidth: 160 }} numberOfLines={1}>
      {text}
    </Text>
  );
}

export default function BotIdentity() {
  const router = useRouter();
  const [pinned, setPinned] = useState<PinState>(null);
  const [vault, setVault] = useState<CredentialsStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    const p = await getPinnedBot();
    setPinned(p ? { fingerprint: p.fingerprint, tlsCertSha256: p.tlsCertSha256 } : null);
    const status = await fetchCredentialsStatus();
    if (status.ok) {
      setVault(status.data);
    } else {
      setVault(null);
      setError(status.error);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void refresh();
    }, [refresh]),
  );

  async function onWipe() {
    Alert.alert(
      'Wipe credentials on bot?',
      'The bot will refuse to start in LIVE mode until you push fresh credentials.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Wipe',
          style: 'destructive',
          onPress: async () => {
            setBusy(true);
            const r = await forgetCredentialsOnBot();
            setBusy(false);
            if (!r.ok) {
              Alert.alert('Could not wipe', r.error);
              return;
            }
            void refresh();
          },
        },
      ],
    );
  }

  async function onUnpin() {
    Alert.alert(
      'Unpin bot identity?',
      'Next connection will TOFU-pin whatever public key the host returns. Only do this if you intentionally rotated the bot keypair.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Unpin',
          style: 'destructive',
          onPress: async () => {
            await unpinBot();
            void refresh();
          },
        },
      ],
    );
  }

  return (
    <Screen title="Bot identity" showBack>
      <SectionLabel>PINNED HOST</SectionLabel>
      <Card padding={0} style={{ marginBottom: 16 }}>
        <Row
          left="X25519 fingerprint"
          right={<MonoValue text={pinned?.fingerprint ?? 'not pinned'} />}
          last={!pinned?.tlsCertSha256}
        />
        {pinned?.tlsCertSha256 ? (
          <Row
            left="TLS cert SHA-256"
            right={<MonoValue text={pinned.tlsCertSha256} />}
            last
          />
        ) : null}
      </Card>

      <SectionLabel>VAULT STATE</SectionLabel>
      <Card padding={0} style={{ marginBottom: 16 }}>
        <Row
          left="Loaded on bot"
          right={vault?.loaded ? 'yes' : vault === null ? 'unknown' : 'no'}
          last={!vault?.loaded}
        />
        {vault?.loaded ? (
          <>
            <Row left="Key fingerprint" right={<MonoValue text={vault.fingerprint ?? '—'} />} />
            <Row left="Source" right={vault.source ?? '—'} />
            <Row left="Validated" right={vault.validatedAtIso ?? '—'} last />
          </>
        ) : null}
      </Card>

      {error ? (
        <Card color={AT.pnlRedSoft} padding={12} style={{ marginBottom: 16 }}>
          <Text style={{ color: AT.plum, fontSize: 12 }}>{error}</Text>
        </Card>
      ) : null}

      <View style={{ gap: 10 }}>
        <Btn
          kind="primary"
          icon={<Icon name="lock" size={20} color="#fff" />}
          onPress={() => router.push('/(onboarding)/vault')}
        >
          Push new keys
        </Btn>
        <Btn
          kind="ghost"
          icon={<Icon name="x" size={18} color={AT.plum} />}
          loading={busy}
          onPress={onWipe}
        >
          Wipe credentials on bot
        </Btn>
        <Btn kind="ghost" onPress={onUnpin}>
          Unpin bot identity
        </Btn>
      </View>
    </Screen>
  );
}
