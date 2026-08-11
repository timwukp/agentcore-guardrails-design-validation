# FINDING-P0-PII-CORPUS — the corpus the plan told us to reuse cannot answer the question it was reused for

**Phase** 0 (offline) · **Cost** $0 · **Date** 2026-08-09
**Deviation** `DEV-P0-6` (class **design**) · **Seal** `DEV-SEAL-3` in `DEVIATIONS.md`
**Artifacts** `PREREGISTRATION.yaml` §`corpora.pii`, §`sample_sizes.pii_per_entity_cell` ·
`verify_prereg.py` (`check_pii_source_audit`) · `claims/tests/test_prereg_verifier.py`

<!-- provenance
{
  "status": "INTERNAL",
  "evidence_runs": [],
  "note": "A property of a corpus on disk and of the SDK's entity-type enumeration, both read offline. No AWS behaviour is claimed."
}
-->

---

## 1. Summary

The approved plan says, in Part 5: *"PII (**reuse the existing 108-case corpus**,
extended to align with the 31 SDK entity types)"*. When the pre-registration was
first sealed, that instruction was recorded as a flat corpus total of **108** — the
reuse clause survived and the extension clause did not.

Inspecting the corpus rather than citing it showed the recorded figure was wrong in
**two independent ways**, either of which alone would have prevented F3-4 from
reaching its own decision rule:

| | Defect | Consequence |
|:--|:---|:---|
| **1** | **Wrong content.** The corpus is a secrets/credential corpus, not a Bedrock PII-entity corpus. Of its 15 positive labels, **2** name a `GuardrailPiiEntityType` exactly, **5** map to one after relabelling, and **8** correspond to no SDK entity type at all. **24 of the SDK's 31** entity types have zero coverage. | 24 entities would have been reported on with no data. |
| **2** | **Wrong shape.** F3-4's oracle is **per-entity** — *"FALSE for any entity whose CI upper bound is below 0.5"*. A flat total is not a per-entity design; an entity at n=0 has no interval, so the oracle is undefined rather than unfalsified. | The case could not have produced the verdict it declares. |

Corrected: **n=11 per entity across all 31 entity types** (341 positives) plus the
27 CLEAN negatives reused verbatim — **368 items**, of which **39** come from the
source corpus after relabelling and **302** are authored against the SDK
enumeration. The 42 items whose labels have no SDK entity type are **not
discarded**: they move to `hard_negatives`, where "a secret that is not a
documented PII entity" is precisely the right stimulus.

Nothing else moves. No other cell, family, oracle, threshold or significance level
changes.

---

## 2. What the source corpus actually contains

`claude-code-enterprise-bedrock/tests/pii-corpus/` — 81 positive + 27 negative
items across 13 `.jsonl` files. Its labels, and where each one lands against the
SDK enumeration:

| Source label | Items | `GuardrailPiiEntityType` | Relation |
|:---|---:|:---|:---|
| AWS_ACCESS_KEY | 8 | `AWS_ACCESS_KEY` | exact |
| AWS_SECRET_KEY | 2 | `AWS_SECRET_KEY` | exact |
| CREDIT_CARD | 15 | `CREDIT_DEBIT_CARD_NUMBER` | relabel |
| PASSWORD_ASSIGNMENT | 6 | `PASSWORD` | relabel |
| EMAIL_ADDRESS | 3 | `EMAIL` | relabel |
| PHONE_INTL | 3 | `PHONE` | relabel |
| PASSPORT_NUMBER | 2 | `US_PASSPORT_NUMBER` | relabel |
| API_KEY_ASSIGNMENT | 7 | — | **no SDK entity type** |
| DB_CONNECTION_STRING | 7 | — | **no SDK entity type** |
| PRIVATE_KEY | 7 | — | **no SDK entity type** |
| SG_NRIC | 6 | — | **no SDK entity type** |
| JWT_TOKEN | 5 | — | **no SDK entity type** |
| HEX_SECRET | 4 | — | **no SDK entity type** |
| GIT_TOKEN | 3 | — | **no SDK entity type** |
| SLACK_TOKEN | 3 | — | **no SDK entity type** |
| **Total positives** | **81** | 7 distinct types covered | 39 reusable, 42 not |
| CLEAN (negatives) | 27 | n/a — label-agnostic | reusable verbatim |

The pattern is not an accident, and it is worth naming precisely rather than
calling the corpus "wrong". That corpus was built to test a **local secret
scanner** — a regex/entropy pipeline looking for credentials in source code. Its
label set is the right label set for that question. `SG_NRIC` (Singapore national
ID) and `PRIVATE_KEY` are genuinely useful stimuli; they are simply not names that
Bedrock Guardrails' PII policy has an opinion about.

