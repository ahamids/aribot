# Branch C Leverage Setter Architecture

## Scope
This design covers Change 3 only: explicit leverage setting before entry market orders in the live execution path.

Target file for implementation: order_executor.py
Supporting callsite/test hooks: usdt_paper_bot_v2.py and test_live_bot.py

## Current Baseline
- Entry orders are submitted through Aribot.open_position -> submit_market_order -> OrderExecutor.execute_order.
- OrderExecutor.execute_order currently calls exchange.create_order directly (after idempotency checks and dry-run gate).
- No leverage pre-check exists in OrderExecutor.

## Design Goals
1. Set Bybit leverage explicitly before every entry market order.
2. Abort the order if leverage setting fails.
3. Preserve existing behavior for non-entry orders (exit, partial profit, etc.).
4. Keep idempotency ledger semantics intact for failed attempts.

## Proposed API and Method Signatures

### 1) New exception in order_executor.py

```python
class LeverageSetError(Exception):
    """Raised when leverage cannot be set before an entry order."""
```

### 2) New private method in OrderExecutor

```python
def _ensure_leverage(self, symbol: str, leverage: float) -> None:
    """
    Ensure exchange leverage is set for the symbol before entry order placement.

    Raises:
        LeverageSetError: when set_leverage fails or leverage input is invalid.
    """
```

Behavior inside _ensure_leverage:
- Validate leverage is numeric and > 0.
- Normalize for Bybit request value:
  - leverage_value = int(float(leverage)) if whole number leverage is expected
  - If project prefers decimal leverage, keep as float; do not round unexpectedly.
- Call ccxt exactly as required:

```python
self.exchange.set_leverage(
    leverage_value,
    symbol,
    params={
        'buyLeverage': leverage_value,
        'sellLeverage': leverage_value,
    },
)
```

- On success, emit the exact info log line:

```text
Leverage confirmed: {symbol} = {leverage}x
```

- On failure, emit error log with symbol and leverage and raise LeverageSetError.

### 3) Execute path signature extension

```python
def execute_order(
    self,
    symbol: str,
    order_type: str,
    side: str,
    amount: float,
    price: Optional[float] = None,
    idempotency_key: Optional[str] = None,
    *,
    order_reason: str = 'unspecified',
    leverage: Optional[float] = None,
) -> OrderResult:
```

Why keyword-only fields:
- Preserves existing positional call compatibility.
- Makes entry-only leverage requirement explicit and harder to misuse.

### 4) submit_market_order hook signature in usdt_paper_bot_v2.py

```python
def submit_market_order(self, symbol, side, quantity, reason, idempotency_key, leverage=None):
```

And pass through:

```python
result = self.order_executor.execute_order(
    symbol=symbol,
    order_type='market',
    side=side,
    amount=quantity,
    idempotency_key=idempotency_key,
    order_reason=reason,
    leverage=leverage,
)
```

### 5) Entry callsite hook in open_position

In open_position, pass computed leverage to entry order call:

```python
ok, order_data = self.submit_market_order(
    symbol=symbol,
    side=order_side,
    quantity=qty,
    reason='entry',
    idempotency_key=order_key,
    leverage=leverage,
)
```

Non-entry calls (close_position, partial_profit) keep leverage omitted.

## Call Flow (Entry Order)

1. Aribot.open_position computes leverage via get_leverage_for_symbol(symbol).
2. Aribot.submit_market_order is called with reason='entry' and leverage=<computed>.
3. OrderExecutor.execute_order begins idempotency handling and marks intent pending.
4. If dry_run is true:
   - Return dry-run success exactly as today.
   - Do not call _ensure_leverage.
5. If order_reason == 'entry':
   - If leverage is None, fail fast by raising LeverageSetError (configuration/programming error).
   - Call self._ensure_leverage(symbol, leverage).
6. On leverage success, call self.exchange.create_order(...).
7. Finalize order status/fills and persist success in idempotency table as today.

## Call Flow (Non-Entry Order)

1. submit_market_order called with reason in {partial_profit, stop_loss, trailing_stop, timeout, etc.}.
2. execute_order receives order_reason != 'entry'.
3. _ensure_leverage is skipped.
4. create_order behavior remains unchanged.

