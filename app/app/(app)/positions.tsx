// Positions full screen — open + closed segmented, per-position cards with
// KV grid (size/mark/entry/leverage), pull-to-refresh, polling on focus.
//
// Per-card sparkline is a 2-point entry→mark line. The bot doesn't persist
// per-position price history, so a real sparkline would be misleading. The
// 2-point line is enough to communicate direction at a glance; a future pass
// could subscribe to a ticker stream for fuller curves.

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  Text,
  View,
} from 'react-native';
import { useFocusEffect } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Screen } from '@/components/Screen';
import { Card } from '@/components/Card';
import { Money } from '@/components/Money';
import { KV } from '@/components/KV';
import { Sparkline } from '@/components/Sparkline';
import { Segmented } from '@/components/Segmented';
import { SideChip } from '@/components/SideChip';
import { HostDownCard } from '@/components/states/HostDownCard';
import { KillActiveCard } from '@/components/states/KillActiveCard';
import { EmptyPositionsCard } from '@/components/states/EmptyPositionsCard';
import { MascotSlot } from '@/mascot/MascotSlot';
import { MProp } from '@/mascot/MProp';
import { AT } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import {
  fetchPositions,
  fetchStatus,
  fetchTrades,
  isHostDownError,
  type BotStatus,
  type ClosedTrade,
  type Position,
} from '@/lib/botApi';

const POLL_MS = 5000;
const VIEW_OPTIONS = ['Open', 'Closed'] as const;
type ViewMode = (typeof VIEW_OPTIONS)[number];

function fmtNum(v: number | null | undefined, max = 4): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return v.toLocaleString('en-US', { maximumFractionDigits: max });
}

