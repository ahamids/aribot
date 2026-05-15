// History — Trades / Equity segmented views.
//
// Trades view: closed trades from /trades?days=7, grouped by date label in the
// device's local timezone. Each row is symbol + side chip + reason on the left,
// color-coded PnL right-aligned. Dashed dividers between rows in a group.
//
// Equity view: 7-day equity curve + summary stats card (win rate / trades /
// avg win / avg loss). The bot doesn't persist per-minute equity, so the
// curve is stepped per closed trade — see EquityChart's notes.

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { Segmented } from '@/components/Segmented';
import { SideChip } from '@/components/SideChip';
import { Money } from '@/components/Money';
import { KV } from '@/components/KV';
import { EquityChart } from '@/components/EquityChart';
import { HostDownCard } from '@/components/states/HostDownCard';
import { KillActiveCard } from '@/components/states/KillActiveCard';
import { EmptyTradesCard } from '@/components/states/EmptyTradesCard';
import { ChartEmptyCard } from '@/components/states/ChartEmptyCard';
import { AT } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';
import {
  fetchEquity,
  fetchStatus,
  fetchTrades,
  isHostDownError,
  type BotStatus,
  type ClosedTrade,
  type EquityResponse,
} from '@/lib/botApi';

const POLL_MS = 10000; // historical data is less hot than the dashboard
const VIEW_OPTIONS = ['Trades', 'Equity'] as const;
type ViewMode = (typeof VIEW_OPTIONS)[number];

// ─────────────────────────────────────────────────────────────────────────────
// Grouping helpers — bucket trades by local-timezone date label.
// ─────────────────────────────────────────────────────────────────────────────

function dateLabelFor(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'UNKNOWN';
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);
  if (d >= startOfToday) return 'Today';
  if (d >= startOfYesterday) return 'Yesterday';
  // Older — show "Mon May 5" style label
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

function timeFmt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

function groupTrades(trades: ClosedTrade[]): { label: string; rows: ClosedTrade[] }[] {
  const buckets = new Map<string, ClosedTrade[]>();
  for (const t of trades) {
    const k = dateLabelFor(t.closedAtIso);
    const arr = buckets.get(k) ?? [];
    arr.push(t);
    buckets.set(k, arr);
  }
  // Preserve insertion order — trades are newest-first, so the iteration
  // gives Today → Yesterday → older dates, which is what we want.
  return Array.from(buckets.entries()).map(([label, rows]) => ({ label, rows }));
}

// ─────────────────────────────────────────────────────────────────────────────
// Main screen
// ─────────────────────────────────────────────────────────────────────────────

