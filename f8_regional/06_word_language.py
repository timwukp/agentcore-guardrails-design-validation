#!/usr/bin/env python3
"""F8-7: are custom word filters really inert outside English, French and Spanish?

    python3 f8_regional/06_word_language.py --dry-run
    python3 f8_regional/06_word_language.py --n 3
    python3 f8_regional/06_word_language.py

§3.4, line 269: "Word filters support English, French, and Spanish only, on either tier."
The sealed oracle is `EXISTENCE`: TRUE if non-EN/FR/ES word filters are inert on both
tiers; FALSE if effective. The sibling case F1-26 states the same claim with a disjunction
the F8-7 text does not have — "rejected **or** provably inert" — and that difference
decides how one branch of this script behaves; see PRECONDITIONS below.

WHY THIS CASE CREATES ITS OWN GUARDRAILS
----------------------------------------
Two facts about the 1.43.67 service model, both verified rather than recalled:

  * `CreateGuardrail.wordPolicyConfig` has **exactly** the members
    `['wordsConfig', 'managedWordListsConfig']`. There is **no `tierConfig`**. The tier is
    a member of `contentPolicyConfig` and `topicPolicyConfig` only.
  * `GetGuardrail`'s `wordPolicy` has members `['words', 'managedWordLists']` — no `tier`
    either. So the tier is not merely unsettable on the word policy, it is unreadable
    there: the only place a tier can be *confirmed* is `contentPolicy.tier.tierName` or
    `topicPolicy.tier.tierName`.

"On either tier" therefore cannot be expressed by configuring the word policy two ways. It
has to be expressed by putting the word list on **two guardrails that differ in tier**, and
the tier has to be carried by a second policy block. This script carries it on
`contentPolicyConfig`, whose `filtersConfig` is required (`min: 1`) — so a single VIOLENCE
filter is attached at `inputStrength/outputStrength = NONE`, `inputAction/outputAction =
NONE`, `inputEnabled/outputEnabled = False`. That is the weakest legal filter the model
admits, and every one of the four knobs is set explicitly so the block cannot contribute a
detection that `hit_word` would never see but that `any_detection` in a later analysis
would. The provisioner's `words` guardrail cannot be used at all: it carries
`wordsConfig` only, with no tier-bearing block, so its tier is neither set nor readable.

WHAT IS AND IS NOT UNDER TEST — THE MECHANISM, NAMED
----------------------------------------------------
`wordPolicyConfig` has two mechanisms and they are not the same claim:

  * **custom words** (`wordsConfig[].text`) — a list we supply. Matching a supplied
    literal needs no lexicon, so the honest prior is that it works in any script, and a
    document sentence restricting it to three languages is falsifiable in the strong
    direction.
  * **managed word lists** (`managedWordListsConfig[].type`, enum `['PROFANITY']` and
    nothing else) — a list AWS supplies. Here language coverage is a real property of the
    service, because the list either contains a language's terms or does not.

This case tests the **custom** mechanism only, and the payload says so. Testing the managed
list would require authoring profanity in four scripts and then *labelling it as profanity*
— our labels would be the instrument, produced by one annotator, with no second rater and
therefore no κ (the Phase 0 gate is κ ≥ 0.80). An unmeasurable instrument reporting on a
service's lexicon is worth less than an explicit gap. Recorded as DEVIATIONS.md/DEV-P1-9.

THE DESIGN THAT KEEPS A "NOTHING BLOCKED" RESULT FROM BEING VACUOUS
------------------------------------------------------------------
"Non-EN/FR/ES word filters are inert" is confirmed by observing nothing block. That is
exactly the shape `feedback_vacuous_test_check` warns about: a guardrail that was never
created, never READY, or configured with an empty list produces the same clean silence as a
real language boundary. Three controls stand between silence and a TRUE verdict, and all
three are **preconditions**, not context:

  1. **A supported-language positive control.** `moonquake` — the same nonsense term F3-6
     already found blocking, chosen so the positive control has no natural-language
     ambiguity. If it does not block on a tier, that tier's word policy is not working and
     the inertness of anything else on it is uninformative.
  2. **Unlisted negative controls.** Two terms that are *not* on the list, sharing no
     character with any listed term. If one blocks, something other than our list is
     matching and every "blocked" reading below is unattributable.
  3. **A tier read-back.** `GetGuardrail.contentPolicy.tier.tierName` per probe. "Inert on
     both tiers" cannot be asserted from two guardrails whose tiers were requested and
     never confirmed.

THE ACCENTED CONTROLS ARE THE DISCRIMINATING PROBE
--------------------------------------------------
`réveillon` (fr) and `cumpleaños` (es) are single words in *supported* languages that are
not ASCII. They separate two hypotheses a Chinese-only probe cannot:

  * the boundary is **language** — the service has no lexicon for zh/ja/ko, and the two
    accented supported-language terms block normally; or
  * the boundary is **script or encoding** — anything outside ASCII fails, and the accented
    supported-language terms fail too, which would mean the document's sentence names the
    wrong reason even where its prediction happens to hold.

Both readings are reported under `script_vs_language`, and German (`de`, Latin script,
**not** one of the three) probes the same seam from the other side: a Latin-script term in
an unsupported language.

TWO SURFACES PER TERM
---------------------
Each term is sent twice: alone, and embedded in a sentence in its own language. Chinese and
Japanese are written without spaces, so if the filter tokenises on whitespace the embedded
surface can fail where the bare term succeeds — and a design that sent only the embedded
form would report a tokenisation property as a language property. Both surfaces are on
every row.

PRECONDITIONS, AND THE ONE BRANCH WHERE F8-7 AND F1-26 DIVERGE
--------------------------------------------------------------
If the service **rejects** a `CreateGuardrail` carrying non-EN/FR/ES words, a control-only
guardrail is created for that tier to attribute the rejection to the words rather than to
something else in the request. That outcome satisfies F1-26 ("rejected or provably inert")
and is *not* expressible under F8-7's sealed text, which says only "inert". A rejected
configuration is not an inert one — it is one that cannot be configured. So the verdict
becomes INCONCLUSIVE via `oracle.not_measured`, with the rejection, its error code and its
request id in the payload, and F1-26 named as the case whose sealed text covers it.

That is also why this script uses `oracle.not_measured` and never
`evaluate(obs_recorded(...))`: RECORDED is a sealed property of a case, meaning the
pre-registration declared the outcome unknown, and F8-7's kind is EXISTENCE — it made a
prediction. See DEVIATIONS.md/DEV-P1-8.

NO PRE-REGISTERED n
-------------------
`planned_n('F8-7')` is None; `n_met` is vacuous. This is not a rate: it is a conjunction
over (language × surface × tier) cells each decided by one deterministic response, and one
blocking non-EN/FR/ES term falsifies the claim outright regardless of how many did not.
"""

