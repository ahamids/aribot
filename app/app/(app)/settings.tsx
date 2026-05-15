// Settings tab — Account / Bot / Mode / Safety / Notifications / About.
// Pass 4 rebuild: SectionLabel + Row primitives, complete Bot section,
// Account with red Sign-out row, Notifications (UI + AsyncStorage only —
// real push delivery is future work), expo-constants version footer.

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Text, View } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import Constants from 'expo-constants';
import { Screen } from '@/components/Screen';
import { Btn } from '@/components/Btn';
import { Card } from '@/components/Card';
import { Icon } from '@/components/Icon';
import { KillButton } from '@/components/KillButton';
import { ModeChip } from '@/components/ModeChip';
import { LiveConfirmSheet } from '@/components/LiveConfirmSheet';
import { SectionLabel } from '@/components/SectionLabel';
import { Row } from '@/components/Row';
import { Toggle } from '@/components/Toggle';
import { AT } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { useAuth } from '@/lib/auth';
import {
  clearBotConnection,
  clearKill,
  fetchStatus,
  getBotConnection,
  pingStatus,
  setBotMode,
  startBot,
  stopBot,
  tripKill,
  type BotConnection,
  type BotStatus,
} from '@/lib/botApi';
import {
  DEFAULT_PREFS,
  loadNotificationPrefs,
  saveNotificationPrefs,
  type NotificationPrefs,
} from '@/lib/notificationPrefs';

const SAFETY_POLL_MS = 5000;

type Mode = 'PAPER' | 'SHADOW' | 'LIVE';
type TestState = 'idle' | 'testing' | 'ok' | 'error';

function maskToken(t: string): string {
  if (!t) return '—';
  if (t.length <= 8) return '••••';
  return `${t.slice(0, 4)}…${t.slice(-4)}`;
}

function maskHost(h: string): string {
  if (!h) return '—';
  try {
    // Strip protocol + port to fit one line. Keep host so the user can
    // recognize their server at a glance.
    const url = new URL(h);
    return url.host;
  } catch {
    return h.length > 32 ? `${h.slice(0, 30)}…` : h;
  }
}

