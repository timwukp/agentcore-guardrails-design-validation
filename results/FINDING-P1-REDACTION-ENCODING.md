# FINDING P1-REDACTION-ENCODING — The live account ID got past both redaction layers into a commit, because both failed on the same character

**Status:** FIXED at both root causes. The pre-fix blob is **not** retractable — history is not
rewritten — so the identifier stays in the repository's history; the repository is **private**
(verified 2026-08-19), which makes that a **decision point before any future flip to public** rather
than a completed public disclosure
**Date:** 2026-08-19
**Class:** platform (a property of our own guards, not a claim about AWS or about the document
under test)
**Artifacts:** `check_redaction.py` (`scan_forms`), `lib/redact.py` (`_ARN_ACCOUNT_PCT`, `mask_text`),
`lib/tests/test_redaction_gate_encoding.py` (18 arms),
`results/phase1/F5-7b.json`, `FUTURE-WORK.md` item 35,
`session-logs/redaction-gate-20260819-pctfix.log` (the failing run),
`session-logs/redaction-gate-20260819-pctfix-2.log` (rc 0 over 737 files)

<!-- provenance
{
  "status": "INTERNAL",
  "evidence_runs": [],
  "note": "A property of our own redaction guards. It asserts nothing about AgentCore and licenses no amendment to the guardrails document, so there is no external state whose durability a replication would test — the equivalent of replication here is the mutation arm that restores the identifier and requires the gate to convict, which runs on every suite. Deliberately not a case finding: no verdict moved, and F5-7b's INCONCLUSIVE verdict, its oracle, its guards and every other field are byte-identical before and after the mask."
}
-->

## 0. The one-sentence version

The live AWS account ID went into a pushed commit, twenty times, in one verdict file, and the reason
neither of this project's two independent redaction layers saw it is that **both of them anchored the
identifier on `\b`, and the character in front of it was a letter.**

## 1. What was exposed, to whom, and for how long

| | |
|---|---|
| File | `results/phase1/F5-7b.json` |
| Occurrences of the live account ID | **20** |
| Pushed in | `3f3c398b`, 2026-08-14T17:02:41Z — the **only** commit that ever touched this path |
| Masked | 2026-08-19 |
| Exposure window | the file's entire life in the pushed tree, ~5 days |
| Repository visibility | **private** — `private: true`, `visibility: "private"`, 0 forks / 0 stargazers / 0 watchers / 0 subscribers, one collaborator (`timwukp`, admin). Verified by `gh api repos/…` on 2026-08-19, i.e. *after* the fact, which is the only kind of check available |
| Third-party read | **none evidenced.** Nor disproven: GitHub exposes no per-blob read log to a repository owner, so "nobody fetched it" is not a claim this document makes |
| sha256 before → after | `38e0ba4a…0de9635c` → `1d45454a…069a3414b7` |
| Bytes | 26,885 → 26,825 characters; 20 × 12 digits replaced by 20 × `<account>` |
| Everything else | unchanged. Verdict `INCONCLUSIVE` before and after; identical top-level keys; `json.loads` equal apart from the masked substrings |
| Other files affected | **none.** A whole-tree search (`evidence/` and the local-only state dirs excluded by policy, as they are never distributed) finds the identifier in no other distributable file |

The 20 occurrences all sit in one shape: a **botocore read-timeout message that quotes the invoke
URL**. F5-7b invokes an AgentCore runtime, and the runtime's ARN is a *path segment* of that URL, so
every colon inside it arrives percent-escaped. The message is kept because it is the case's own
evidence — F5-7b's finding is precisely that the invoke never received an HTTP response, so the
timeout text and the absence of a request id *are* the observation.

## 2. Why the gate could not see it

`check_redaction.py`'s account pattern was, and still is, `\b\d{12}\b`. In the published bytes the
character immediately before the twelve digits is the **trailing letter of the escape that replaced a
colon**. `\b` asserts a boundary between a word and a non-word character; a letter followed by a digit
is two word characters, so the boundary **cannot exist**, and the pattern could not fire no matter how
many times the gate read the file.

The same one-character property defeats four more of the gate's patterns on the same line:

| Pattern | Why encoding defeats it |
|---|---|
| `aws-account-id` — `\b\d{12}\b` | no word boundary after a letter |
| `arn` — `\barn:aws[a-z-]*:[a-z0-9-]*:` | requires literal colons |
| `s3-uri` | requires literal `://` |
| `private-ip` — `\b10\.…` | same boundary failure if the address were encoded |
| `vpc-or-subnet-id` — `\b(?:vpc|subnet|sg|eni)-…` | same |

So this is **one defect with five symptoms**, not five defects. That is what decided the fix.

## 3. Why the masker could not see it either — and why that is the real finding

`lib/redact.py`'s own docstring states the defence: a masker at the two writers and a gate that reads
the bytes are *independent*, so what lives in the gap is only "an identifier shape the masker does not
cover", and the gate stays the backstop.

Here they were **not independent**. `_ARN_ACCOUNT` requires literal colons; the registered-token pass
was `re.sub(rf"\b{aid}\b", …)`. Both broke on the same input, for the same reason, at the same
character. **Two layers that share an assumption are one layer**, and the assumption they shared was
not written down anywhere as an assumption — it was written down as `\b`, twice, in two files, by
someone reasoning about the same identifier in the same way both times. No amount of adding a third
layer of the same kind would have helped.

Worse, the gate **did** fire on this file. `results/phase1/F5-7b.json` carries a reviewed, path-scoped
ALLOW entry for `private-ip`, because the case builds its own VPC and the CIDR is in the record. A
human read that line, wrote a reason, and shipped the file. The file was *known to the gate and
reviewed by a person* — and the account ID was in the same records, three fields away.

## 4. The fix, at the cause rather than the instance

**Gate — `check_redaction.scan_forms(line)`.** Every pattern is now applied to each line **as written
and URL-decoded** (two decode rounds, since a second round is how `%` itself gets encoded). Patching
five regexes to accept encoded punctuation was rejected: it is five chances to miss the sixth, it
leaves the next encoding exactly as invisible, and it makes each pattern harder for a reader to check
by eye. Decoding closes the class in one place and lets every pattern keep being written against the
identifier's real shape. The as-written form is scanned **first and kept**, because decoding is lossy
in the direction that matters and an identifier plainly visible in the bytes must be reported against
the bytes. Lines with no `%` cost one comparison — the gate reads 48 MB per run.

**Masker — two changes.** `_ARN_ACCOUNT_PCT` masks the encoded ARN's account field, shape-based and
registry-free like `_ARN_ACCOUNT`, so it protects an account **nobody registered** (F7's instrument
enumerates a shared namespace; another team's account can arrive in our results and will never be in
`_KNOWN`). And the registered-token pass moved from `\b…\b` to `(?<!\d)…(?!\d)`: the property that
actually matters is *"not part of a longer **number**"* — that is what protects the
`US_BANK_ACCOUNT_NUMBER` corpus rows and 12-digit epochs, which are digit runs — while letters around
an account ID never make it less of a disclosure.

**Tests — `lib/tests/test_redaction_gate_encoding.py`, 24 arms.** Two assert the **old** anchors were
structurally blind, so the suite distinguishes a fix from a claim
(`feedback_identical_output_wrong_assertion`). One is a no-mutant control. One restores the identifier
into the real file and requires the gate to convict — under the same path whose ALLOW entry exists, so
it also proves that waiver does not excuse an account ID. Two assert the widened boundary did **not**
start masking corpus values or epochs. One asserts `scan_forms` returns more than one form, which is
the arm that reds if a later performance edit drops the decoded pass and silently reopens the whole
class. Six more arrived with §4b. Measured 2026-08-20 across the six redaction-related suites
(`test_redact`, `test_redaction_gate_encoding`, `test_redaction_gate_skips`,
`test_results_writes_are_masked`, `test_account_id_choke_point`, `test_scan_scope`): **114 arms pass**,
24 of them this finding's, the other 90 pre-existing and unchanged.

**Verification.** Full-tree gate: **rc 0 over 745 files, 48,061,072 bytes, 10,911 reviewed exceptions**
(rc read directly from the process, never through a pipe). The failing run immediately before the fix
is kept beside it: **rc 1, 45 findings**.

## 4b. The same defect at a second site, found on 2026-08-20 by mutation-testing a different gate

§4 fixed the encoding. It did not fix `\b`, and the encoding was only one way to break it.