from __future__ import annotations

import hashlib
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R          # noqa: E402
import awsclients as A    # noqa: E402
import oracle as O        # noqa: E402
import phase1 as P        # noqa: E402
from evidence import EvidenceStore, capture  # noqa: E402

FAMILY = "f8"
CASE = "F8-7"
SIBLING = "F1-26"

# The two tiers the document's "on either tier" quantifies over. Held on
# `contentPolicyConfig`, because `wordPolicyConfig` has no tier member at all.
TIERS = ("CLASSIC", "STANDARD")

# The probe vocabulary. Constructed here rather than loaded from a corpus: the multilingual
# corpora carry no word-filter items, and `corpora_deviation/word_probe/probe.jsonl` is
# English-only by construction (it probes exact-vs-stem matching, which needs one language
# held constant). A term list is also the *configuration* of the guardrail under test, not
# just its input, so it cannot live in a file the provisioner never reads.
#
# `supported` marks the three languages §3.4 says are covered. Every term is a single
# token, benign, and under the model's 100-character maximum for `wordsConfig[].text`.
LISTED: tuple[dict[str, Any], ...] = (
    # Supported languages. `moonquake` is the positive control the preconditions depend on;
    # the other two are single words in supported languages that are NOT ASCII, which is
    # what separates a language boundary from a script boundary.
    {"lang": "en", "term": "moonquake", "supported": True,
     "carrier": "The observatory logged a {t} last night.",
     "why": "positive control; the same nonsense term F3-6 found blocking, so the control "
            "has no natural-language ambiguity"},
    {"lang": "fr", "term": "réveillon", "supported": True,
     "carrier": "Le rapport mentionne un {t} de plus.",
     "why": "supported language, non-ASCII: separates a language boundary from a script "
            "boundary"},
    {"lang": "es", "term": "cumpleaños", "supported": True,
     "carrier": "El informe menciona un {t} más.",
     "why": "supported language, non-ASCII (ñ), same discriminating role as fr"},
    # Unsupported languages. The four CJK ones are `phase1.UNSUPPORTED_LANGS`, so this case
    # and F8-2/F8-3 quantify over the same set; `de` and `ru` are additions this script
    # declares, not sealed constants.
    {"lang": "zh-TW", "term": "颱風警報", "supported": False,
     "carrier": "報告提到昨晚的{t}。",
     "why": "Traditional-only orthography (颱, 風): distinct bytes from the zh-CN probe"},
    {"lang": "zh-CN", "term": "台风警报", "supported": False,
     "carrier": "报告提到昨晚的{t}。",
     "why": "Simplified-only orthography; shares no codepoint with the zh-TW probe, so the "
            "two are genuinely separate trials rather than one term counted twice"},
    {"lang": "ja", "term": "月震観測", "supported": False,
     "carrier": "報告書は昨夜の{t}に言及した。",
     "why": "kanji compound; Japanese is written without spaces, so the embedded surface "
            "also probes whitespace tokenisation"},
    {"lang": "ko", "term": "달지진관측", "supported": False,
     "carrier": "보고서는 어젯밤의 {t}을 언급했다.",
     "why": "Hangul; a third script among the unsupported set"},
    {"lang": "de", "term": "Mondbebenmessung", "supported": False,
     "carrier": "Der Bericht nennt eine {t} von gestern.",
     "why": "LATIN SCRIPT, unsupported language. The other side of the same seam as the "
            "accented supported terms: if this blocks and zh/ja/ko do not, the boundary is "
            "script; if it does not block, the boundary really is language"},
    {"lang": "ru", "term": "лунотрясение", "supported": False,
     "carrier": "В отчёте упоминается {t} прошлой ночью.",
     "why": "Cyrillic: a non-CJK, non-Latin script, so 'not ASCII' and 'CJK' do not "
            "co-vary across the unsupported set"},
)