**The relabel column is the load-bearing one.** `CREDIT_CARD` → 
`CREDIT_DEBIT_CARD_NUMBER` is not a rename for tidiness: the ApplyGuardrail
request names the entity type, and a request naming `CREDIT_CARD` is a request for
an entity that does not exist. 13 of the 15 source labels are plausible-looking
names the SDK does not use. That is exactly the kind of near-miss that survives
being read and fails being run.

**What the SDK covers that the corpus does not** (24 types, from the live
`GuardrailPiiEntityType` enumeration): `ADDRESS`, `AGE`, `CA_HEALTH_NUMBER`,
`CA_SOCIAL_INSURANCE_NUMBER`, `CREDIT_DEBIT_CARD_CVV`,
`CREDIT_DEBIT_CARD_EXPIRY`, `DRIVER_ID`, `INTERNATIONAL_BANK_ACCOUNT_NUMBER`,
`IP_ADDRESS`, `LICENSE_PLATE`, `MAC_ADDRESS`, `NAME`, `PIN`, `SWIFT_CODE`,
`UK_NATIONAL_HEALTH_SERVICE_NUMBER`, `UK_NATIONAL_INSURANCE_NUMBER`,
`UK_UNIQUE_TAXPAYER_REFERENCE_NUMBER`, `URL`, `USERNAME`,
`US_BANK_ACCOUNT_NUMBER`, `US_BANK_ROUTING_NUMBER`,
`US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER`, `US_SOCIAL_SECURITY_NUMBER`,
`VEHICLE_IDENTIFICATION_NUMBER`.

Most of these are the ordinary PII a document about guardrails is *about*. A
validation of §3's PII claims that omitted `NAME`, `ADDRESS`,
`US_SOCIAL_SECURITY_NUMBER` and `IP_ADDRESS` would not be a partial validation; it
would be a validation of a different subject.

---

## 3. Why a flat total cannot satisfy a per-entity oracle

This is the defect that matters more, because it is structural rather than a
coverage shortfall.