function fmtAge(iso?: string | null): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${h}h ${String(m).padStart(2, '0')}m`;
}

export default function PositionsTab() {
  const insets = useSafeAreaInsets();
  const theme = useTheme();
  const [view, setView] = useState<ViewMode>('Open');
  const [open, setOpen] = useState<Position[] | null>(null);
  const [closed, setClosed] = useState<ClosedTrade[] | null>(null);
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hostDown, setHostDown] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reload = useCallback(async () => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    const [pos, tr, st] = await Promise.all([
      fetchPositions(ac.signal),
      fetchTrades(7, ac.signal),
      fetchStatus(ac.signal),
    ]);
    if (ac.signal.aborted) return;
    const failed = !pos.ok ? pos : !tr.ok ? tr : !st.ok ? st : null;
    if (failed) {
      setError(failed.error);
      setHostDown(isHostDownError(failed));
    } else {
      setError(null);
      setHostDown(false);
    }
    if (pos.ok) setOpen(pos.data.positions);
    if (tr.ok) setClosed(tr.data.trades);
    if (st.ok) setStatus(st.data);
  }, []);

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

  useEffect(() => () => abortRef.current?.abort(), []);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await reload();
    setRefreshing(false);
  }, [reload]);

  const openCount = open?.length ?? 0;
  const closedCount = closed?.length ?? 0;

  return (
    <Screen title="Positions" scroll={false}>
      <View style={{ flex: 1 }}>
        <View
          style={{
            paddingBottom: 12,
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Segmented
            options={VIEW_OPTIONS}
            value={view}
            onChange={setView}
          />
          <Text style={{ fontSize: 12, fontWeight: '800', color: theme.textMid, letterSpacing: 0.4 }}>
            {view === 'Open' ? `${openCount} OPEN` : `${closedCount} CLOSED · 7d`}
          </Text>
        </View>

        <ScrollView
          contentContainerStyle={{ paddingBottom: 120 + insets.bottom, gap: 14 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.text} />}
          showsVerticalScrollIndicator={false}
        >
          {hostDown && open === null && closed === null ? (
            <HostDownCard onRetry={reload} detail={error} />
          ) : status?.status === 'killed' ? (
            <KillActiveCard />
          ) : error && open === null && closed === null ? (
            <ErrorCard message={error} />
          ) : view === 'Open' ? (
            open === null ? (
              <LoadingCard />
            ) : open.length === 0 ? (
              <EmptyPositionsCard showCta />
            ) : (
              open.map((p, i) => <OpenCard key={`${p.symbol}-${i}`} p={p} />)
            )
          ) : closed === null ? (
            <LoadingCard />
          ) : closed.length === 0 ? (
            <EmptyClosed />
          ) : (
            closed.map((t, i) => <ClosedCard key={`${t.symbol}-${t.closedAtIso}-${i}`} t={t} />)
          )}
        </ScrollView>
      </View>
    </Screen>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Open position card
// ─────────────────────────────────────────────────────────────────────────────

function OpenCard({ p }: { p: Position }) {
  const theme = useTheme();
  // 2-point sparkline showing entry→mark. Sparkline auto-colors by direction;
  // for LONG we want green-if-mark>entry, red-if-mark<entry. The component
  // derives color from last vs first, which is exactly the right rule.
  const spark = p.mark != null && p.entry > 0 ? [p.entry, p.mark] : null;

  return (
    <Card padding={16}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Text style={{ fontSize: 18, fontWeight: '900', color: theme.text, letterSpacing: -0.3 }}>
            {p.symbol}
          </Text>
          <SideChip side={p.side} />
          {p.leverage ? (
            <View
              style={{
                paddingHorizontal: 8,
                paddingVertical: 2,
                borderRadius: AT.rPill,
                backgroundColor: theme.cardAlt,
              }}
            >
              <Text style={{ fontSize: 11, fontWeight: '800', color: theme.textMid }}>
                {p.leverage}x
              </Text>
            </View>
          ) : null}
        </View>
        <Money value={p.pnl} size={22} />
      </View>

      <View
        style={{
          flexDirection: 'row',
          flexWrap: 'wrap',
          rowGap: 8,
          columnGap: 14,
          marginBottom: 10,
        }}
      >
        <View style={{ width: '46%' }}><KV label="SIZE" value={fmtNum(p.size, 6)} /></View>
        <View style={{ width: '46%' }}><KV label="MARK" value={p.mark != null ? `$${fmtNum(p.mark)}` : '—'} /></View>
        <View style={{ width: '46%' }}><KV label="ENTRY" value={`$${fmtNum(p.entry)}`} /></View>
        <View style={{ width: '46%' }}>
          <KV
            label="P&L %"
            value={p.pnlPercent != null ? `${p.pnlPercent >= 0 ? '+' : ''}${p.pnlPercent.toFixed(2)}%` : '—'}
            danger={p.pnlPercent != null && p.pnlPercent < 0}
          />
        </View>
      </View>

      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingTop: 10,
          borderTopWidth: 1.5,
          borderStyle: 'dashed',
          borderColor: theme.divider,
        }}
      >
        <Text style={{ fontSize: 11, fontWeight: '700', color: theme.textMid, letterSpacing: 0.4 }}>
          OPEN {fmtAge(p.openedAtIso)}
        </Text>
        {spark ? (
          <Sparkline data={spark} width={120} height={28} />
        ) : (
          <Text style={{ fontSize: 10, color: theme.textSoft, fontStyle: 'italic' }}>no price stream</Text>
        )}
      </View>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Closed trade card — compact: symbol + side + reason + pnl + when
// ─────────────────────────────────────────────────────────────────────────────

function ClosedCard({ t }: { t: ClosedTrade }) {
  const theme = useTheme();
  return (
    <Card padding={14}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Text style={{ fontSize: 16, fontWeight: '900', color: theme.text }}>{t.symbol}</Text>
          <SideChip side={t.side} dense />
        </View>
        <Money value={t.pnl} size={18} />
      </View>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 6 }}>
        <Text style={{ fontSize: 11, color: theme.textMid }}>
          {t.reason ? t.reason.replace(/_/g, ' ').toLowerCase() : '—'}
        </Text>
        <Text style={{ fontSize: 11, color: theme.textMid }}>
          closed {fmtAge(t.closedAtIso)} ago
        </Text>
      </View>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Empty / loading / error states
// ─────────────────────────────────────────────────────────────────────────────

function LoadingCard() {
  const theme = useTheme();
  return (
    <Card padding={28} style={{ alignItems: 'center', gap: 12 }}>
      <ActivityIndicator color={theme.textMid} />
      <Text style={{ color: theme.textMid, fontSize: 12 }}>Loading positions…</Text>
    </Card>
  );
}

function EmptyClosed() {
  const theme = useTheme();
  return (
    <Card padding={24} style={{ alignItems: 'center', gap: 14 }}>
      <MascotSlot size={120} pose="napping" tone="yellow" prop={<MProp kind="chart" />} />
      <Text style={{ fontSize: 18, fontWeight: '900', color: theme.text, textAlign: 'center' }}>
        No closed trades yet
      </Text>
      <Text style={{ fontSize: 13, color: theme.textMid, textAlign: 'center', lineHeight: 18 }}>
        Last 7 days. Trades show up here as the bot closes them.
      </Text>
    </Card>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <Card color={AT.pnlRedSoft} padding={14}>
      {/* Card bg stays AT.pnlRedSoft per reservation rule; text on top reads
          in both modes against that pink-ish background. */}
      <Text style={{ fontWeight: '800', fontSize: 14, color: AT.plum, marginBottom: 4 }}>
        Can’t load positions
      </Text>
      <Text style={{ fontSize: 12, color: AT.plumMid }}>{message}</Text>
    </Card>
  );
}