# Terms deliberately NOT put on the list. A block on one of these means something other
# than our word list is matching, which would make every 'blocked' reading unattributable —
# so this is a precondition, not context.
#
# The separation property they must have is checked at startup rather than asserted here,
# and it is not the same property in every script. In Latin script a shared *letter* is
# harmless — every English word shares letters with `réveillon`. In CJK a shared
# *ideograph* is not harmless: 報 is a morpheme, so a character-level matcher would fire
# `颱風警報` on any text containing 報, and the zh-TW carrier below was rewritten to drop
# `報告` for exactly that reason. So the rule is: no substring containment either way in
# any script, plus no shared codepoint above Latin Extended-B. (F3-6 probes substring
# behaviour deliberately, in English, with surfaces designed for it; here it would be a
# confound.)
UNLISTED: tuple[dict[str, Any], ...] = (
    {"lang": "en", "term": "quaxlinate",
     "carrier": "The observatory logged a {t} last night."},
    {"lang": "zh-TW", "term": "地層下陷",
     "carrier": "昨晚的{t}情況嚴重。"},
)

LABEL_LISTED_SUPPORTED = "LISTED_SUPPORTED"
LABEL_LISTED_UNSUPPORTED = "LISTED_UNSUPPORTED"
LABEL_UNLISTED = "UNLISTED"

# The one supported term whose blocking makes every other reading interpretable.
CONTROL_TERM = "moonquake"


def item_id(label: str, text: str, extra: str) -> str:
    """Content hash over everything that varies between requests.

    Same construction as `corpora/build.py` and `corpora_deviation/build_deviation.py`, and
    `extra` carries the tier: the same text is sent to two guardrails, and `arms.run_arm`
    skips a trial the checkpoint already holds. Without the tier in the id, the STANDARD arm
    would resume onto the CLASSIC arm's rows and report 22 usable trials for a tier it never
    called. (`Checkpoint` keys per arm, so this is belt and braces — but the id is also the
    join key in the analysis, and two tiers sharing one id would collide there too.)
    """
    return hashlib.sha256(f"{label}\x00{text}\x00{extra}".encode()).hexdigest()[:12]


def items_for(tier: str) -> list[dict[str, Any]]:
    """The 22 probe items for one tier: 9 listed terms x 2 surfaces, plus 2 unlisted x 2."""
    out: list[dict[str, Any]] = []
    for spec in LISTED:
        label = (LABEL_LISTED_SUPPORTED if spec["supported"]
                 else LABEL_LISTED_UNSUPPORTED)
        for surface, text in (("alone", spec["term"]),
                              ("embedded", spec["carrier"].format(t=spec["term"]))):
            out.append({"id": item_id(label, text, tier), "label": label,
                        "slot": spec["lang"], "surface": surface,
                        "term": spec["term"], "lang": spec["lang"],
                        "supported": spec["supported"], "tier": tier, "text": text})
    for spec in UNLISTED:
        for surface, text in (("alone", spec["term"]),
                              ("embedded", spec["carrier"].format(t=spec["term"]))):
            out.append({"id": item_id(LABEL_UNLISTED, text, tier),
                        "label": LABEL_UNLISTED,
                        "slot": spec["lang"], "surface": surface,
                        "term": spec["term"], "lang": spec["lang"],
                        "supported": None, "tier": tier, "text": text})
    return out


