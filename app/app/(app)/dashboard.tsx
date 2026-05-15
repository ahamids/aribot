// Dashboard — the lead screen. Status card with mascot + start/stop button,
// today's PnL with sparkline, open positions preview. Live data from the
// sidecar with a poll loop on focus.
//
// Polling cadence: 5s while focused, paused when blurred. Aggressive but
// the sidecar is local, payloads are <2KB, and a trader expects "live"
// numbers to actually be live. Polls cancel via AbortController on unmount
// so we don't have orphan requests.

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { AT } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import { Card } from '@/components/Card';
import { Btn } from '@/components/Btn';
import { Icon } from '@/components/Icon';
import { StatusPill } from '@/components/StatusPill';
import { ModeChip } from '@/components/ModeChip';
import { Money } from '@/components/Money';
import { Sparkline } from '@/components/Sparkline';
import { PositionRow } from '@/components/PositionRow';
import { LiveConfirmSheet } from '@/components/LiveConfirmSheet';
import { GradientFill } from '@/components/GradientFill';
import { HostDownCard } from '@/components/states/HostDownCard';
import { KillActiveCard } from '@/components/states/KillActiveCard';
import { EmptyPositionsCard } from '@/components/states/EmptyPositionsCard';
import { MascotSlot } from '@/mascot/MascotSlot';
import {
  fetchEquity,
  fetchPositions,
  fetchStatus,
  isHostDownError,
  startBot,
  stopBot,
  type BotStatus,
  type EquityResponse,
  type PositionsResponse,
} from '@/lib/botApi';
import { useAuth } from '@/lib/auth';

const POLL_MS = 5000;

