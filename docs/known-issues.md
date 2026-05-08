# Known Issues (Transparently Tracked)

> Architecture's highest principle is honesty, not aesthetics.

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | **Self-referential paradox**: the agent is its own judge, no external metric system | 🔴 High | Needs external design |
| 2 | State graph not externally enforced — relies on agent following instructions | 🟡 Medium | Logic Anchor mitigation |
| 3 | Protocol 3 violations have no auto-penalty | 🟡 Medium | Logic Anchor mitigation |
| 4 | Memory distillation not on cron — script exists but no timer | 🟡 Medium | Script ready, timer pending |
| 5 | Engine 4 baseline data insufficient (n<5, trend uncomputable) | 🟡 Medium | Accumulating |
| 6 | Deep memory (REVIEW.md) not consistently updated | 🟡 Medium | Low-frequency scenario |
| 7 | Tool result cache not implemented | 🟡 Medium | Planned |