export default function SettingsTab() {
  const { user, signOut, setOnboardingDone } = useAuth();
  const router = useRouter();
  const theme = useTheme();

  const [status, setStatus] = useState<BotStatus | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [modeBusy, setModeBusy] = useState(false);
  const [modeError, setModeError] = useState<string | null>(null);
  const [modeProgress, setModeProgress] = useState<string | null>(null);
  const [pendingLiveSheet, setPendingLiveSheet] = useState(false);

  const [conn, setConn] = useState<BotConnection | null>(null);
  const [testState, setTestState] = useState<TestState>('idle');
  const [testError, setTestError] = useState<string | null>(null);

  const [prefs, setPrefs] = useState<NotificationPrefs>(DEFAULT_PREFS);

  const abortRef = useRef<AbortController | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reloadStatus = useCallback(async () => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    const r = await fetchStatus(ac.signal);
    if (ac.signal.aborted) return;
    if (r.ok) setStatus(r.data);
  }, []);

  useFocusEffect(
    useCallback(() => {
      let cancelled = false;
      const tick = async () => {
        if (cancelled) return;
        await reloadStatus();
        if (cancelled) return;
        pollTimer.current = setTimeout(tick, SAFETY_POLL_MS);
      };
      tick();
      return () => {
        cancelled = true;
        if (pollTimer.current) clearTimeout(pollTimer.current);
        abortRef.current?.abort();
      };
    }, [reloadStatus]),
  );

  // Load bot connection (in-memory) + notification prefs (AsyncStorage) once.
  useEffect(() => {
    (async () => {
      const c = await getBotConnection();
      setConn(c);
      const p = await loadNotificationPrefs(user?.id);
      setPrefs(p);
    })();
  }, [user?.id]);

  useEffect(() => () => abortRef.current?.abort(), []);

  function confirmSignOut() {
    Alert.alert(
      'Sign out?',
      'You can sign back in any time. Your encrypted keys stay on this device.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Sign out',
          style: 'destructive',
          onPress: async () => {
            clearBotConnection();
            await signOut();
          },
        },
      ],
    );
  }

  function confirmReconnect() {
    Alert.alert(
      'Reconnect bot?',
      'Takes you back through the bot connection + API key setup. Existing encrypted blobs in Supabase stay until you save new ones.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reconnect',
          onPress: async () => {
            clearBotConnection();
            await setOnboardingDone(false);
            router.replace('/(onboarding)/bot-setup');
          },
        },
      ],
    );
  }

  async function onKillHeld() {
    setActionBusy(true);
    const r = await tripKill();
    setActionBusy(false);
    if (!r.ok) {
      Alert.alert('Couldn’t trip kill switch', r.error);
      return;
    }
    await reloadStatus();
  }

  function onPressClearKill() {
    Alert.alert(
      'Clear kill switch?',
      'The bot can start again after this. It will not auto-start — you’ll need to start it from the dashboard.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Clear',
          onPress: async () => {
            setActionBusy(true);
            const r = await clearKill();
            setActionBusy(false);
            if (!r.ok) {
              Alert.alert('Couldn’t clear kill switch', r.error);
              return;
            }
            await reloadStatus();
          },
        },
      ],
    );
  }

  // Test connection row: pings /status using the cached host + bearer.
  async function onPressTestConnection() {
    if (!conn) {
      setTestState('error');
      setTestError('No bot connection saved.');
      return;
    }
    setTestState('testing');
    setTestError(null);
    const r = await pingStatus(conn.hostUrl, conn.bearerToken);
    if (r.ok) {
      setTestState('ok');
    } else {
      setTestState('error');
      setTestError(r.error);
    }
  }

  // Orchestrate stop → mode → start atomically.
  async function orchestrateModeSwitch(next: Mode) {
    setModeBusy(true);
    setModeError(null);

    const wasRunning = status?.status === 'running';

    if (wasRunning) {
      setModeProgress('Stopping bot…');
      const stopRes = await stopBot();
      if (!stopRes.ok) {
        setModeBusy(false);
        setModeProgress(null);
        setModeError(`Couldn’t stop bot: ${stopRes.error}`);
        return;
      }
      setModeProgress('Waiting for cycle end…');
      const stoppedOk = await pollUntil(
        async () => {
          const s = await fetchStatus();
          if (!s.ok) return false;
          return s.data.status !== 'running';
        },
        { timeoutMs: 90_000, intervalMs: 2_000 },
      );
      if (!stoppedOk) {
        setModeBusy(false);
        setModeProgress(null);
        setModeError('Bot didn’t stop in time. Trip the kill switch and try again.');
        return;
      }
      await clearKill();
    }

    setModeProgress('Updating mode…');
    const modeRes = await setBotMode(next);
    if (!modeRes.ok) {
      setModeBusy(false);
      setModeProgress(null);
      setModeError(`Couldn’t change mode: ${modeRes.error}`);
      return;
    }

    if (wasRunning) {
      setModeProgress('Starting bot…');
      const startRes = await startBot();
      if (!startRes.ok) {
        setModeBusy(false);
        setModeProgress(null);
        setModeError(
          `Mode is now ${next}, but couldn’t auto-restart the bot: ${startRes.error}. Start it from the dashboard.`,
        );
        return;
      }
    }

    setModeBusy(false);
    setModeProgress(null);
    await reloadStatus();
  }

  function onPressMode(next: Mode) {
    if (next === currentMode) return;
    if (next === 'LIVE') {
      setPendingLiveSheet(true);
      return;
    }
    Alert.alert(
      `Switch to ${next} mode?`,
      status?.status === 'running'
        ? `This will stop the bot, change the mode, then restart it. Open positions in ${currentMode} stay in the ${currentMode} ledger.`
        : `This will change the mode. The bot isn’t running, so no restart is needed.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: status?.status === 'running' ? 'Switch & restart' : 'Switch',
          onPress: () => orchestrateModeSwitch(next),
        },
      ],
    );
  }

  async function pollUntil(
    predicate: () => Promise<boolean>,
    opts: { timeoutMs: number; intervalMs: number },
  ): Promise<boolean> {
    const deadline = Date.now() + opts.timeoutMs;
    while (Date.now() < deadline) {
      if (await predicate()) return true;
      await new Promise(r => setTimeout(r, opts.intervalMs));
    }
    return false;
  }

  async function updatePref<K extends keyof NotificationPrefs>(
    key: K,
    value: NotificationPrefs[K],
  ) {
    const next = { ...prefs, [key]: value };
    setPrefs(next);
    await saveNotificationPrefs(next, user?.id);
  }

  const killed = status?.status === 'killed';
  const currentMode = (status?.mode ?? 'PAPER') as Mode;
  const botRunning = status?.status === 'running';

  const appVersion =
    Constants.expoConfig?.version ?? '0.0.0';
  const buildNumber =
    (Constants.expoConfig?.ios?.buildNumber as string | undefined) ??
    Constants.nativeBuildVersion ??
    'dev';

  // Test-connection right-side rendering: state-dependent badge.
  const testRight = (() => {
    if (testState === 'testing') {
      return (
        <Text style={{ fontSize: 13, color: theme.textMid }}>Testing…</Text>
      );
    }
    if (testState === 'ok') {
      return (
        <Text style={{ fontSize: 13, fontWeight: '800', color: AT.pnlGreen }}>
          ✓ OK
        </Text>
      );
    }
    if (testState === 'error') {
      return (
        <Text style={{ fontSize: 13, fontWeight: '800', color: AT.pnlRed }}>
          ✗ Failed
        </Text>
      );
    }
    return <Icon name="chevron" size={16} color={theme.textMid} />;
  })();

  return (
    <Screen title="Settings">
      <View style={{ paddingBottom: 100 }}>
        {/* ACCOUNT ─────────────────────────────────────────────────── */}
        <SectionLabel>ACCOUNT</SectionLabel>
        <Card padding={0} style={{ marginBottom: 14 }}>
          <Row left="Email" right={user?.email ?? 'Not signed in'} />
          <Row left="Plan" right="Personal" />
          <Row
            left="Sign out"
            right={
              <Text style={{ color: AT.pnlRed, fontSize: 18, fontWeight: '900' }}>›</Text>
            }
            danger
            last
            onPress={confirmSignOut}
          />
        </Card>

        {/* BOT ─────────────────────────────────────────────────────── */}
        <SectionLabel>BOT</SectionLabel>
        <Card padding={0} style={{ marginBottom: 14 }}>
          <Row left="Host URL" right={maskHost(conn?.hostUrl ?? '')} />
          <Row left="Bearer token" right={maskToken(conn?.bearerToken ?? '')} />
          <Row
            left="Test connection"
            right={testRight}
            onPress={onPressTestConnection}
          />
          <Row
            left="Bot identity & vault"
            right="›"
            onPress={() => router.push('/(app)/bot-identity')}
            last
          />
        </Card>
        {testState === 'error' && testError ? (
          <Text
            style={{
              marginTop: -8,
              marginBottom: 14,
              marginHorizontal: 4,
              fontSize: 11,
              color: AT.pnlRed,
              fontWeight: '600',
            }}
          >
            {testError}
          </Text>
        ) : null}
        <View style={{ marginBottom: 14, alignItems: 'flex-start', marginHorizontal: 4 }}>
          <Btn
            kind="soft"
            size="sm"
            icon={<Icon name="plug" size={16} color={theme.text} />}
            onPress={confirmReconnect}
          >
            Reconnect bot
          </Btn>
        </View>

        {/* MODE ────────────────────────────────────────────────────── */}
        <SectionLabel>MODE</SectionLabel>
        <Card padding={16} style={{ marginBottom: 14 }}>
          <Text style={{ fontSize: 12, color: theme.textMid, marginBottom: 12, lineHeight: 17 }}>
            Currently <Text style={{ color: theme.text, fontWeight: '800' }}>{currentMode}</Text>
            {botRunning ? ' · bot is running, stop it first to change' : ''}
          </Text>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <ModeChip mode="PAPER" active={currentMode === 'PAPER'} onPress={() => onPressMode('PAPER')} />
            <ModeChip mode="SHADOW" active={currentMode === 'SHADOW'} onPress={() => onPressMode('SHADOW')} />
            <ModeChip mode="LIVE" active={currentMode === 'LIVE'} onPress={() => onPressMode('LIVE')} />
          </View>
          {currentMode === 'LIVE' ? (
            <View
              style={{
                marginTop: 12,
                paddingHorizontal: 12,
                paddingVertical: 10,
                backgroundColor: AT.pnlRedSoft,
                borderRadius: AT.rM,
                borderWidth: 2,
                borderColor: AT.pnlRed,
                flexDirection: 'row',
                gap: 8,
                alignItems: 'flex-start',
              }}
            >
              <Text style={{ fontSize: 14 }}>⚠</Text>
              <Text style={{ flex: 1, fontSize: 12, color: AT.plum, lineHeight: 17, fontWeight: '600' }}>
                LIVE places real orders on Bybit. Requires typed confirmation each time the bot starts.
              </Text>
            </View>
          ) : null}
          {modeError ? (
            <Text style={{ marginTop: 10, fontSize: 12, color: AT.pnlRed, fontWeight: '600' }}>
              {modeError}
            </Text>
          ) : null}
          {modeProgress ? (
            <Text style={{ marginTop: 8, fontSize: 11, color: theme.textMid, fontWeight: '600' }}>
              {modeProgress}
            </Text>
          ) : null}
        </Card>

        {/* SAFETY ─────────────────────────────────────────────────── */}
        <SectionLabel>SAFETY</SectionLabel>
        <Card padding={16} style={{ marginBottom: 14 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
            <View style={{ flex: 1 }}>
              <Text style={{ fontWeight: '900', fontSize: 15, color: theme.text }}>
                Kill switch
              </Text>
              <Text style={{ fontSize: 12, color: theme.textMid, lineHeight: 18, marginTop: 2 }}>
                {killed
                  ? 'Tripped. The bot is refusing to take new orders.'
                  : 'Hold to stop the bot at the next cycle. Tap won’t fire.'}
              </Text>
            </View>
            {killed ? (
              <Btn kind="soft" size="sm" onPress={onPressClearKill} disabled={actionBusy}>
                Clear
              </Btn>
            ) : (
              <KillButton onConfirm={onKillHeld} disabled={actionBusy} />
            )}
          </View>
        </Card>

        {/* NOTIFICATIONS ──────────────────────────────────────────── */}
        <SectionLabel>NOTIFICATIONS</SectionLabel>
        <Card padding={0} style={{ marginBottom: 6 }}>
          <Row
            left="Fill alerts"
            right={
              <Toggle
                value={prefs.fillAlerts}
                onValueChange={v => updatePref('fillAlerts', v)}
                accessibilityLabel="Fill alerts"
              />
            }
          />
          <Row
            left="Error alerts"
            right={
              <Toggle
                value={prefs.errorAlerts}
                onValueChange={v => updatePref('errorAlerts', v)}
                accessibilityLabel="Error alerts"
              />
            }
          />
          <Row
            left="Daily summary"
            right={
              <Toggle
                value={prefs.dailySummary}
                onValueChange={v => updatePref('dailySummary', v)}
                accessibilityLabel="Daily summary"
              />
            }
            last
          />
        </Card>
        <Text
          style={{
            marginBottom: 14,
            marginHorizontal: 4,
            fontSize: 11,
            color: theme.textSoft,
            lineHeight: 15,
          }}
        >
          Preferences only — push delivery ships in a later pass. Toggles persist here so the
          choices survive your next sign-in.
        </Text>

        {/* ABOUT ─────────────────────────────────────────────────── */}
        <Text
          style={{
            textAlign: 'center',
            marginTop: 18,
            fontSize: 11,
            color: theme.textMid,
            fontWeight: '600',
          }}
        >
          Aribot · v{appVersion} · build {buildNumber}
        </Text>
      </View>

      <LiveConfirmSheet
        visible={pendingLiveSheet}
        busy={modeBusy}
        onDismiss={() => setPendingLiveSheet(false)}
        onConfirm={async () => {
          setPendingLiveSheet(false);
          await orchestrateModeSwitch('LIVE');
        }}
      />
    </Screen>
  );
}