Writing the payload gate for the platform (`platform/build/gate_payload.py`, which imports `PATTERNS`,
`allowed()` and `scan_forms()` from this module rather than restating them) meant writing an arm that
puts the account ID inside a file that will not decode as UTF-8 — a PNG text chunk or a compiled
bundle, which the payload gate reads as latin-1 rather than skipping. **That arm failed.** Not a test
defect: `\b` requires a non-word character on each side, and Python's `\w` is Unicode-aware, so a
**high byte is a word character**. `…\xff\xfe` + twelve digits has no leading boundary, exactly as
`%3A` had none.

The general form is worse than the binary case, because this repository ships prose in Chinese:

* `帳戶123456789012號` — CJK on both sides, no separator (the digits here are AWS's reserved
  documentation value, because this file is itself inside the gate's scan). Two zh-TW editions of the design
  document and two 61-slide zh-TW decks are in scope for the payload.
* any twelve-digit run adjacent to a latin-1 high byte, which is precisely what the payload gate's
  "scan undecodable files as latin-1" path manufactures.

**Why the obvious repair was rejected, with the measurement.** §4 already moved `lib/redact.py`'s
registered-token pass to `(?<!\d)…(?!\d)`, so adopting the same boundary here looks like consistency.
It was measured against the tree first: of **11,679** hex digests in scanned files, **281** contain a
run of exactly twelve digits. `(?<!\d)\d{12}(?!\d)` would raise 281 findings that are sha256
characters. `\b` is load-bearing *there* — and the asymmetry is that `lib/redact.py`'s pass matches a
**known literal account**, while this gate matches any 12-digit *shape*, so the two cannot share a
boundary rule.

**The fix is therefore a form, not a pattern.** `scan_forms()` now also yields each form with every
non-ASCII character replaced by a space. Every identifier the gate looks for is ASCII, so a non-ASCII
character can only ever be *around* one, where its only effect is to destroy the boundary; blanking it
restores the boundary without touching anything between ASCII letters, so CJK and high bytes stop
hiding identifiers **and the 281 digests keep their protection**. The replacement is one character for
one character, so a reported column still points at the same place. Findings are labelled
`(non-ASCII blanked)`, and because both repairs compose, `(url-decoded ×1 + non-ASCII blanked)` is a
label the gate can emit — an encoded identifier sitting in CJK prose needs both, and an arm asserts it.

**What stays blind, stated rather than implied.** An account ID glued directly to ASCII letters —
`x` + twelve digits + `y`, with ASCII letters touching both ends — is still invisible to this gate, and
that is the 281-digest trade taken knowingly.
An arm asserts the limit, so it is visible in the suite rather than inferred from its absence.

**Measured impact on the current tree: zero new findings.** rc 0 over 745 files and 48,061,072 bytes
with the widened scan, 67.4 s wall clock; the payload gate likewise rc 0 over 104 files with its 4
inherited exceptions unchanged. The widening is strictly stronger here — it convicts what the old form
could not and convicts nothing new.

**The note now travels with the form.** `scan_forms()` returns `(form, note)` pairs instead of a bare
list whose label a caller derived from the list index. Two independent reasons to add a form exist as
of today; a caller computing the label from a position is a caller that mislabels the day a third
arrives.

**What this says about §4.** The URL-encoding write-up called `%3A` "the" cause. It was an *instance*.
The cause is that a pattern anchored on `\b` makes a claim about **every character class that can
neighbour an identifier**, and the finding survived one round of "fixed at the cause" while that claim
went unexamined. The gate that found it was a gate for different bytes, written mutation-first — which
is the argument for both, not a coincidence.

## 5. What is NOT fixed, and will not be

**The history is not retractable.** The pre-fix blob remains reachable by SHA after any subsequent
commit, and this project's own rule is that history is never rewritten (`feedback_no_git_push`: pushes
go through the Git Data API; a force-push is not an operation this project performs). Masking forward
therefore does not un-write it.

