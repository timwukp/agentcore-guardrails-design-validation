# ERRATA — factual errors found inside sealed artifacts

A sealed artifact cannot be edited without destroying the property the seal exists for: that
nobody moved the goalposts after the data arrived. So when measurement shows that a sealed file
*states a wrong fact*, the file stays byte-identical and the correction lives here — dated, with
the evidence that established it. This is the same posture academic pre-registration takes: the
register is immutable, errata are annotations beside it, and a reader who finds the discrepancy
finds the explanation next to it rather than a silent rewrite.

This register is for **factual errors in what a sealed file says**, not for changes to procedure —
those are `DEVIATIONS.md` entries — and not for verdicts, which live in `results/` and the
findings.

---

## E-1 — `claims/triage.csv:147` registers an inference path the wire refused

- **Date recorded:** 2026-08-15
- **Sealed artifact:** `claims/triage.csv` (bound by sha256 before any measurement)
- **Location:** line 147, claim `C-s4-1-bullet-007` (case F1-15)
- **Disposition decided by the user, 2026-08-15:** annotate here; do **not** edit or re-seal the
  csv.

**What the sealed line says.** The claim text enumerates three gateway target types and gives the
HTTP inference surface's path as **`POST /inference`**. That wording was copied faithfully from
the v1.2 document under test — the register recorded what the document claimed, which is its job.

**What was measured.** On a live gateway (run `r20260810T130945Z`, 2026-08-14 UTC, us-east-1),
`POST /inference` alone is refused with `Http operation is not supported for gateway protocol
type MCP`, and so is `/v1/messages` on its own. The served route is a composition — the target's
`operations[].path` (`/v1/messages`) beneath the gateway's own `/inference` prefix — so the real
wire path is **`POST /inference/v1/messages`**. v1.2's path was the prefix mistaken for the whole
route.

- Evidence: `results/DIAG-target-types-20260814T054243Z.json`,
  `results/DIAG-inference-body-20260814T060945Z.json`,
  `results/DIAG-inference-body-20260814T061554Z.json`, `results/phase1/F1-15.json`
- Analysis: `results/FINDING-F1-15.md` (the path comparison and the refusal bodies)
- Document correction: v1.4 §4.1 (correction item 21) — the bullet's path was corrected and
  flagged in place; the three-target-type claim itself was **not** amended (F1-15 is
  INCONCLUSIVE, which licenses no amendment; the path is an incidental wire fact in the same
  bullet, not the claim's substance).

**Why the csv is not edited.** The register's value is that the 93 claims were fixed before any
outcome was known. The stale path is not a defect in the register — it is the register doing its
job, quoting a document that was wrong. Editing it would replace evidence of what v1.2 claimed
with what v1.4 knows, which is exactly the laundering a seal exists to make impossible.

**Effect on verdicts.** None. F1-15's oracle decides the three-target-type enumeration, not the
path spelling; its verdict is INCONCLUSIVE for reasons unrelated to this erratum
(`http.agentcoreRuntime` targets cannot be constructed at this API version, so "all three" can be
neither satisfied nor refuted).
