# User decision on the blocked live-API review (2026-11-13)

The round-1 live-API review for this sub-job came back BLOCKED: the sandbox refused to bind a local port
(`[Errno 1] ... operation not permitted`), so no scratch proxy could start and no HTTP check ran.
The orchestrator offered to rerun it if the user allowed `sandbox.network.allowLocalBinding: true`.
The user declined ("No, proceed"). Decision: proceed to the approver WITHOUT live HTTP verification.

- The board keeps `reviews.api = "BLOCKED"`; it was not changed to PASS. The approver must treat the live checks as
  UNVERIFIED and say so in decision.md. Security and code reviews passed.
- This is the user's acceptance of the evidence available (in-process tests, the code reviews, and the
  orchestrator's own re-runs), not a claim that the live behaviour was observed.
- The approver may not start servers either. Judge whether the in-process tests cover the behaviours the live review
  would have exercised, and name any gap in decision.md.
