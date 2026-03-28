#!/usr/bin/env python3
"""Analyze Stage 1 readiness from logs and database."""
import json
from collections import defaultdict
from datetime import datetime
import sqlite3

print("=" * 80)
print("STAGE 1 COMPLETION ANALYSIS")
print("=" * 80)
print()

# Analyze run durations from observability.jsonl
print("1. RUN DURATION ANALYSIS")
print("-" * 80)

run_times = defaultdict(lambda: {'first': None, 'last': None, 'events': 0})

with open('observability.jsonl', 'r') as f:
    for line in f:
        try:
            event = json.loads(line)
            run_id = event.get('run_id')
            ts = event.get('ts')
            run_times[run_id]['events'] += 1
            if ts:
                if run_times[run_id]['first'] is None or ts < run_times[run_id]['first']:
                    run_times[run_id]['first'] = ts
                if run_times[run_id]['last'] is None or ts > run_times[run_id]['last']:
                    run_times[run_id]['last'] = ts
        except:
            pass

total_hours = 0
for run_id in sorted(run_times.keys()):
    info = run_times[run_id]
    print(f"Run ID: {run_id}")
    print(f"  First event: {info['first']}")
    print(f"  Last event:  {info['last']}")
    print(f"  Total events: {info['events']}")
    if info['first'] and info['last']:
        first_dt = datetime.fromisoformat(info['first'].replace('Z', '+00:00'))
        last_dt = datetime.fromisoformat(info['last'].replace('Z', '+00:00'))
        duration = last_dt - first_dt
        hours = duration.total_seconds() / 3600
        total_hours += hours
        print(f"  Duration: {hours:.2f} hours")
    print()

print(f"Total accumulated run time: {total_hours:.2f} hours")
print()

# Count lifecycle events
print("2. LIFECYCLE EVENT ANALYSIS")
print("-" * 80)

exit_types = defaultdict(int)
entry_count = 0
partial_exit_count = 0
position_closed_count = 0

with open('observability.jsonl', 'r') as f:
    for line in f:
        try:
            event = json.loads(line)
            event_type = event.get('event_type')
            if event_type == 'position_opened':
                entry_count += 1
            elif event_type == 'partial_exit':
                partial_exit_count += 1
            elif event_type == 'position_closed':
                reason = event.get('values', {}).get('reason', 'unknown')
                exit_types[reason] += 1
                position_closed_count += 1
        except:
            pass

print(f"Total entries: {entry_count}")
print(f"Total partial exits: {partial_exit_count}")
print(f"Total position closes: {position_closed_count}")
print(f"Exit reasons:")
for reason, count in sorted(exit_types.items()):
    print(f"  {reason}: {count}")
print()

# Analyze database for ghost positions and reconciliation
print("3. DATABASE ANALYSIS")
print("-" * 80)

try:
    conn = sqlite3.connect('usdt_paper_bot_v2.db')
    cursor = conn.cursor()
    
    # Check for ghost positions
    cursor.execute("""
        SELECT name FROM sqlite_master WHERE type='table'
    """)
    tables = [row[0] for row in cursor.fetchall()]
    print(f"Database tables: {', '.join(tables)}")
    print()
    
    # Check positions table
    if 'positions' in tables:
        cursor.execute("SELECT COUNT(*) FROM positions WHERE status='open'")
        open_count = cursor.fetchone()[0]
        print(f"Currently open positions in DB: {open_count}")
        
        cursor.execute("SELECT COUNT(*) FROM positions")
        total_count = cursor.fetchone()[0]
        print(f"Total position records: {total_count}")
    
    conn.close()
except Exception as e:
    print(f"Database error: {e}")

print()

# Check trading log for errors
print("4. ERROR AND CRASH ANALYSIS")
print("-" * 80)

error_count = 0
with open('usdt_paper_trading_log.txt', 'r') as f:
    content = f.read()
    error_keywords = ['error', 'ERROR', 'Exception', 'EXCEPTION', 'crash', 'CRASH', 'failed', 'FAILED']
    for keyword in error_keywords:
        count = content.count(keyword)
        if count > 0:
            print(f"Found {count} instances of '{keyword}'")
            error_count += count

if error_count == 0:
    print("No errors or crashes detected in trading log")
print()

# Summary
print("=" * 80)
print("STAGE 1 READINESS ASSESSMENT")
print("=" * 80)

print()
print("REQUIREMENT CHECKLIST:")
print()

# Duration check
duration_pass = total_hours >= 48
print(f"[{'PASS' if duration_pass else 'FAIL'}] Runtime >= 48 hours: {total_hours:.2f} hours")

# Trade cycles check
trade_cycles = position_closed_count
cycles_pass = trade_cycles >= 3
print(f"[{'PASS' if cycles_pass else 'FAIL'}] >= 3 complete trade cycles: {trade_cycles} closes")

# Lifecycle events check
lifecycle_pass = entry_count > 0 and partial_exit_count > 0 and 'TRAILING_STOP' in exit_types
print(f"[{'PASS' if lifecycle_pass else 'FAIL'}] Full lifecycle coverage:")
print(f"     - Entries: {entry_count}")
print(f"     - Partial exits: {partial_exit_count}")
print(f"     - Trailing stop exits: {exit_types.get('TRAILING_STOP', 0)}")
print(f"     - Time exits: {exit_types.get('TIME_EXIT', 0)}")

# Stability check
stability_pass = error_count == 0
print(f"[{'PASS' if stability_pass else 'FAIL'}] No unhandled exceptions/crashes")

# Overall
all_pass = duration_pass and cycles_pass and lifecycle_pass and stability_pass
print()
print(f"OVERALL STAGE 1 STATUS: {'✓ READY FOR STAGE 2' if all_pass else '✗ NOT READY FOR STAGE 2'}")
print()

if not duration_pass:
    print(f"  ⚠ BLOCKER: Need additional {48 - total_hours:.2f} hours of runtime")
if not cycles_pass:
    print(f"  ⚠ BLOCKER: Need {3 - trade_cycles} more complete trade cycles")
if not lifecycle_pass and partial_exit_count == 0:
    print(f"  ⚠ WARNING: No partial exits observed")
if not lifecycle_pass and exit_types.get('TRAILING_STOP', 0) == 0:
    print(f"  ⚠ WARNING: No trailing stop exits observed")
if not lifecycle_pass and exit_types.get('TIME_EXIT', 0) == 0:
    print(f"  ⚠ WARNING: No time-based exits observed")