## Failure Handling Contract

### _ensure_leverage failures
Failure sources:
- ccxt ExchangeError / NetworkError / timeout
- invalid leverage value (None, <= 0, non-numeric)

Required behavior:
1. Log ERROR with context:
   - symbol
   - leverage
   - exception type/message
2. Raise LeverageSetError.
3. execute_order catches LeverageSetError and:
   - marks idempotency intent failed
   - returns OrderResult(success=False, order_id=None, message=<error text>)
4. Critically, do not call exchange.create_order after leverage failure.

Suggested message format:

```text
Leverage setup failed for {symbol} at {leverage}x: {error}
```

## Idempotency Interaction

- Existing idempotency pending/success/failed logic is retained.
- If leverage fails, the attempt ends in failed status.
- A retry with same key can follow existing failed-attempt behavior (new attempt allowed if current logic permits).

## Logging Requirements

Mandatory success log:

```text
Leverage confirmed: {symbol} = {leverage}x
```

Mandatory failure log (ERROR): include symbol + leverage + cause.

## Test Hooks Needed in test_live_bot.py

Add targeted unit-style hooks (no live exchange dependency) to validate sequence and abort behavior.

### Hook 1: Sequence capture fake exchange

Add a fake class:

```python
class FakeExchangeLeverageOrder:
    def __init__(self, fail_set_leverage=False):
        self.fail_set_leverage = fail_set_leverage
        self.calls = []

    def set_leverage(self, leverage, symbol, params=None):
        self.calls.append(('set_leverage', leverage, symbol, params))
        if self.fail_set_leverage:
            raise ccxt.ExchangeError('set_leverage rejected')
        return {'retCode': 0}

    def create_order(self, **kwargs):
        self.calls.append(('create_order', kwargs))
        return {'id': 'order-123', 'status': 'closed', 'filled': kwargs.get('amount', 0), 'average': 100.0}

    def fetch_order(self, order_id, symbol):
        return {'id': order_id, 'status': 'closed'}

    def fetch_my_trades(self, symbol=None, limit=200):
        return []
```

### Hook 2: Entry leverage pre-check test

New test function signature:

```python
def test_10_entry_order_sets_leverage_before_create_order() -> tuple[str, str]:
```

Assertions:
- execute_order called with order_reason='entry' and leverage=5.
- First exchange call is set_leverage, second is create_order.
- set_leverage args include params with both buyLeverage and sellLeverage equal to 5.
- Result is success.

### Hook 3: Abort on leverage failure test

New test function signature:

```python
def test_11_entry_order_aborts_when_set_leverage_fails() -> tuple[str, str]:
```

Assertions:
- Fake exchange configured with fail_set_leverage=True.
- execute_order called with order_reason='entry', leverage=5.
- Result is failure.
- create_order was never called.
- Message contains leverage setup failure context.

### Hook 4: Non-entry path does not require leverage

Optional but recommended to prevent regressions.

```python
def test_12_non_entry_order_skips_leverage_precheck() -> tuple[str, str]:
```

Assertions:
- execute_order called with order_reason='partial_profit', leverage omitted.
- create_order is called successfully.
- set_leverage is not called.

## Minimal Implementation Checklist

1. order_executor.py
- Add LeverageSetError.
- Add _ensure_leverage(symbol, leverage).
- Extend execute_order signature with keyword-only order_reason and leverage.
- Invoke _ensure_leverage before create_order for entry orders.
- Catch LeverageSetError and return failed OrderResult after marking idempotency failed.

2. usdt_paper_bot_v2.py
- Extend submit_market_order signature to accept leverage=None.
- Pass order_reason and leverage through to execute_order.
- Pass leverage from open_position entry call only.

3. test_live_bot.py
- Add fake exchange hook class for call-sequence capture.
- Add tests 10 and 11 (and optional 12).
- Register new tests in main() test list and criteria map.

## Acceptance Mapping for Branch C

- _ensure_leverage exists and is private in OrderExecutor.
- set_leverage is called before create_order in entry path.
- set_leverage uses buyLeverage and sellLeverage params.
- set_leverage failure aborts order placement.
- success log line is exactly: Leverage confirmed: {symbol} = {leverage}x
