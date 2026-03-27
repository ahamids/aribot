#!/usr/bin/env python3
"""Observability primitives for the bot runtime."""

from __future__ import annotations

import datetime
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional


STRUCTURED_LOG_SCHEMA = {
    'ts': 'ISO-8601 UTC timestamp',
    'level': 'DEBUG|INFO|WARNING|ERROR|CRITICAL',
    'event_type': 'Machine-readable event name',
    'run_id': 'Unique process/run identifier',
    'component': 'Subsystem name',
    'symbol': 'Market symbol or null',
    'values': 'Object of event-specific values',
    'message': 'Human-readable summary',
}


INTENTIONAL_KILL_SWITCH_EXIT_CODE = 42


class StructuredEventLogger:
    def __init__(self, file_path: str, run_id: str):
        self.file_path = Path(file_path)
        self.run_id = run_id

    def emit(
        self,
        level: str,
        event_type: str,
        component: str,
        message: str,
        symbol: Optional[str] = None,
        values: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'level': level.upper(),
            'event_type': event_type,
            'run_id': self.run_id,
            'component': component,
            'symbol': symbol,
            'values': values or {},
            'message': message,
        }
        with self.file_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(payload, separators=(',', ':')) + '\n')


class KillSwitchMonitor:
    def __init__(
        self,
        kill_switch_path: str,
        logger: logging.Logger,
        emit_event: Callable[..., None],
        cancel_all_open_orders: Callable[[], int],
        close_all_positions_market: Callable[[], int],
        exit_callback: Callable[[int], None],
    ) -> None:
        self.kill_switch_path = Path(kill_switch_path)
        self.logger = logger
        self.emit_event = emit_event
        self.cancel_all_open_orders = cancel_all_open_orders
        self.close_all_positions_market = close_all_positions_market
        self.exit_callback = exit_callback
        self.triggered = False

    def check(self, loop_index: int) -> bool:
        if self.triggered or not self.kill_switch_path.exists():
            return self.triggered

        self.triggered = True
        self.emit_event(
            level='CRITICAL',
            event_type='kill_switch_detected',
            component='kill_switch',
            message='Kill switch flag detected; beginning emergency shutdown.',
            values={
                'kill_switch_path': str(self.kill_switch_path),
                'loop_index': loop_index,
            },
        )

        canceled_orders = 0
        closed_positions = 0
        exit_code = INTENTIONAL_KILL_SWITCH_EXIT_CODE
        try:
            canceled_orders = self.cancel_all_open_orders()
            closed_positions = self.close_all_positions_market()
            self.emit_event(
                level='CRITICAL',
                event_type='kill_switch_executed',
                component='kill_switch',
                message='Emergency shutdown actions executed.',
                values={
                    'canceled_orders': canceled_orders,
                    'closed_positions': closed_positions,
                },
            )
        except Exception as exc:
            exit_code = 2
            self.logger.exception('Kill switch execution failed: %s', exc)
            self.emit_event(
                level='CRITICAL',
                event_type='kill_switch_execution_error',
                component='kill_switch',
                message='Emergency shutdown encountered an error.',
                values={
                    'canceled_orders': canceled_orders,
                    'closed_positions': closed_positions,
                    'error': str(exc),
                },
            )
        finally:
            self.exit_callback(exit_code)

        return True


class FundingTracker:
    DDL = '''
        CREATE TABLE IF NOT EXISTS funding_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            symbol TEXT NOT NULL,
            position_side TEXT NOT NULL,
            position_qty REAL NOT NULL,
            funding_rate REAL NOT NULL,
            mark_price REAL NOT NULL,
            payment REAL NOT NULL,
            run_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'estimated'
        );

        CREATE INDEX IF NOT EXISTS idx_funding_payments_ts
        ON funding_payments(ts);

        CREATE INDEX IF NOT EXISTS idx_funding_payments_symbol_ts
        ON funding_payments(symbol, ts);
    '''

    def __init__(
        self,
        exchange: Any,
        db: sqlite3.Connection,
        emit_event: Callable[..., None],
        run_id: str,
        interval_hours: int = 4,
    ) -> None:
        self.exchange = exchange
        self.db = db
        self.emit_event = emit_event
        self.run_id = run_id
        self.interval_seconds = interval_hours * 3600
        self.last_run_ts = 0.0

    def ensure_schema(self) -> None:
        cursor = self.db.cursor()
        cursor.executescript(self.DDL)
        self.db.commit()

    def should_run(self, now_ts: float) -> bool:
        return (now_ts - self.last_run_ts) >= self.interval_seconds

    def track_open_positions(self, positions: Iterable[Any], now_ts: float) -> float:
        if not self.should_run(now_ts):
            return 0.0

        self.last_run_ts = now_ts
        total_payment = 0.0
        cursor = self.db.cursor()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        for pos in positions:
            qty = abs(float(getattr(pos, 'quantity', 0.0)))
            if qty <= 0.0:
                continue

            symbol = getattr(pos, 'symbol')
            side = str(getattr(pos, 'side', '')).lower()
            if not symbol or side not in {'long', 'short', 'buy', 'sell'}:
                continue

            try:
                funding = self.exchange.fetch_funding_rate(symbol)
            except Exception as exc:
                self.emit_event(
                    level='WARNING',
                    event_type='funding_rate_fetch_failed',
                    component='funding',
                    message='Failed to fetch funding rate.',
                    symbol=symbol,
                    values={'error': str(exc)},
                )
                continue

            funding_rate = float(funding.get('fundingRate') or 0.0)
            mark_price = float(
                funding.get('markPrice')
                or getattr(pos, 'current_price', 0.0)
                or getattr(pos, 'entry_price', 0.0)
            )
            if mark_price <= 0.0:
                continue

            notional = qty * mark_price
            payment = notional * funding_rate
            signed_payment = -payment if side in {'long', 'buy'} else payment
            total_payment += signed_payment

            cursor.execute(
                '''
                INSERT INTO funding_payments (
                    ts, symbol, position_side, position_qty,
                    funding_rate, mark_price, payment, run_id, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    now_iso,
                    symbol,
                    side,
                    qty,
                    funding_rate,
                    mark_price,
                    signed_payment,
                    self.run_id,
                    'estimated',
                ),
            )

            self.emit_event(
                level='INFO',
                event_type='funding_payment_recorded',
                component='funding',
                message='Funding payment recorded.',
                symbol=symbol,
                values={
                    'position_side': side,
                    'position_qty': qty,
                    'funding_rate': funding_rate,
                    'mark_price': mark_price,
                    'payment': signed_payment,
                },
            )

        self.db.commit()
        return total_payment