function relativeTime(iso?: string | null): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const secs = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const m = Math.round(secs / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

export default function Dashboard() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const theme = useTheme();

  const [status, setStatus] = useState<BotStatus | null>(null);
  const [positions, setPositions] = useState<PositionsResponse | null>(null);
  const [equity, setEquity] = useState<EquityResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [showLiveConfirm, setShowLiveConfirm] = useState(false);

  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [needsReconnect, setNeedsReconnect] = useState(false);
  const [hostDown, setHostDown] = useState(false);

  const reload = useCallback(async () => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    const [s, p, e] = await Promise.all([
      fetchStatus(ac.signal),
      fetchPositions(ac.signal),
      fetchEquity(1, ac.signal),
    ]);
    if (ac.signal.aborted) return;

    // Pick the first failed call. Usually all three fail together (host down).
    // We track three flavors of failure so the UI can render the right state:
    //   - "no connection saved" → reconnect CTA
    //   - host-down (no HTTP status, transport-level) → HostDownCard
    //   - HTTP error (401, 500) → inline error card
    const failed = !s.ok ? s : !p.ok ? p : !e.ok ? e : null;
    if (failed) {
      setLoadError(failed.error);
      setNeedsReconnect(failed.error.startsWith('No bot connection saved'));
      setHostDown(isHostDownError(failed) && !failed.error.startsWith('No bot connection saved'));
    } else {
      setLoadError(null);
      setNeedsReconnect(false);
      setHostDown(false);
    }
    if (s.ok) setStatus(s.data);
    if (p.ok) setPositions(p.data);
    if (e.ok) setEquity(e.data);
  }, []);

  // Polling driven by focus — runs while this tab is visible, stops when not.
  useFocusEffect(
    useCallback(() => {
      let cancelled = false;
      const tick = async () => {
        if (cancelled) return;
        await reload();
        if (cancelled) return;
        pollTimer.current = setTimeout(tick, POLL_MS);
      };
      tick();
      return () => {
        cancelled = true;
        if (pollTimer.current) clearTimeout(pollTimer.current);
        abortRef.current?.abort();
      };
    }, [reload]),
  );

  // Aborter on unmount as well.
  useEffect(() => () => abortRef.current?.abort(), []);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await reload();
    setRefreshing(false);
  }, [reload]);

  async function actuallyStart() {
    setActionBusy(true);
    const r = await startBot();
    setActionBusy(false);
    setShowLiveConfirm(false);
    if (!r.ok) {
      Alert.alert('Couldn’t start bot', r.error);
      return;
    }
    // Force a fresh fetch so the status pill flips quickly.
    await reload();
  }

  function onPressStart() {
    if (status?.mode === 'LIVE') {
      setShowLiveConfirm(true);
      return;
    }
    actuallyStart();
  }

  function onPressStop() {
    Alert.alert(
      'Stop the bot?',
      'Writes kill_switch.flag. The bot exits cleanly at its next cycle.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Stop',
          style: 'destructive',
          onPress: async () => {
            setActionBusy(true);
            const r = await stopBot();
            setActionBusy(false);
            if (!r.ok) Alert.alert('Couldn’t stop bot', r.error);
            await reload();
          },
        },
      ],
    );
  }

  const st = status?.status ?? 'stopped';
  const mode = status?.mode ?? 'PAPER';
  const mascotPose =
    st === 'running' ? 'alert'
    : st === 'error' ? 'panicked'
    : st === 'killed' ? 'panicked'
    : 'sleeping';

  // Equity sparkline data — extract from the equity response when present.
  // Fall back to a 2-point line at current balance so layout stays stable.
  const equityNumbers =
    equity?.points && equity.points.length >= 2
      ? equity.points.map(p => p.equity)
      : [status?.currentBalance ?? 0, status?.currentBalance ?? 0];

  const pnlToday = status?.todaysPnl ?? 0;
  const equityNow = status?.currentBalance ?? 0;
  const pnlPercent = equityNow > 0 ? (pnlToday / Math.max(1, equityNow - pnlToday)) * 100 : 0;

  // Initial-load skeleton — only show when we genuinely have no data yet.
  const isInitialLoad = status === null && positions === null && equity === null && loadError === null;

  return (
    <View style={{ flex: 1, backgroundColor: theme.bg }}>
      <ScrollView
        contentContainerStyle={{
          paddingTop: insets.top + 4,
          paddingHorizontal: 18,
          paddingBottom: 120, // clears the floating tab bar
        }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.text} />}
        showsVerticalScrollIndicator={false}
      >
        {/* GREETING + MODE */}
        <View
          style={{
            paddingVertical: 14,
            paddingHorizontal: 6,
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <View>
            <Text style={{ fontSize: 13, fontWeight: '700', color: theme.textMid, letterSpacing: 0.4 }}>
              HI THERE
            </Text>
            <Text style={{ fontSize: 26, fontWeight: '900', letterSpacing: -0.5, color: theme.text }}>
              {user?.email?.split('@')[0] ?? 'Aribot'}
            </Text>
          </View>
          <ModeChip mode={mode} />
        </View>

        {/* NEEDS RECONNECT — happens when the user closes/reopens the app
            after onboarding; the bot connection lives only in memory in this
            pass. Future work: decrypt from Supabase via sealed-box on launch. */}
        {needsReconnect ? (
          <Card padding={20} style={{ alignItems: 'center', gap: 12, marginBottom: 18 }}>
            <MascotSlot size={100} pose="questioning" tone="peri" />
            <Text style={{ fontSize: 18, fontWeight: '900', color: theme.text, textAlign: 'center' }}>
              Reconnect your bot
            </Text>
            <Text style={{ fontSize: 13, color: theme.textMid, textAlign: 'center', lineHeight: 18 }}>
              Bot connection isn’t loaded in this session. Quick fix: re-run the connection setup.
            </Text>
            <Btn
              kind="primary"
              size="md"
              icon={<Icon name="plug" size={18} color="#fff" />}
              onPress={() => router.push('/(onboarding)/bot-setup')}
            >
              Reconnect bot
            </Btn>
          </Card>
        ) : null}

        {/* INITIAL LOAD */}
        {isInitialLoad && !needsReconnect ? (
          <Card padding={28} style={{ alignItems: 'center', marginBottom: 18 }}>
            <ActivityIndicator color={theme.text} />
            <Text style={{ marginTop: 12, color: theme.textMid }}>Connecting to bot…</Text>
          </Card>
        ) : null}

        {/* STATUS CARD — vertical gradient fades the tone color into the
            card surface at 70%, matching the design's
            linear-gradient(180deg, <tone>, paper 70%). */}
        <Card padding={0} style={{ overflow: 'hidden', marginBottom: 18 }}>
          <View style={{ padding: 18 }}>
            <GradientFill
              from={
                st === 'running' ? AT.mint
                : st === 'error' || st === 'killed' ? AT.pnlRedSoft
                : AT.creamDeep
              }
              to={theme.card}
            />
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <MascotSlot size={92} pose={mascotPose} tone={st === 'running' ? 'yellow' : 'cream'} />
              <View style={{ flex: 1, gap: 10 }}>
                <StatusPill status={st} mode={mode} />
                <Text style={{ fontSize: 13, fontWeight: '600', color: theme.textMid }}>
                  {st === 'running'
                    ? `Last cycle ${relativeTime(status?.lastCycleIso)}`
                    : st === 'killed'
                      ? 'Kill switch tripped'
                      : st === 'error'
                        ? `Last cycle ${relativeTime(status?.lastCycleIso)} · ${status?.reason ?? 'check sidecar logs'}`
                        : 'Bot stopped'}
                </Text>
              </View>
            </View>

            <View style={{ marginTop: 18 }}>
              {st === 'running' ? (
                <Btn
                  kind="danger"
                  size="lg"
                  icon={<Icon name="x" size={20} color="#fff" />}
                  loading={actionBusy}
                  onPress={onPressStop}
                >
                  STOP BOT
                </Btn>
              ) : st === 'killed' ? (
                <Btn kind="ghost" size="lg" disabled>
                  KILL SWITCH ACTIVE
                </Btn>
              ) : (
                <Btn
                  kind="primary"
                  size="lg"
                  icon={<Icon name="bolt" size={20} color="#fff" />}
                  loading={actionBusy}
                  onPress={onPressStart}
                >
                  START BOT
                </Btn>
              )}
            </View>
          </View>
        </Card>

        {/* HOST-DOWN — replaces the flat red toast from the previous pass. */}
        {hostDown && status === null ? (
          <View style={{ marginBottom: 18 }}>
            <HostDownCard onRetry={reload} detail={loadError} />
          </View>
        ) : null}

        {/* NON-HOST HTTP ERROR — keep a flat card; HostDownCard is for transport
            failures specifically. This catches 401 tokens, 5xx sidecar bugs, etc. */}
        {loadError && !hostDown && !needsReconnect && status === null ? (
          <Card color={AT.pnlRedSoft} padding={14} style={{ marginBottom: 18 }}>
            {/* Card color stays AT.pnlRedSoft (reservation rule). The text on
                top of it reads well in both modes against that pink-ish bg,
                so AT.plum / AT.plumMid here are also intentional and stay. */}
            <Text style={{ fontWeight: '800', fontSize: 14, color: AT.plum, marginBottom: 2 }}>
              Bot rejected the request
            </Text>
            <Text style={{ fontSize: 12, color: AT.plumMid }}>{loadError}</Text>
          </Card>
        ) : null}

        {/* PNL CARD */}
        <Card style={{ marginBottom: 18 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 6 }}>
            <Text style={{ fontSize: 12, fontWeight: '800', letterSpacing: 0.8, color: theme.textMid }}>
              TODAY’S PNL
            </Text>
            <Text style={{ fontSize: 11, color: theme.textMid }}>
              EQUITY ${equityNow.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </Text>
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 12 }}>
            <Money value={pnlToday} size={48} />
            <Text
              style={{
                fontSize: 16,
                fontWeight: '700',
                color: pnlToday >= 0 ? AT.pnlGreen : AT.pnlRed,
              }}
            >
              {pnlToday >= 0 ? '+' : '−'}
              {Math.abs(pnlPercent).toFixed(2)}%
            </Text>
          </View>
          <View style={{ marginTop: 10, marginLeft: -4 }}>
            <Sparkline data={equityNumbers} width={320} height={56} />
          </View>
        </Card>

        {/* POSITIONS PREVIEW */}
        <Card>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 }}>
            <Text style={{ fontSize: 12, fontWeight: '800', letterSpacing: 0.8, color: theme.textMid }}>
              OPEN POSITIONS · {positions?.positions.length ?? 0}
            </Text>
            <Text
              style={{ fontSize: 13, fontWeight: '800', color: AT.coralDeep }}
              onPress={() => router.push('/(app)/positions')}
            >
              See all ›
            </Text>
          </View>
          {positions === null ? (
            <View style={{ paddingVertical: 18, alignItems: 'center' }}>
              <ActivityIndicator color={theme.textMid} />
            </View>
          ) : positions.positions.length === 0 ? (
            // Inline (no CTA): the dashboard's START BOT button lives directly
            // above this card, so a "Wake the bot" CTA would be redundant. The
            // Positions full screen uses showCta because its context is different.
            <View style={{ paddingTop: 6 }}>
              <EmptyPositionsCard />
            </View>
          ) : (
            positions.positions.slice(0, 3).map((p, i, arr) => (
              <PositionRow
                key={`${p.symbol}-${i}`}
                p={{
                  symbol: p.symbol,
                  side: p.side,
                  size: p.size.toFixed(4).replace(/\.?0+$/, ''),
                  entry: p.entry.toLocaleString('en-US', { maximumFractionDigits: 4 }),
                  mark: p.mark != null ? p.mark.toLocaleString('en-US', { maximumFractionDigits: 4 }) : undefined,
                  pnl: p.pnl,
                }}
                hideDivider={i === arr.length - 1}
              />
            ))
          )}
        </Card>

        {/* TINY DECORATIVE FOOTER — bot version + cycle count when we have it */}
        {status ? (
          <Text style={{ fontSize: 10, color: theme.textSoft, textAlign: 'center', marginTop: 20 }}>
            bot {status.runId?.slice(0, 8) ?? '—'} · cycle {status.cycleCount ?? 0} · sidecar {status.version}
          </Text>
        ) : null}
      </ScrollView>

      <LiveConfirmSheet
        visible={showLiveConfirm}
        busy={actionBusy}
        onDismiss={() => setShowLiveConfirm(false)}
        onConfirm={actuallyStart}
      />
    </View>
  );
}
