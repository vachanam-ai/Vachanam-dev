---
active: true
iteration: 1
session_id: c80029f1-d6c8-4698-982a-5baf863a1e3f
max_iterations: 0
completion_promise: null
started_at: "2026-06-12T09:03:56Z"
---

Run 3 iterations of a bug bounty cycle on the Vachanam project. Phase 1 of each iteration: a bug-bounty-hunter agent sweeps the entire codebase and produces a complete severity-ranked bug list. Reward tiers: trivial UI or static bugs pay least, logic bugs pay medium, bugs that can crash the app or corrupt bookings or leak tenant data pay most. The hunter must completely finish before phase 2. Phase 2: brainstormer agent proposes the best fix approach per bug, then developer agent implements all fixes. FIXLOG ritual applies: every fix gets a docs/FIXLOG.md row plus a regression test, full suite re-run after changes.