export default function HistoryTab() {
  const insets = useSafeAreaInsets();
  const theme = useTheme();
  const [view, setView] = useState<ViewMode>('Trades');
  const [trades, setTrades] = useState<ClosedTrade[] | null>(null);
  const [equity, setEquity] = useState<EquityResponse | null>(null);
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

    const [tr, eq, st] = await Promise.all([
      fetchTrades(7, ac.signal),
      fetchEquity(7, ac.signal),
      fetchStatus(ac.signal),
    ]);
    if (ac.signal.aborted) return;
    const failed = !tr.ok ? tr : !eq.ok ? eq : !st.ok ? st : null;
    if (failed) {
      setError(failed.error);
      setHostDown(isHostDownError(failed));
    } else {
      setError(null);
      setHostDown(false);
    }
    if (tr.ok) setTrades(tr.data.trades);
    if (eq.ok) setEquity(eq.data);
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

  const grouped = useMemo(() => (trades ? groupTrades(trades) : []), [trades]);

  return (
    <Screen title="History" scroll={false}>
      <View style={{ flex: 1 }}>
        <View style={{ alignItems: 'center', paddingBottom: 14 }}>
          <Segmented options={VIEW_OPTIONS} value={view} onChange={setView} />
        </View>

        <ScrollView
          contentContainerStyle={{ paddingBottom: 120 + insets.bottom, gap: 14 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.text} />}
          showsVerticalScrollIndicator={false}
        >
          {hostDown && trades === null && equity === null ? (
            <HostDownCard onRetry={reload} detail={error} />
          ) : status?.status === 'killed' ? (
            <KillActiveCard />
          ) : error && trades === null && equity === null ? (
            <ErrorCard message={error} />
          ) : view === 'Trades' ? (
            trades === null ? (
              <LoadingCard />
            ) : grouped.length === 0 ? (
              <EmptyTradesCard />
            ) : (
              grouped.map(g => <TradeGroup key={g.label} label={g.label} rows={g.rows} />)
            )
          ) : equity === null ? (
            // Equity view's initial-load placeholder is the mascot card,
            // not the spinner. Trades view keeps the spinner above —
            // initial-load is the only place these diverge.
            <ChartEmptyCard />
          ) : (
            <EquityView eq={equity} />
          )}
        </ScrollView>
      </View>
    </Screen>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Trades view — date-grouped list
// ─────────────────────────────────────────────────────────────────────────────

function TradeGroup({ label, rows }: { label: string; rows: ClosedTrade[] }) {
  const theme = useTheme();
  return (
    <View>
      <Text
        style={{
          fontSize: 11,
          fontWeight: '800',
          letterSpacing: 0.7,
          color: theme.textMid,
          marginBottom: 8,
          marginHorizontal: 4,
        }}
      >
        {label.toUpperCase()}
      </Text>
      <Card padding={0}>
        {rows.map((t, i) => (
          <TradeRow key={`${t.symbol}-${t.closedAtIso}-${i}`} t={t} last={i === rows.length - 1} />
        ))}
      </Card>
    </View>
  );
}

function TradeRow({ t, last }: { t: ClosedTrade; last: boolean }) {
  const theme = useTheme();
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingVertical: 14,
        paddingHorizontal: 16,
        borderBottomWidth: last ? 0 : 1.5,
        borderBottomColor: theme.divider,
        borderStyle: 'dashed',
      }}
    >
      <View style={{ flex: 1, gap: 4 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Text style={{ fontSize: 15, fontWeight: '900', color: theme.text }}>{t.symbol}</Text>
          <SideChip side={t.side} dense />
        </View>
        <Text style={{ fontSize: 11, color: theme.textMid }}>
          {timeFmt(t.closedAtIso)}
          {t.reason ? ` · ${t.reason.replace(/_/g, ' ').toLowerCase()}` : ''}
        </Text>
      </View>
      <Money value={t.pnl} size={18} />
    </View>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Equity view — chart + stats
// ─────────────────────────────────────────────────────────────────────────────

function EquityView({ eq }: { eq: EquityResponse }) {
  const theme = useTheme();
  const data = eq.points.map(p => p.equity);
  const pnl = eq.stats.pnlAbs;
  const pct = eq.stats.pnlPercent;
  const wr = eq.stats.winRate;

  return (
    <View style={{ gap: 14 }}>
      <Card>
        <Text style={{ fontSize: 11, fontWeight: '800', letterSpacing: 0.7, color: theme.textMid }}>
          7-DAY EQUITY
        </Text>
        <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 10, marginTop: 2 }}>
          <Money value={pnl} size={36} />
          {pct != null ? (
            <Text style={{ fontSize: 13, color: pnl >= 0 ? AT.pnlGreen : AT.pnlRed, fontWeight: '800' }}>
              {pnl >= 0 ? '+' : ''}{pct.toFixed(2)}%
            </Text>
          ) : null}
        </View>
        <View style={{ marginTop: 16, marginLeft: -6 }}>
          <EquityChart data={data} width={320} height={160} />
        </View>
      </Card>

      <Card padding={16}>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', rowGap: 12, columnGap: 10 }}>
          <View style={{ width: '46%' }}>
            <KV
              label="WIN RATE"
              value={wr != null ? `${Math.round(wr * 100)}%` : '—'}
            />
          </View>
          <View style={{ width: '46%' }}>
            <KV label="TRADES" value={String(eq.stats.tradeCount)} />
          </View>
          <View style={{ width: '46%' }}>
            <KV
              label="AVG WIN"
              value={eq.stats.avgWin != null ? `+$${eq.stats.avgWin.toFixed(2)}` : '—'}
            />
          </View>
          <View style={{ width: '46%' }}>
            <KV
              label="AVG LOSS"
              value={eq.stats.avgLoss != null ? `−$${Math.abs(eq.stats.avgLoss).toFixed(2)}` : '—'}
              danger={eq.stats.avgLoss != null}
            />
          </View>
        </View>
      </Card>

      {eq.note ? (
        <Text style={{ fontSize: 10, color: theme.textSoft, textAlign: 'center', paddingHorizontal: 20, lineHeight: 14 }}>
          {eq.note}
        </Text>
      ) : null}
    </View>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Empty / loading / error
// ─────────────────────────────────────────────────────────────────────────────

function LoadingCard() {
  const theme = useTheme();
  return (
    <Card padding={28} style={{ alignItems: 'center', gap: 12 }}>
      <ActivityIndicator color={theme.textMid} />
      <Text style={{ color: theme.textMid, fontSize: 12 }}>Loading history…</Text>
    </Card>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <Card color={AT.pnlRedSoft} padding={14}>
      {/* Card bg pnlRedSoft is reservation-rule; text stays plum/plumMid
          and reads on the pink bg in both modes. */}
      <Text style={{ fontWeight: '800', fontSize: 14, color: AT.plum, marginBottom: 4 }}>
        Can’t load history
      </Text>
      <Text style={{ fontSize: 12, color: AT.plumMid }}>{message}</Text>
    </Card>
  );
}