def vocabulary_check() -> dict[str, Any]:
    """Assert the probe vocabulary has the properties the design claims for it.

    Run before any AWS call and fatal, because each property below is one this script's
    reasoning rests on, and each is easy to break with a one-character edit months later:

      * no unlisted term contains, or is contained by, a listed one, and none shares a
        non-Latin codepoint with one (else a substring or character-level match is recorded
        as a spurious detection and the negative control fires by construction — see the
        note on UNLISTED for why the rule is script-dependent);
      * no unlisted term appears in any *carrier sentence* of a listed term, in either
        direction. The carriers are sent as their own trials, so a listed term whose
        carrier happens to contain an unlisted term would make that trial ambiguous;
      * no two listed terms are equal (two languages sharing bytes would be one trial
        reported as two);
      * every term is within the model's `wordsConfig[].text` maximum of 100;
      * the positive control is on the list.
    """
    listed = [s["term"] for s in LISTED]
    problems: list[str] = []
    if len(set(listed)) != len(listed):
        problems.append(f"listed terms are not distinct: {listed}")
    if CONTROL_TERM not in listed:
        problems.append(f"the positive control {CONTROL_TERM!r} is not on the list")
    for s in LISTED + UNLISTED:
        if not 1 <= len(s["term"]) <= 100:
            problems.append(f"{s['term']!r} is {len(s['term'])} chars; the model's "
                            f"wordsConfig[].text maximum is 100")
        if s["term"] not in s["carrier"].format(t=s["term"]):
            problems.append(f"{s['term']!r} does not appear in its own carrier sentence")
    for u in UNLISTED:
        if u["term"] in listed:
            problems.append(f"unlisted term {u['term']!r} is on the list")
        for s in LISTED:
            if u["term"] in s["term"] or s["term"] in u["term"]:
                problems.append(
                    f"unlisted {u['term']!r} and listed {s['term']!r} contain one another; "
                    f"a substring matcher would fire the negative control by construction")
            # Codepoints above Latin Extended-B (U+024F) only. A shared Latin letter is
            # not a substring risk — every English word shares letters with `réveillon` —
            # but a shared ideograph is a shared morpheme.
            shared = sorted(c for c in set(u["term"]) & set(s["term"]) if ord(c) > 0x24F)
            if shared:
                problems.append(
                    f"unlisted {u['term']!r} shares non-Latin {shared} with listed "
                    f"{s['term']!r}; a character-level matcher would fire the negative "
                    f"control by construction")
            if u["term"] in s["carrier"].format(t=s["term"]):
                problems.append(
                    f"unlisted {u['term']!r} appears in listed {s['term']!r}'s carrier "
                    f"sentence, so that carrier trial would be ambiguous")
            if s["term"] in u["carrier"].format(t=u["term"]):
                problems.append(
                    f"listed {s['term']!r} appears in unlisted {u['term']!r}'s carrier "
                    f"sentence, so the negative control would fire by construction")
    return {
        "listed": listed,
        "unlisted": [u["term"] for u in UNLISTED],
        "n_listed_supported": sum(1 for s in LISTED if s["supported"]),
        "n_listed_unsupported": sum(1 for s in LISTED if not s["supported"]),
        "max_term_len": max(len(s["term"]) for s in LISTED + UNLISTED),
        "sdk_max_term_len": 100,
        "problems": problems,
        "ok": not problems,
    }


def word_config() -> dict[str, Any]:
    """`wordPolicyConfig` carrying every listed term, and nothing else.

    `managedWordListsConfig` is deliberately absent — see the module docstring on why the
    managed PROFANITY list is a separate claim this case does not test. Every action and
    enabled flag is set explicitly rather than defaulted: `inputAction` defaults are not
    documented as stable, and a term that was configured with `NONE` would return
    `detected=True, action=NONE`, which `phase1.hit_word` counts as a hit and a reader
    would take for a block.
    """
    return {"wordsConfig": [
        {"text": s["term"], "inputAction": "BLOCK", "outputAction": "BLOCK",
         "inputEnabled": True, "outputEnabled": True} for s in LISTED]}


def control_only_word_config() -> dict[str, Any]:
    """The same policy with the supported-language terms only.

    Created only if the full config is REJECTED, to attribute the rejection: if this one is
    accepted, the non-EN/FR/ES words are what the service refused, which is F1-26's
    "rejected" branch. If it is also rejected, the rejection is about something else in the
    request and neither case's oracle is engaged.
    """
    return {"wordsConfig": [
        {"text": s["term"], "inputAction": "BLOCK", "outputAction": "BLOCK",
         "inputEnabled": True, "outputEnabled": True}
        for s in LISTED if s["supported"]]}


def tier_config(tier: str) -> dict[str, Any]:
    """The weakest legal content policy that can carry a tier.

    `contentPolicyConfig` requires `filtersConfig` with `min: 1`, so a tier cannot be
    attached without a filter. All four knobs on that filter are set to their inert values
    explicitly, so the block cannot contribute a detection to any later analysis that reads
    `arms.any_detection` over these rows.
    """
    return {"filtersConfig": [{"type": "VIOLENCE",
                               "inputStrength": "NONE", "outputStrength": "NONE",
                               "inputAction": "NONE", "outputAction": "NONE",
                               "inputEnabled": False, "outputEnabled": False}],
            "tierConfig": {"tierName": tier}}


def wait_and_read(client, store, lim, gid: str, *,
                  timeout_s: int = 240, sleep=time.sleep) -> dict[str, Any]:
    """Poll GetGuardrail until the guardrail leaves CREATING, then read the tier back.

    Two jobs in one call because they need the same response. `CreateGuardrail` returns
    `status=CREATING`: applying against a guardrail that has not finished building fails in
    a way `lib/checkpoint.py` records as a transient error, so 22 items would land in the
    failure map and the arm would report `n_usable=0` for a guardrail that was merely not
    ready yet.

    The tier is read off `contentPolicy.tier.tierName` because that is the only place it is
    readable: `GetGuardrail`'s `wordPolicy` has members ['words', 'managedWordLists'] and
    no `tier`. `words_configured` is read back for the same reason the tier is — a guardrail
    whose word list did not persist would produce exactly the clean silence a TRUE verdict
    is built from.
    """
    waited = 0.0
    rec = None
    while waited < timeout_s:
        lim.wait("GetGuardrail")
        rec = capture(store, "get_guardrail", client,
                      guardrailIdentifier=gid, guardrailVersion="DRAFT")
        if not rec.ok or (rec.response or {}).get("status") != "CREATING":
            break
        sleep(3.0)
        waited += 3.0
    resp = (rec.response or {}) if rec else {}
    status = resp.get("status", "TIMEOUT_STILL_CREATING" if rec else "NO_RESPONSE")
    words = [w.get("text") for w in ((resp.get("wordPolicy") or {}).get("words") or [])]
    return {
        "ok": bool(rec and rec.ok),
        "status": status,
        "ready": status == "READY",
        "status_reasons": resp.get("statusReasons") or [],
        "tier_read_back": ((resp.get("contentPolicy") or {}).get("tier") or {})
        .get("tierName"),
        "words_configured": words,
        "n_words_configured": len(words),
        "word_policy_members_seen": sorted((resp.get("wordPolicy") or {}).keys()),
        "waited_s": waited,
        "error_code": (rec.error_code or None) if rec else "NO_CALL",
        "request_id": rec.request_id if rec else "",
        "why_tier_from_content_policy": (
            "GetGuardrail's wordPolicy has members ['words', 'managedWordLists'] and no "
            "`tier`; contentPolicy.tier.tierName is the only place the tier is readable, "
            "which is also why the tier had to be requested on contentPolicyConfig"),
        "evidence": rec.path if rec else "",
    }