F3-4's falsifying condition, fixed in the triage before this was noticed, reads:
*FALSE for any entity whose CI upper bound is below 0.5.* That quantifier is over
**entities**. Evaluating it requires, for each entity type, a count of trials and a
count of detections — a **cell**. A single 108-item aggregate provides one interval
for one pooled proportion, which answers a question nobody asked ("what fraction of
a mixed bag of secrets does the PII filter catch?") and cannot answer the one
declared.

The failure is not that the estimate would be imprecise. It is that for 24 of 31
entities the estimate does not exist:

```
n = 0  →  no Wilson interval  →  the oracle's condition is undefined
```

An undefined oracle does not evaluate to FALSE. It evaluates to nothing, and a
harness that reports "not falsified" for a cell it never populated has produced
the most dangerous possible output — a pass that looks like evidence. **A
per-entity oracle needs a per-entity cell; the corpus shape and the decision rule
are the same design choice, made once.**

---

## 4. Sizing the per-entity cell: two different floors, and the larger binds

F3-4 asks a **screening** question per entity — does this entity type detect at
all? — not a precision question. Sizing it like the attack-recall cell (n=87, from
a Wilson half-width ≤ 0.075) would give 31 × 87 = **2,697 items** to answer a
yes/no. So the size is derived from the rule the oracle needs, and there are two
candidate floors.

**Floor A — can the oracle physically fire?** The oracle fires on an entity when
its interval's upper bound falls below 0.5. At x=0 that is `wilson_ci(0, n).hi`:

| n | `wilson_ci(0, n).hi` | Oracle can fire at x=0? |
|---:|---:|:---|
| 3 | 0.5615 | **no** |
| **4** | **0.4899** | **yes** |
| 5 | 0.4345 | yes |
| 11 | 0.2588 | yes |

So **n=4** is the floor for the oracle to be *capable* of firing. Below it, an
entity that detects nothing in every single trial is reported as not falsified —
the exact pathology of the flat corpus, reproduced at small n.

*(This floor was initially recorded as n=5. Checking the claim before asserting it
gave 0.4899 at n=4. The corrected value is pinned by
`test_kills_a_wrong_oracle_firing_floor`.)*

**Floor B — is x=0 evidence, or an accident?** The oracle firing is only
informative if a working entity is unlikely to produce x=0. Treating "works" as
p ≥ 0.25 and requiring 95% power:

```
power(n) = 1 − (1 − p)ⁿ  ≥  0.95
n ≥ ln(0.05) / ln(0.75) = 10.41  →  n = 11
```

| n | power against p ≥ 0.25 |
|---:|---:|
| 10 | 0.9437 |
| **11** | **0.9578** |

At n=11, `P(x = 0 | p = 0.25) = 0.0422` — so a zero is a genuine signal rather
than a plausible run of bad luck, and the interval it produces is [0, 0.2588],
comfortably below the 0.5 the oracle needs.

**n = 11 per entity**, because 11 > 4 and both floors must hold. 31 × 11 = **341**
positives.

**What n=11 explicitly does not buy.** At p̂ ≈ 0.9 the Wilson half-width at n=11 is
**0.181** (interval [0.623, 0.984]). That is not a recall estimate and the
pre-registration says so in the cell's own `note`. F3-4 reports
detected/not-detected per entity with a bound; it does not report per-entity
recall, and any later text that quotes one would be quoting a number this design
cannot support.

Reporting convention, fixed before data: two-sided 95% Wilson per entity,
**BH-adjusted across the 31 entities** within the exploratory detection family. An
entity is reported as unsupported-in-practice only if its upper bound is below 0.5.

---

## 5. Cost

| | Items | ApplyGuardrail text units |
|:---|---:|---:|
| As first sealed (flat) | 108 | 108 |
| As corrected | 368 | 368 |
| **Delta** | **+260** | **+260** |

260 additional `ApplyGuardrail` text units, inside Phase 1's ~$5 envelope and far
below the 100 rps rate ceiling. **Cumulative project spend at the time of this
finding: $0.** The correction is bounded by the corpus-authoring effort, not by
money — which is the reason it is affordable to get right rather than to argue
about.

---

## 6. How this was found, and the check that now holds it

It was not found by a check. It was found by opening the corpus in order to write
its build script, having previously cited it twice.

**The pre-registration was internally consistent while it was wrong.** Every
arithmetic relation among its numbers closed; the verifier's 120 assertions were
green. It said `108` and the corpus had 108 items. The error lived entirely in the
correspondence between the artifact and the question — a place no assertion was
looking.

That is the same defect class as `DEV-SEAL-2`, one screen further down the same
file, and it recurred **inside the amendment that recorded it**: the first draft of
this deviation put "4 more map after relabelling" and "25 of the SDK's 31 entity
types" into a YAML comment and a `why:` string. Both were wrong — 5 and 24. They
were wrong in prose, which is why nothing caught them; they were found by
recomputing the mapping table while writing this document.

So the fix is again structural, not numeric:

1. **Every count is now a data field**, in `corpora.pii.source_corpus_audit`, and
   the prose points at the block instead of restating it. The two figures that were
   wrong are no longer stated in any comment.
2. **The mapping table is pre-registered.** Which source label becomes which SDK
   entity type is fixed *before* any detection result exists. Relabelling after
   seeing which entities fire would let the corpus be tuned to the outcome, and it
   would be undetectable afterwards.
3. **`check_pii_source_audit()` recomputes the audit from the files on disk** —
   label counts, reusable/unmappable item counts, negatives — and from the **live
   SDK enumeration**, so `entity_types_from_sdk: 31` goes stale loudly rather than
   silently. Every mapping target is checked to be a name the SDK actually
   enumerates; `CREDIT_CARD` as its own target fails the gate.
4. **The mapping must cover exactly the labels on disk.** A label present in the
   corpus but absent from the table would be dropped from every count while leaving
   the audit self-consistent at a smaller label set — deletion being cheaper than
   falsification, one level down from where `DEV-SEAL-2` closed it.
5. **21 mutation tests**, including a parametrised arm that falsifies each of the
   nine audit counts individually. Written parametrised on purpose: the defect was
   *two* wrong numbers in one paragraph, and checking one of them would have left
   the other exactly as unverified as before.
6. **One test asserts the assertions are live.** `check_pii_source_audit` skips its
   item-count checks when the sibling corpus is absent, which is right for a reader
   who lacks that repository and fatal for a mutation suite — every item-count
   mutation would pass via the skip branch.
   `test_the_source_corpus_audit_assertions_are_live_not_skipped` copies the corpus
   into the mutant tree and asserts the skip message did **not** appear.
7. Assertion count **130 → 144**. Deleting `source_corpus_audit` is **rc=2**, not a
   traceback, via the precondition pass.

---

## 7. What is verifiable about this finding

```sh
python3 verify_prereg.py                                   # 144 assertions, sealed
python3 -m pytest claims/tests/test_prereg_verifier.py -q  # mutation suite
python3 -m pytest claims/tests/test_prereg_finding_numbers.py -q
./verify_phase0.sh                                         # 7/7 gates
```

Every figure in §2 and §4 of this document is recomputed by one of those commands
from either the corpus files or `lib/stats.py`. None is asserted here and checked
nowhere.

---

## 8. Consequence for the plan

The plan's Part 5 sentence was **right**, and the pre-registration's first sealing
of it was wrong. "Reuse the 108-case corpus, **extended to align with the 31 SDK
entity types**" already contained the correction; the extension clause was dropped
in the act of making the plan machine-checkable.

That is worth stating plainly, because the lesson is not "the plan was wrong". It
is that **a qualifier is the first thing lost when prose becomes a number**, and
the resulting number is then defended by every check built on top of it. Reusing a
corpus is only free when it was built to answer the same question; this one was
built to answer a different one, and the plan said so.
