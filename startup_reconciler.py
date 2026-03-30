#!/usr/bin/env python3
"""Startup reconciliation for live Bybit positions vs local SQLite state."""

from __future__ import annotations

import datetime
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ReconciliationItem:
    symbol: str
    severity: str
    category: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReconciliationReport:
    started_at: datetime.datetime
    finished_at: datetime.datetime
    exchange_open_count: int
    local_open_count: int
    reconciled_count: int
    warning_count: int
    critical_count: int
    manual_review_required: bool
    passed: bool
    items: List[ReconciliationItem] = field(default_factory=list)


class StartupReconciler:
    """
    Reconciles startup state before the trading loop runs.

    Rules:
    1) SQLite open position missing on exchange -> reconstruct close, else unknown_close and alert.
    2) Exchange open position missing in SQLite -> CRITICAL, manual review required, do not auto-close.
    3) Position in both with >1% qty/entry mismatch -> WARNING and overwrite local with exchange values.
    """

    RECONCILIATION_DDL = """
    CREATE TABLE IF NOT EXISTS reconciliation_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        exchange_open_count INTEGER NOT NULL,
        local_open_count INTEGER NOT NULL,
        reconciled_count INTEGER NOT NULL,
        warning_count INTEGER NOT NULL,
        critical_count INTEGER NOT NULL,
        manual_review_required INTEGER NOT NULL,
        passed INTEGER NOT NULL,
        report_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS reconciliation_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        severity TEXT NOT NULL,
        category TEXT NOT NULL,
        message TEXT NOT NULL,
        details_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY(report_id) REFERENCES reconciliation_reports(id)
    );

    CREATE INDEX IF NOT EXISTS idx_reconciliation_items_report
    ON reconciliation_items(report_id);

    CREATE INDEX IF NOT EXISTS idx_reconciliation_items_symbol
    ON reconciliation_items(symbol);
    """

    def __init__(
        self,
        exchange: Any,
        db: sqlite3.Connection,
        logger: logging.Logger,
        alert_dispatcher: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
        native_stop_executor: Optional[Any] = None,
    ) -> None:
        self.exchange = exchange
        self.db = db
        self.logger = logger
        self.alert_dispatcher = alert_dispatcher
        self.native_stop_executor = native_stop_executor

    def ensure_schema(self) -> None:
        cursor = self.db.cursor()
        cursor.executescript(self.RECONCILIATION_DDL)
        self.db.commit()

    def reconcile_startup_state(self) -> ReconciliationReport:
        self.ensure_schema()

        started_at = datetime.datetime.now(datetime.timezone.utc)
        items: List[ReconciliationItem] = []

        exchange_positions = self.fetch_open_exchange_positions()
        local_positions = self.load_local_open_positions()

        exchange_symbols = set(exchange_positions.keys())
        local_symbols = set(local_positions.keys())

        # 1) Local open but absent on exchange.
        missing_on_exchange = sorted(local_symbols - exchange_symbols)
        for symbol in missing_on_exchange:
            local_pos = local_positions[symbol]
            reconstructed_close = self.reconstruct_close_from_trades(
                symbol=symbol,
                side=local_pos['side'],
                open_quantity=local_pos['quantity'],
            )

            if reconstructed_close is not None:
                self.archive_local_position_as_closed(
                    symbol=symbol,
                    local_position=local_pos,
                    close_price=reconstructed_close,
                    reason='offline_reconciled_close',
                )
                items.append(
                    ReconciliationItem(
                        symbol=symbol,
                        severity='INFO',
                        category='local_missing_on_exchange',
                        message='Local open position was closed while bot was offline; close reconstructed.',
                        details={'reconstructed_close_price': reconstructed_close},
                    )
                )
            else:
                self.archive_local_position_as_closed(
                    symbol=symbol,
                    local_position=local_pos,
                    close_price=None,
                    reason='unknown_close',
                )
                self._send_alert(
                    level='WARNING',
                    message=f'unknown_close for {symbol} during startup reconciliation',
                    payload={'symbol': symbol, 'category': 'local_missing_on_exchange'},
                )
                items.append(
                    ReconciliationItem(
                        symbol=symbol,
                        severity='WARNING',
                        category='local_missing_on_exchange_unknown_close',
                        message='Local open position missing on exchange and close price could not be reconstructed.',
                    )
                )

        # 2) Exchange open but absent in local DB.
        ghost_positions = sorted(exchange_symbols - local_symbols)
        for symbol in ghost_positions:
            ex_pos = exchange_positions[symbol]
            msg = (
                f'CRITICAL ghost position: exchange has open {symbol} but local DB does not. '
                'Manual review required; startup blocked.'
            )
            self.logger.critical(msg)
            self._send_alert(
                level='CRITICAL',
                message=msg,
                payload={'symbol': symbol, 'category': 'ghost_position', 'exchange_position': ex_pos},
            )
            items.append(
                ReconciliationItem(
                    symbol=symbol,
                    severity='CRITICAL',
                    category='ghost_position',
                    message=msg,
                    details={'exchange_position': ex_pos},
                )
            )

        # 3) Positions in both systems.
        overlap_symbols = sorted(exchange_symbols & local_symbols)
        for symbol in overlap_symbols:
            local_pos = local_positions[symbol]
            ex_pos = exchange_positions[symbol]

            qty_diff_pct = self._percent_diff(local_pos['quantity'], ex_pos['quantity'])
            entry_diff_pct = self._percent_diff(local_pos['entry_price'], ex_pos['entry_price'])

            if qty_diff_pct > 1.0 or entry_diff_pct > 1.0:
                self.logger.warning(
                    'Startup reconcile mismatch for %s: qty_diff_pct=%.2f entry_diff_pct=%.2f. '
                    'Using exchange values as truth.',
                    symbol,
                    qty_diff_pct,
                    entry_diff_pct,
                )
                self.upsert_local_position_from_exchange(symbol, ex_pos, fallback_side=local_pos['side'])
                items.append(
                    ReconciliationItem(
                        symbol=symbol,
                        severity='WARNING',
                        category='position_mismatch_exchange_truth',
                        message='Position mismatch > 1%; local position overwritten with exchange truth.',
                        details={
                            'qty_diff_pct': qty_diff_pct,
                            'entry_diff_pct': entry_diff_pct,
                            'local_quantity': local_pos['quantity'],
                            'exchange_quantity': ex_pos['quantity'],
                            'local_entry_price': local_pos['entry_price'],
                            'exchange_entry_price': ex_pos['entry_price'],
                        },
                    )
                )

        if self.native_stop_executor is not None:
            # Copilot prompt: Re-arm branch-B native protection only when local flags show nothing active; warnings must not block startup.
            refreshed_local_positions = self.load_local_open_positions()
            for symbol in overlap_symbols:
                local_pos = refreshed_local_positions.get(symbol)
                if not local_pos:
                    continue

                native_sl_active = bool(local_pos.get('native_sl_active'))
                native_tp_active = bool(local_pos.get('native_tp_active'))
                native_trail_active = bool(local_pos.get('native_trail_active'))
                if native_sl_active or native_tp_active or native_trail_active:
                    continue

                trailing_active = bool(local_pos.get('trailing_stop_active'))
                result = self.native_stop_executor.ensure_native_protection_for_position(
                    symbol=symbol,
                    side=local_pos['side'],
                    entry_price=local_pos['entry_price'],
                    trailing_active=trailing_active,
                )
                if result.get('ok', False):
                    self.update_local_native_flags(
                        symbol=symbol,
                        native_sl_active=result.get('native_sl_active', False),
                        native_tp_active=result.get('native_tp_active', False),
                        native_trail_active=result.get('native_trail_active', False),
                        native_sl_price=result.get('native_sl_price'),
                    )
                    items.append(
                        ReconciliationItem(
                            symbol=symbol,
                            severity='INFO',
                            category='native_protection_rearmed',
                            message='Missing native protection re-armed during startup reconciliation.',
                            details={
                                'trailing_active': trailing_active,
                                'result': result,
                            },
                        )
                    )
                else:
                    items.append(
                        ReconciliationItem(
                            symbol=symbol,
                            severity='WARNING',
                            category='native_protection_rearm_failed',
                            message='Failed to re-arm missing native protection during startup reconciliation.',
                            details={
                                'trailing_active': trailing_active,
                                'result': result,
                            },
                        )
                    )

        finished_at = datetime.datetime.now(datetime.timezone.utc)
        warning_count = sum(1 for item in items if item.severity == 'WARNING')
        critical_count = sum(1 for item in items if item.severity == 'CRITICAL')
        manual_review_required = critical_count > 0

        report = ReconciliationReport(
            started_at=started_at,
            finished_at=finished_at,
            exchange_open_count=len(exchange_positions),
            local_open_count=len(local_positions),
            reconciled_count=len(overlap_symbols),
            warning_count=warning_count,
            critical_count=critical_count,
            manual_review_required=manual_review_required,
            passed=not manual_review_required,
            items=items,
        )

        self.persist_report(report)
        return report

    def fetch_open_exchange_positions(self) -> Dict[str, Dict[str, Any]]:
        positions = self.exchange.fetch_positions()
        result: Dict[str, Dict[str, Any]] = {}

        for pos in positions:
            contracts = pos.get('contracts')
            if contracts is None:
                contracts = pos.get('info', {}).get('size')

            qty = abs(float(contracts or 0.0))
            if qty <= 0.0:
                continue

            symbol = pos.get('symbol')
            if not symbol:
                continue

            entry_price = float(pos.get('entryPrice') or pos.get('average') or 0.0)
            side = str(pos.get('side') or '').lower()
            if side not in {'long', 'short', 'buy', 'sell'}:
                side = 'long' if (float(contracts or 0.0) > 0) else 'short'

            result[symbol] = {
                'symbol': symbol,
                'quantity': qty,
                'entry_price': entry_price,
                'side': side,
                'raw': pos,
            }

        return result

    def load_local_open_positions(self) -> Dict[str, Dict[str, Any]]:
        cursor = self.db.cursor()
        table_info_rows = cursor.execute("PRAGMA table_info(positions)").fetchall()
        existing_columns = {row[1] for row in table_info_rows}

        trailing_expr = 'trailing_stop_active' if 'trailing_stop_active' in existing_columns else '0 AS trailing_stop_active'
        native_sl_expr = 'native_sl_active' if 'native_sl_active' in existing_columns else '0 AS native_sl_active'
        native_tp_expr = 'native_tp_active' if 'native_tp_active' in existing_columns else '0 AS native_tp_active'
        native_trail_expr = 'native_trail_active' if 'native_trail_active' in existing_columns else '0 AS native_trail_active'
        native_sl_price_expr = 'native_sl_price' if 'native_sl_price' in existing_columns else 'NULL AS native_sl_price'

        rows = cursor.execute(
            (
                'SELECT symbol, side, entry_price, quantity, timestamp, '
                f'{trailing_expr}, {native_sl_expr}, {native_tp_expr}, {native_trail_expr}, {native_sl_price_expr} '
                'FROM positions'
            )
        ).fetchall()

        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            result[row['symbol']] = {
                'symbol': row['symbol'],
                'side': row['side'],
                'entry_price': float(row['entry_price']),
                'quantity': float(row['quantity']),
                'timestamp': row['timestamp'],
                'trailing_stop_active': int(row['trailing_stop_active'] or 0),
                'native_sl_active': int(row['native_sl_active'] or 0),
                'native_tp_active': int(row['native_tp_active'] or 0),
                'native_trail_active': int(row['native_trail_active'] or 0),
                'native_sl_price': row['native_sl_price'],
            }

        return result

    def reconstruct_close_from_trades(self, symbol: str, side: str, open_quantity: float) -> Optional[float]:
        try:
            trades = self.exchange.fetch_my_trades(symbol=symbol, limit=200)
        except Exception as exc:
            self.logger.warning('Failed to fetch trade history for %s: %s', symbol, exc)
            return None

        if not trades:
            return None

        expected_close_side = 'sell' if side.lower() in {'long', 'buy'} else 'buy'

        candidates = [
            t for t in trades
            if str(t.get('side', '')).lower() == expected_close_side
        ]
        if not candidates:
            return None

        # Most recent close-side trades first.
        candidates.sort(key=lambda t: int(t.get('timestamp') or 0), reverse=True)

        qty_left = abs(float(open_quantity or 0.0))
        notional = 0.0
        filled = 0.0

        for trade in candidates:
            px = float(trade.get('price') or 0.0)
            qty = abs(float(trade.get('amount') or 0.0))
            if px <= 0 or qty <= 0:
                continue

            take = min(qty, qty_left) if qty_left > 0 else qty
            notional += px * take
            filled += take
            qty_left -= take

            if qty_left <= 1e-12:
                break

        if filled <= 0:
            return None

        return notional / filled

    def archive_local_position_as_closed(
        self,
        symbol: str,
        local_position: Dict[str, Any],
        close_price: Optional[float],
        reason: str,
    ) -> None:
        cursor = self.db.cursor()

        side = str(local_position['side']).lower()
        entry_price = float(local_position['entry_price'])
        qty = float(local_position['quantity'])
        open_time = str(local_position['timestamp'])
        close_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

        pnl = None
        pnl_pct = None
        if close_price is not None and entry_price > 0 and qty > 0:
            if side in {'long', 'buy'}:
                pnl = (close_price - entry_price) * qty
            else:
                pnl = (entry_price - close_price) * qty
            # Keep archived percentage aligned with runtime stop logic: derive only from prices.
            from usdt_paper_bot_v2 import derive_pnl_pct

            pnl_pct = derive_pnl_pct(entry_price, close_price, side)

        cursor.execute(
            '''
            INSERT INTO closed_trades (
                symbol, side, entry_price, exit_price, quantity, pnl,
                pnl_percentage, reason, open_time, close_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                symbol,
                side,
                entry_price,
                close_price,
                qty,
                pnl,
                pnl_pct,
                reason,
                open_time,
                close_time,
            ),
        )

        cursor.execute('DELETE FROM positions WHERE symbol = ?', (symbol,))
        self.db.commit()

    def update_local_native_flags(
        self,
        symbol: str,
        *,
        native_sl_active: bool,
        native_tp_active: bool,
        native_trail_active: bool,
        native_sl_price: Optional[float],
    ) -> None:
        cursor = self.db.cursor()
        cursor.execute(
            '''
            UPDATE positions
            SET native_sl_active = ?,
                native_tp_active = ?,
                native_trail_active = ?,
                native_sl_price = ?
            WHERE symbol = ?
            ''',
            (
                1 if native_sl_active else 0,
                1 if native_tp_active else 0,
                1 if native_trail_active else 0,
                native_sl_price,
                symbol,
            ),
        )
        self.db.commit()

    def upsert_local_position_from_exchange(
        self,
        symbol: str,
        exchange_position: Dict[str, Any],
        fallback_side: str,
    ) -> None:
        side = str(exchange_position.get('side') or fallback_side).lower()
        entry_price = float(exchange_position.get('entry_price') or 0.0)
        qty = float(exchange_position.get('quantity') or 0.0)
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

        cursor = self.db.cursor()
        cursor.execute(
            '''
            INSERT OR REPLACE INTO positions (
                symbol, side, entry_price, quantity, timestamp,
                stop_loss, trailing_stop_level, trailing_stop_active,
                peak_pnl_percentage, current_price, pnl, pnl_percentage,
                partial_exits_json
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, 0.0, ?, 0.0, 0.0, '[]')
            ''',
            (
                symbol,
                side,
                entry_price,
                qty,
                ts,
                # Startup upsert stores a neutral cached pct; live refresh derives true pct from market price.
                entry_price,
            ),
        )
        self.db.commit()

    def persist_report(self, report: ReconciliationReport) -> int:
        payload = {
            'started_at': report.started_at.isoformat(),
            'finished_at': report.finished_at.isoformat(),
            'exchange_open_count': report.exchange_open_count,
            'local_open_count': report.local_open_count,
            'reconciled_count': report.reconciled_count,
            'warning_count': report.warning_count,
            'critical_count': report.critical_count,
            'manual_review_required': report.manual_review_required,
            'passed': report.passed,
            'items': [
                {
                    'symbol': i.symbol,
                    'severity': i.severity,
                    'category': i.category,
                    'message': i.message,
                    'details': i.details,
                }
                for i in report.items
            ],
        }

        cursor = self.db.cursor()
        cursor.execute(
            '''
            INSERT INTO reconciliation_reports (
                started_at, finished_at, exchange_open_count, local_open_count,
                reconciled_count, warning_count, critical_count,
                manual_review_required, passed, report_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                payload['started_at'],
                payload['finished_at'],
                report.exchange_open_count,
                report.local_open_count,
                report.reconciled_count,
                report.warning_count,
                report.critical_count,
                1 if report.manual_review_required else 0,
                1 if report.passed else 0,
                json.dumps(payload),
            ),
        )
        report_id = int(cursor.lastrowid)

        for item in report.items:
            cursor.execute(
                '''
                INSERT INTO reconciliation_items (
                    report_id, symbol, severity, category, message, details_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    report_id,
                    item.symbol,
                    item.severity,
                    item.category,
                    item.message,
                    json.dumps(item.details),
                ),
            )

        self.db.commit()
        return report_id

    def startup_gate(self) -> ReconciliationReport:
        """
        Blocking startup sequence entrypoint.
        Raises RuntimeError when reconciliation does not pass.
        """
        report = self.reconcile_startup_state()
        self.logger.info(
            'Startup reconciliation completed: passed=%s warnings=%d critical=%d manual_review=%s',
            report.passed,
            report.warning_count,
            report.critical_count,
            report.manual_review_required,
        )

        if not report.passed:
            raise RuntimeError(
                'Startup reconciliation failed. Manual review required before main loop can start.'
            )

        return report

    def _send_alert(self, level: str, message: str, payload: Dict[str, Any]) -> None:
        if not self.alert_dispatcher:
            return
        try:
            self.alert_dispatcher(level, message, payload)
        except Exception as exc:
            self.logger.warning('Alert dispatch failed: %s', exc)

    @staticmethod
    def _percent_diff(a: float, b: float) -> float:
        a_f = abs(float(a))
        b_f = abs(float(b))
        base = max(a_f, b_f, 1e-12)
        return abs(a_f - b_f) / base * 100.0
