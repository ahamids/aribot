# Aribot Branching Strategy

## Branch Model

- `mainnet`: production branch (protected)
- `testnet`: integration branch for testnet-safe code only (protected)
- `feature/<phase>-<short-topic>`: short-lived development branches

Recommended phase prefixes:
- `feature/foundation-*`
- `feature/execution-*`
- `feature/reconciliation-*`
- `feature/observability-*`
- `feature/certification-*`
- `feature/golive-*`

## Flow Rules

1. Create all feature branches from `testnet`.
2. Merge feature branches into `testnet` first.
3. Promote from `testnet` into `mainnet` only via pull request.
4. No direct pushes to `testnet` or `mainnet`.

## Branch Protection Rules

### `mainnet` (strict)

- Require pull request before merging.
- Require at least 1 approval.
- Dismiss stale approvals when new commits are pushed.
- Require all conversations to be resolved.
- Require status checks before merge.
- Required status check:
  - `verify_bot_v2 harness`
- Require branch to be up to date before merge.
- Restrict who can push (maintainers only).
- Disallow force pushes.
- Disallow deletions.

### `testnet` (guarded integration)

- Require pull request before merging.
- Require at least 1 approval.
- Require status checks before merge.
- Required status check:
  - `verify_bot_v2 harness`
- Require branch to be up to date before merge.
- Disallow force pushes.
- Disallow deletions.

## Commit Message Convention (Conventional Commits)

Format:

`<type>(<scope>): <subject>`

Allowed `type` values:
- `feat`
- `fix`
- `refactor`
- `test`
- `docs`
- `chore`
- `perf`
- `ci`
- `revert`

Rules:
- Subject is imperative and <= 72 chars.
- Use lowercase type and scope.
- One logical change per commit.
- Include breaking changes in footer when needed:
  - `BREAKING CHANGE: <description>`

Examples:
- `feat(execution): add partial-fill remainder policy`
- `fix(reconciliation): handle orphan exchange position`
- `ci(verify): run verify harness on PR`
- `docs(branching): define mainnet protection policy`

## Pull Request Requirements

Every PR into `testnet` or `mainnet` must:

1. Pass `verify_bot_v2 harness` in CI.
2. Include command output snippet for local run of:
   - `python verify_bot_v2.py --market usdt --strict`
3. Describe risk impact and rollback plan.

## One-time Branch Setup Commands

```bash
git checkout -b testnet
git push -u origin testnet
git checkout -b mainnet
git push -u origin mainnet
```

Then set the above protections in GitHub: Settings -> Branches (or Rulesets).