def per_cell(rows: list[dict]) -> dict[str, Any]:
    """(label, language, surface) -> blocked?, over one tier's rows.

    The label is in the key, not only in the value. `slot` is the language, and the two
    UNLISTED negative controls deliberately reuse the slots `en` and `zh-TW` so that each
    control sits in the same language as a listed term — which means a `slot/surface` key
    collides for exactly those four rows. Keying on `slot/surface` alone silently overwrote
    the `moonquake` positive control's two cells and the zh-TW listed term's two cells with
    the negative controls' rows: 22 trials reported as 18 cells, and the two cells the
    precondition rests on replaced by rows whose expected outcome is the opposite.

    The overwrite did not change any verdict — `precondition` and `unsupported_blocks` are
    computed from `t["rows"]` directly, never from this map — so it would have travelled
    into the result file as a quietly wrong evidence table that a reader auditing the
    control would have read as a control that did not block.
    """
    out: dict[str, Any] = {}
    for r in rows:
        key = f"{r['label']}/{r['slot']}/{r['surface']}"
        assert key not in out, f"two rows share the cell key {key!r}"
        out[key] = {"label": r["label"], "lang": r["slot"], "surface": r["surface"],
                    "hit": bool(r["hit"]),
                    "action": r["action"],
                    "words_detected": r["words_detected"],
                    "detected_types": r["detected_types"],
                    "request_id": r["request_id"]}
    return out


