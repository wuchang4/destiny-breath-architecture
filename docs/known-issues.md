# Known Issues

> Transparency is the highest architectural principle.

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | **Self-reference paradox**: I am my own judge — no external metric system | 🔴 High | Needs design |
| 2 | **Cache hit path untested**: 门下省 can skip execution and go directly to AAR, but no cache entries exist yet | 🟡 Medium | Awaiting data |
| 3 | **Double Agent registration**: Old `register` + new `AgentRuntime` coexist, needs cleanup | 🟡 Medium | Needs refactor |
| 4 | **Memory distillation manual**: Scripts ready, cron not configured | 🟡 Medium | Scripts ready |
| 5 | **Engine 4 baseline insufficient**: n<5, trend not computable | 🟡 Medium | Accumulating |
| 6 | **REVIEW.md inactive**: Deep memory file not updated | 🟡 Medium | Low frequency |
| 7 | **Tool result cache not implemented** | 🟡 Medium | Planned |
| 8 | **WeChat control limited**: Qt framework no UIA tree + missing multimodal vision | 🟡 Medium | Awaiting model upgrade |

## Architecture-Level Limitations

- **State Graph is mental simulation, not an independent engine**: Node functions and conditional edges run in the agent's reasoning process, not in a separate runtime
- **Metrics are self-assessed**: Scores are evaluated internally during AAR, not by an external validator
- **Auto-gradient triggers, fixes still need human review**: Heartbeat can detect degradation and generate gradient files, but root cause analysis and rule changes require human confirmation