What that means depends on visibility, and the visibility is **private** — so the accurate statement
is narrower than the one this document carried in its first draft ("treat the account ID as
disclosed"), and it is this:

- **the gate's severity is unchanged by the repository being private.** What failed is a
  *pre-publication* gate. Its entire purpose is to be correct before visibility widens, and it was
  wrong for five days over bytes it read on every run. Privacy is the reason there is no incident to
  report, not a reason the defect is smaller;
- **the residual item is a decision point, not a completed disclosure.** Before this repository is
  ever made public — or a fork, an export, a bundle or a support attachment is made from its history —
  the pre-fix blob is a thing that must be looked at and decided about. That belongs in the checklist
  governing such a flip, alongside the still-open `.log` gap below. Register item 35 carries it;
- **no third-party read is evidenced, and none is disproven.** A repository owner has no per-blob read
  log, so "nobody fetched it" is not available as a finding. What is available: 0 forks, 0 watchers,
  0 subscribers, one collaborator;
- **masking forward is proportionate rather than sufficient**, because an account ID is not a
  credential — it is an identifier that narrows reconnaissance. The things that would have made this
  an incident regardless of visibility (long-lived keys, bucket names, a role ARN granting anything)
  are absent, verified by the whole-tree scan in §1.

**The encoding family is not closed.** URL escaping is what shipped, and it is what the gate now
covers, to two rounds. JSON `:`, HTML entities, and base64 are the same defect wearing a
different alphabet, and the gate does **not** cover them today. Register item 35 records that as an
enumeration to be made explicit rather than as a gap a reader must infer — a docstring claiming a
scope is where the next instance hides (`feedback_guard_scope_is_a_claim`).

**Nor is the neighbour-character family.** §4b closes the non-ASCII half of it and states the half that
stays open — an identifier flanked by ASCII letters on both sides — with the measurement (281 of 11,679
hex digests) that says why the open half is a deliberate trade rather than an oversight. What makes this
enumerable at all is that `\b`'s claim is now written down: **a pattern anchored on `\b` asserts
something about every character class that can neighbour the identifier.** URL escaping turned a colon
into a letter; CJK and high bytes are word characters outright; ASCII letters were always word
characters and always will be.

**And the same class has a second, still-open instance, found while writing this document.** The
gate's `SCAN_EXT` is nine extensions; `.log` is not one of them, and `session-logs/` **is pushed to
the repository** (4 files on `main`, no `.gitignore` rule). The 7 local `.log` files happen to be
clean, which is luck:
producer logs and gate output are the text most likely to quote an ARN, and this window's own failing
gate run wrote one of them. "The gate passed" is therefore a statement about nine extensions, not
about the tree. Item 35 carries the closing condition, and it is a predicate rather than a tenth
extension.

## 6. What this changed about the platform being built

The leak was found by `platform/build/build_site_data.py`'s first successful build — by grepping the
derived payload, not by the gate. Two consequences, both already applied:

1. **The site payload is written OUTSIDE the repository** (`../grx-site-payload`, enforced in
   `main()`). Inside the repo, `check_redaction.py` would read a derived copy of every reviewed
   exception and need a second waiver for each: the first build produced **45 findings, 44 of which
   were second copies of two already-reviewed lines**, and the 45th was this one. A gate whose output
   is 98 % known-benign is a gate whose reader stops reading. The alternative — adding the payload to
   `SKIP_DIRS` — is the one change that would blind the gate to the exact bytes we serve, and
   `lib/tests/test_redaction_gate_skips.py` would go **green** on it, because its proxy for
   "published" is "tracked by git" and the payload is gitignored *and* published.
2. `platform/build/gate_payload.py` gates the payload where it lands, importing the same `PATTERNS`,
   `allowed()` and `scan_forms()` — import, never fork — and asserting set equality, both directions,
   between what it scanned, what the manifest declares and what is uploaded. Neither gate waives
   anything on the other's behalf: a payload hit is excused only by a rule that holds for any file
   (2,406 of 2,410) or by an exception a human wrote against the payload file's own declared **source**
   (exactly 4). **Written and mutation-tested 2026-08-20, 22 arms** — and its own arms are what
   produced §4b, plus a fixture defect that the no-mutant control caught after it had silenced ten of
   them. That is the return on writing the control arm first.

## 7. The generalisable lesson, stated as a rule

> **Two guards are only independent if they can fail for different reasons.** Write down what each one
> assumes about the identifier's *shape*, and if two guards assume the same thing, count them as one.

The corollary this incident supplies: `\b` is almost never the boundary you mean. What a redaction
pattern means is "not part of a longer value of the same kind" — for a number, `(?<!\d)…(?!\d)`; and
whatever punctuation you are anchoring on, some caller will hand you the same identifier with that
punctuation encoded.