def main(argv: list[str] | None = None) -> int:                     # noqa: C901
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)

    vocab = vocabulary_check()
    if not vocab["ok"]:
        # Before any AWS call, and fatal. Every problem it can report is one the design's
        # reasoning depends on, and each would produce a result that looks clean.
        print("FATAL: the probe vocabulary violates a property this design rests on:",
              file=sys.stderr)
        for p in vocab["problems"]:
            print(f"  - {p}", file=sys.stderr)
        return 2

    plan = [(f"words-{t.lower()}", f"constructed in-script ({t})", len(items_for(t)))
            for t in TIERS]
    if args.n is not None:
        plan = [(lbl, corpus, min(n, args.n)) for lbl, corpus, n in plan]

    if args.dry_run:
        return P.dry_run_banner(
            CASE, plan,
            # The arm plan counts ApplyGuardrail only, so `operations` is left to default
            # to it; the control-plane calls are named in `extra` because they are not
            # trials and folding them into the total would put two operations under one
            # label. `mutations` is NOT 0: this case creates guardrails, and a banner
            # printing "no resource is created" before a script that creates two is the
            # exact label-vs-computation defect this project screens for.
            mutations=len(TIERS),
            extra=[
                f"plus {len(TIERS)} CreateGuardrail + up to "
                f"{len(TIERS)} DeleteGuardrail and {len(TIERS)}+ GetGuardrail calls "
                f"(control-plane, no text units). 'up to', because a REJECTED create "
                f"leaves nothing to delete and adds one control-only create instead",
                f"the tier is held on contentPolicyConfig.tierConfig: "
                f"wordPolicyConfig has NO tierConfig, and GetGuardrail's wordPolicy has no "
                f"`tier` either, so the tier is only settable and only readable via "
                f"contentPolicy",
                f"vocabulary: {vocab['n_listed_supported']} supported + "
                f"{vocab['n_listed_unsupported']} unsupported listed terms x 2 surfaces, "
                f"plus {len(UNLISTED)} unlisted negative controls x 2 surfaces",
                f"preconditions, all fatal to the verdict rather than reported beside it: "
                f"the {CONTROL_TERM!r} positive control blocks on BOTH tiers; no unlisted "
                f"term blocks; the tier is read back from GetGuardrail on both probes",
                "the managed PROFANITY word list is NOT tested — a separate claim needing "
                "profanity we would have to author and label ourselves, with one annotator "
                "and therefore no kappa (DEVIATIONS.md/DEV-P1-9)",
                f"a REJECTED create satisfies {SIBLING}'s 'rejected or provably inert' and "
                f"NOT {CASE}'s 'inert', so that branch returns INCONCLUSIVE via "
                f"oracle.not_measured rather than a verdict",
                "this and F8-5 are the only Phase 1 cases that create AWS resources; "
                "neither touches results/phase1_guardrails.json"])

    run_id = P.resolve_run(args)
    is_smoke = args.n is not None
    store = EvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()

    expires = (datetime.now(timezone.utc) + timedelta(hours=2)) \
        .replace(microsecond=0).isoformat()
    tags = [{"key": k, "value": v}
            for k, v in sorted(A.tags_for(run_id, expires).items())]

    f = A.factory(args.region)
    client = f.bedrock()
    lim = A.limiter()

    probes: list[P.ProbeGuardrail] = []
    made: dict[str, dict[str, Any]] = {}
    deletions: list[dict[str, Any]] = []
    rejected_full: list[dict[str, Any]] = []
    try:
        for tier in TIERS:
            p = P.create_probe_guardrail(
                client, store, lim,
                label=f"words-{tier.lower()}",
                name=f"grx-gr-f8-7-{tier.lower()}-{run_id}",
                description=f"F8-7 word-filter x language probe, tier {tier}",
                tags=tags,
                config={"wordPolicyConfig": word_config(),
                        "contentPolicyConfig": tier_config(tier)},
                tier=tier, n_words=len(LISTED))
            probes.append(p)
            if not p.accepted:
                # The rejection is data. A control-only create attributes it: accepted here
                # means the non-EN/FR/ES words are what the service refused.
                print(f"  {tier}: CreateGuardrail REJECTED ({p.error_code}) — "
                      f"creating a control-only probe to attribute the rejection",
                      file=sys.stderr)
                c = P.create_probe_guardrail(
                    client, store, lim,
                    label=f"control-only-{tier.lower()}",
                    name=f"grx-gr-f8-7-ctl-{tier.lower()}-{run_id}",
                    description=f"F8-7 attribution probe: supported-language terms only, "
                                f"tier {tier}",
                    tags=tags,
                    config={"wordPolicyConfig": control_only_word_config(),
                            "contentPolicyConfig": tier_config(tier)},
                    tier=tier, n_words=vocab["n_listed_supported"])
                probes.append(c)
                rejected_full.append({
                    "tier": tier,
                    "full_config_error_code": p.error_code,
                    "full_config_error_message": p.error_message,
                    "full_config_http_status": p.http_status,
                    "full_config_request_id": p.request_id,
                    "control_only_accepted": c.accepted,
                    "control_only_error_code": c.error_code,
                    "control_only_request_id": c.request_id,
                    "attribution": (
                        "the supported-language-only policy was accepted, so the "
                        "non-EN/FR/ES words are what the service refused"
                        if c.accepted else
                        "the supported-language-only policy was ALSO refused, so the "
                        "rejection is not attributable to the non-EN/FR/ES words and "
                        "neither oracle is engaged"),
                    "evidence": [p.evidence, c.evidence],
                })
                continue
            pre = wait_and_read(client, store, lim, p.guardrail_id)
            made[tier] = {"guardrail_id": p.guardrail_id, "name": p.name,
                          "request_id": p.request_id, "evidence": p.evidence, **pre}
            print(f"  {tier}: {p.guardrail_id}  status={pre['status']}  "
                  f"tier_read_back={pre['tier_read_back']}  "
                  f"words_configured={pre['n_words_configured']}")

        tallies: list[dict[str, Any]] = []
        if not rejected_full and all(made[t]["ready"] for t in TIERS):
            specs, corpora = [], []
            for tier in TIERS:
                items = items_for(tier)[:args.n] if args.n else items_for(tier)
                specs.append(R.ArmSpec(case_id=CASE, family=FAMILY,
                                       corpus=f"constructed:{tier}",
                                       guardrail_id=made[tier]["guardrail_id"],
                                       region=args.region,
                                       label=f"words-{tier.lower()}",
                                       hit=P.hit_word))
                corpora.append(items)
            tallies = P.run_arms(specs, corpora, run_id=run_id, is_smoke=is_smoke)
    finally:
        if any(x.guardrail_id for x in probes):
            print(f"\ndeleting "
                  f"{sum(1 for x in probes if x.guardrail_id)} probe guardrail(s)...")
            deletions = P.delete_probe_guardrails(client, store, lim, probes)
            for d in deletions:
                if not d["deleted"]:
                    print(f"  WARNING: {d['guardrail_id']} not deleted "
                          f"({d['error_code']}); Phase 99's tag sweep will flag it",
                          file=sys.stderr)

    residue = P.probe_residue(probes, deletions)

    common = {
        "run_id": run_id, "is_smoke": is_smoke,
        "mutations": len(probes),
        "probe_guardrails": {t: {k: v for k, v in row.items()} for t, row in made.items()},
        "vocabulary": vocab,
        "vocabulary_provenance": (
            "constructed in this script, not loaded from a corpus: the multilingual "
            "corpora carry no word-filter items, corpora_deviation/word_probe is "
            "English-only by construction, and a term list is the CONFIGURATION of the "
            "guardrail under test as well as its input"),
        "term_rationale": {s["lang"]: s["why"] for s in LISTED},
        "mechanism_under_test": (
            "wordPolicyConfig.wordsConfig (custom terms) only. "
            "managedWordListsConfig (enum ['PROFANITY'] and nothing else) is a DIFFERENT "
            "claim about a lexicon AWS supplies, and testing it would require authoring "
            "and labelling profanity in four scripts with one annotator and therefore no "
            "kappa — see DEVIATIONS.md/DEV-P1-9"),
        "tier_carrier": (
            "contentPolicyConfig.tierConfig.tierName, with one VIOLENCE filter at "
            "NONE/NONE, actions NONE and both enabled flags False — the weakest filter "
            "`filtersConfig` (min: 1) admits. wordPolicyConfig has no tierConfig member, "
            "so 'on either tier' cannot be expressed on the word policy itself"),
        "deletions": deletions,
        "residue": residue,
        "sibling_case": {
            "case_id": SIBLING,
            "oracle": O.oracle_text(SIBLING),
            "difference": ("F1-26 accepts 'rejected OR provably inert'; F8-7's sealed text "
                           "says only 'inert'. The disjunction decides the "
                           "rejected-create branch of this script"),
        },
        "instrument": ("CreateGuardrail (wordPolicyConfig + contentPolicyConfig.tierConfig) "
                       "-> GetGuardrail (tier and word list read back) -> ApplyGuardrail "
                       "(source=INPUT, outputScope=FULL), wordPolicy assessment"),
    }

    # ---- the branch F8-7's sealed text does not cover -------------------------------
    if rejected_full:
        rec = O.not_measured(
            CASE,
            "CreateGuardrail rejected a word policy carrying non-EN/FR/ES terms, so their "
            "inertness could not be observed. A refused configuration is not an inert one",
            rejections=rejected_full)
        P.emit(CASE, rec, {**common, "billable_calls": 0,
                           "rejections": rejected_full,
                           "why_inconclusive": (
                               f"the rejection satisfies {SIBLING}'s 'rejected or provably "
                               f"inert' disjunction and is recorded in full for it; "
                               f"{CASE}'s sealed text says 'inert', and a configuration "
                               f"that cannot be created was never observed to be inert"),
                           "arms": "ApplyGuardrail — NOT RUN"}, store)
        return 1 if not residue["clean"] else 0

    not_ready = {t: made[t]["status"] for t in TIERS if not made.get(t, {}).get("ready")}
    if not_ready:
        rec = O.not_measured(
            CASE,
            f"a probe guardrail did not reach READY ({not_ready}), so ApplyGuardrail "
            f"against it would fail for a reason unrelated to language support",
            probe_status=not_ready)
        P.emit(CASE, rec, {**common, "billable_calls": 0,
                           "arms": "ApplyGuardrail — NOT RUN"}, store)
        return 2

    rc = P.require_measured(tallies, is_smoke=is_smoke)
    if rc:
        return rc

    # ---- preconditions, evaluated on the data -------------------------------------
    by_tier = {t["arm"].replace("words-", "").upper(): t for t in tallies}
    control: dict[str, Any] = {}
    unlisted_blocks: list[dict[str, Any]] = []
    for tier, t in by_tier.items():
        ctl = [r for r in t["rows"] if r["label"] == LABEL_LISTED_SUPPORTED
               and r["slot"] == "en"]
        control[tier] = {
            "n": len(ctl),
            "blocked": [r["surface"] for r in ctl if r["hit"]],
            "not_blocked": [r["surface"] for r in ctl if not r["hit"]],
            "any_surface_blocked": any(r["hit"] for r in ctl),
            "request_ids": [r["request_id"] for r in ctl],
        }
        unlisted_blocks += [
            {"tier": tier, "lang": r["slot"], "surface": r["surface"],
             "words_detected": r["words_detected"], "request_id": r["request_id"]}
            for r in t["rows"] if r["label"] == LABEL_UNLISTED and r["hit"]]

    tiers_confirmed = {t: made[t]["tier_read_back"] for t in TIERS}
    tier_mismatch = {t: v for t, v in tiers_confirmed.items() if v != t}
    control_dead = [t for t, c in control.items() if not c["any_surface_blocked"]]

    precondition = {
        "positive_control": {"term": CONTROL_TERM, "per_tier": control,
                             "why_fatal": ("a word policy that does not block its own "
                                           "supported-language control produces the same "
                                           "silence as a language boundary")},
        "negative_controls": {"terms": [u["term"] for u in UNLISTED],
                              "blocks": unlisted_blocks,
                              "why_fatal": ("a block on a term we never listed means "
                                            "something other than the list is matching, "
                                            "and every 'blocked' reading below becomes "
                                            "unattributable")},
        "tier_read_back": {"requested_vs_read": tiers_confirmed,
                           "mismatch": tier_mismatch,
                           "why_fatal": ("'inert on both tiers' cannot be asserted from "
                                         "two guardrails whose tiers were requested and "
                                         "never confirmed")},
        "sound": not (control_dead or unlisted_blocks or tier_mismatch),
    }

    per_tier_cells = {tier: per_cell(t["rows"]) for tier, t in by_tier.items()}
    per_lang = {}
    for s in LISTED:
        per_lang[s["lang"]] = {
            "term": s["term"], "documented_as_supported": s["supported"],
            "blocked_by_tier": {
                tier: sorted(r["surface"] for r in t["rows"]
                             if r["slot"] == s["lang"] and r["label"] != LABEL_UNLISTED
                             and r["hit"])
                for tier, t in by_tier.items()},
            "cells_total_by_tier": {
                tier: sum(1 for r in t["rows"] if r["slot"] == s["lang"]
                          and r["label"] != LABEL_UNLISTED)
                for tier, t in by_tier.items()},
        }

    unsupported_blocks = [
        {"tier": tier, "lang": r["slot"], "term": next(
            (s["term"] for s in LISTED if s["lang"] == r["slot"]), ""),
         "surface": r["surface"], "words_detected": r["words_detected"],
         "action": r["action"], "request_id": r["request_id"]}
        for tier, t in by_tier.items() for r in t["rows"]
        if r["label"] == LABEL_LISTED_UNSUPPORTED and r["hit"]]

    if not precondition["sound"]:
        reasons = []
        if control_dead:
            reasons.append(f"the {CONTROL_TERM!r} positive control did not block on "
                           f"{control_dead}")
        if unlisted_blocks:
            reasons.append(f"{len(unlisted_blocks)} unlisted term(s) blocked")
        if tier_mismatch:
            reasons.append(f"the tier could not be confirmed: {tier_mismatch}")
        rec = O.not_measured(CASE, "; ".join(reasons), precondition=precondition)
        P.emit(CASE, rec, {**common,
                           "billable_calls": sum(t["n_usable"] for t in tallies),
                           "precondition": precondition,
                           "per_tier_cells": per_tier_cells,
                           "per_language": per_lang,
                           "unsupported_language_blocks": unsupported_blocks,
                           "why_inconclusive": (
                               "the data is recorded in full, and it does not decide the "
                               "oracle: an inertness claim measured through an instrument "
                               "that was not shown to work is the vacuous-test defect this "
                               "project screens the document for")}, store)
        return 0 if residue["clean"] else 1

    # ---- the verdict --------------------------------------------------------------
    # TRUE means the document is right: no term in an unsupported language blocked, on
    # either tier. One blocking cell falsifies it — this is a conjunction over cells, not
    # a rate, so no interval is available or needed.
    observed = not unsupported_blocks
    n_unsupported_cells = sum(1 for t in by_tier.values() for r in t["rows"]
                              if r["label"] == LABEL_LISTED_UNSUPPORTED)
    # Pooled over both tiers: the conjunction is over every cell on every tier, so the
    # denominator is the whole two-tier grid, not one tier's arm.
    o = P.obs_existence(
        CASE, observed, n=sum(t["n_usable"] for t in tallies),
        n_unsupported_cells=n_unsupported_cells,
        n_unsupported_blocks=len(unsupported_blocks),
        tiers=list(TIERS))
    rec = O.evaluate(o)

    accented_supported = {
        s["lang"]: {
            "term": s["term"],
            "blocked_by_tier": per_lang[s["lang"]]["blocked_by_tier"],
        } for s in LISTED if s["supported"] and s["lang"] != "en"}
    latin_unsupported = {
        s["lang"]: {"term": s["term"],
                    "blocked_by_tier": per_lang[s["lang"]]["blocked_by_tier"]}
        for s in LISTED if not s["supported"] and s["lang"] == "de"}

    P.emit(CASE, rec, {
        **common,
        "billable_calls": sum(t["n_usable"] for t in tallies),
        "precondition": precondition,
        "per_language": per_lang,
        "per_tier_cells": per_tier_cells,
        "unsupported_language_blocks": unsupported_blocks,
        "verdict_rule": (
            "TRUE iff NO listed term in an unsupported language blocked on EITHER tier. A "
            "conjunction over (language x surface x tier) cells, each decided by one "
            "deterministic response — not a rate, so no interval is reported"),
        "script_vs_language": {
            "accented_supported_languages": accented_supported,
            "latin_script_unsupported_language": latin_unsupported,
            "reads_as": (
                "if the accented supported-language terms block and the CJK/Cyrillic ones "
                "do not, the boundary the document describes is a LANGUAGE boundary. If "
                "the accented supported-language terms also fail, the boundary is SCRIPT "
                "or encoding and the document names the wrong reason even where its "
                "prediction holds. If the German term blocks while zh/ja/ko do not, the "
                "boundary follows script rather than the three-language list"),
        },
        "surface_effect": {
            tier: {surface: sum(1 for r in t["rows"]
                                if r["surface"] == surface and r["hit"])
                   for surface in ("alone", "embedded")}
            for tier, t in by_tier.items()},
        "surface_effect_reads_as": (
            "Chinese and Japanese are written without spaces. A term that blocks alone but "
            "not when embedded is a whitespace-tokenisation property, and a design that "
            "sent only the embedded form would have published it as a language property"),
        "no_power_claim": (
            f"planned_n({CASE}) is None and n_met={rec['n_met']} is vacuous. This is not a "
            f"rate: it is a conjunction over deterministic cells, and one blocking "
            f"unsupported-language term falsifies the claim regardless of how many did not"),
    }, store)

    if len(tallies) != len(TIERS):
        return 2
    if not residue["clean"]:
        print(f"FAIL: {len(residue['surviving'])} probe guardrail(s) survived: "
              f"{residue['surviving']}. Residue is a teardown failure, not a finding",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
