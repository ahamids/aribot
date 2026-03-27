## Summary

Describe what this PR changes.

## Branch Target

- [ ] This PR targets `testnet` or `mainnet` only when appropriate.
- [ ] No direct push was used for protected branches.

## Verify Harness (Required)

Run locally and paste the output:

```bash
python verify_bot_v2.py --market usdt --strict
```

Output:

```text
PASTE OUTPUT HERE
```

Checklist:
- [ ] `verify_bot_v2.py` completed successfully.
- [ ] I confirm CI check `verify_bot_v2 harness` is green.

## Risk and Rollback

- Risk level: low / medium / high
- Main risks introduced:
- Rollback plan (specific commands or revert plan):

## Testing Scope

- [ ] Logic path tested
- [ ] Reconciliation path tested (if applicable)
- [ ] Kill switch path tested (if applicable)
- [ ] Testnet behavior validated (if applicable)

## Conventional Commit Compliance

- [ ] Commit messages follow Conventional Commits (`type(scope): subject`).
