"""The two halves of the census that used to be unreachable: what the walk cost, and what it dropped.

WHY THIS FILE EXISTS
--------------------
FUTURE-WORK items 42 and 43 both closed on code that lived inside a Playwright walk. Item 42 is the
census's arrival timeout: a flat 15 s that somebody once found sufficient, with a retry performed by a
human re-running the command and therefore recorded nowhere. Item 43 is worse — the census compared RAW
payload strings against RENDERED DOM text, so every `body_md` field, which the site renders through
`md.tsx`, matched nothing and was discarded at a `continue` labelled "exists in the payload, reaches no
reader". 125,957 characters of authored prose were invisible to a census whose published ceiling is 259
strings, and the number of strings it dropped was **0 by construction** because the drop was a `continue`
with no counter.

Both fixes were written inside `walk()` and `main()`, where their only caller was a live browser behind a
four-minute walk. That is the exact shape of defect this repo has already been bitten by — a writer
living inside `main()` whose mutant no test could reach — so `arrive()` and `classify_rows()` were lifted
out first and this file is what holds them.

WHY THE CLOCK IS INJECTED
-------------------------
`arrive()` publishes elapsed milliseconds, and a test that produced them by sleeping would be measuring
this machine's load rather than the function (`feedback_harness_test_measures_the_machine`: a sleeping
double read 46.0 ms for a 30 ms gap). Every timing arm below feeds a scripted clock, so the asserted
numbers are ones no real clock could coincidentally produce.

WHY THE FAKE PAGE LIES
----------------------
One double deliberately reports success **without navigating** (`feedback_unreachable_branch_in_fake`).
A retry that re-requested the first URL would be answered from cache and would publish a time the first
attempt could not have achieved, so "it retried" is not enough: the arms assert `goto` was called with
an attempt-distinct URL each time. A double that cannot lie cannot catch that.

MUTATION RESULTS
----------------
Run against `arrive`, `classify_rows`, `fingerprint` and the timeout's derivation, each mutant applied
to `census_rendered_surfaces.py` on disk with the no-mutant control re-run afterwards.

  2026-09-21, 25 mutants: **24 killed, 1 survivor** --
  `session-logs/a4-a5-census-mutants-20260921.log`. The survivor replaced the timeout's product with the
  literal `30_000`, which is what the product evaluates to, so every arm over the module's *values*
  passed. That survivor is the reason
  `test_the_timeout_is_written_as_a_product_and_not_as_its_own_answer` exists and reads the source text
  rather than the module; its docstring carries the derivation.
  2026-09-22, the same 25 mutants against the added arm --
  `session-logs/a4-a5-census-mutants-20260922.log`.
  2026-09-22, **28 mutants: 28 killed**, after `write_ledger` and its three arms --
  `session-logs/b2-census-mask-mutants-20260922.log`. The three new mutants are the ways a mask at a
  writer goes wrong: not applied at all (which is what the six ledgers of 2026-09-21 shipped), applied
  to one section of the document because the identifiers happened to be found in that section, and
  applied in a way that RECOMPUTES a published number from the masked text -- a redaction fix that
  moves the measurement it was protecting. The timeout survivor above is killed in this run too.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BUILD = REPO / "platform" / "build"
SUBJECT_MODULE_NAME = "census_rendered_surfaces"


def _load_subject():
    spec = importlib.util.spec_from_file_location(
        SUBJECT_MODULE_NAME, BUILD / f"{SUBJECT_MODULE_NAME}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[SUBJECT_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


census = _load_subject()


# --------------------------------------------------------------------------- doubles


class Timeout(Exception):
    """Stands in for `playwright.sync_api.TimeoutError`, which `arrive()` catches by breadth, not name."""


class FakePage:
    """A page that fails arrival for the first `fail_first` attempts.

    Records every call so an arm can assert what was NOT called: `wait_for_load_state` on a failed
    attempt is the difference between "this is how long arrival took" and "this is how long arrival plus
    a network settle on a page that never arrived took".
    """

    def __init__(self, *, fail_first: int = 0, navigates: bool = True):
        self.fail_first = fail_first
        self.navigates = navigates
        self.goto_urls: list[str] = []
        self.waits: list[tuple[int, int]] = []
        self.load_states: list[str] = []

    def goto(self, url, wait_until=None):
        if self.navigates:
            self.goto_urls.append(url)

    def wait_for_function(self, js, arg=None, timeout=None):
        self.waits.append((arg, timeout))
        if len(self.waits) <= self.fail_first:
            raise Timeout(f"waited {timeout} ms for {arg} chars")

    def wait_for_load_state(self, state):
        self.load_states.append(state)


def clock_of(*ticks: float):
    """A monotonic clock that returns the given seconds in order, then refuses.

    Refusing rather than repeating the last value: a clock that ran out would otherwise report a 0.0 ms
    attempt, which is a plausible-looking number and therefore the worst possible failure mode.
    """
    seq = list(ticks)
    calls = {"n": 0}

    def clock() -> float:
        if calls["n"] >= len(seq):
            raise AssertionError(f"the clock was read {calls['n'] + 1} times, only {len(seq)} scripted")
        calls["n"] += 1
        return seq[calls["n"] - 1]

    return clock


def url_for(k: int) -> str:
    return f"http://127.0.0.1:8901/index.html?route=4.{k}#/design"


# --------------------------------------------------------------------------- arrive()


def test_no_mutant_control_a_page_that_arrives_first_time_costs_one_attempt():
    """The control. Without it every arm below would also pass against a function that always raised."""
    page = FakePage()
    cost = census.arrive(page, url_for, clock=clock_of(100.0, 101.25))
    assert cost == {"elapsed_ms": 1250.0, "attempts": 1, "failed_attempt_ms": []}
    assert page.load_states == ["networkidle"], "a successful arrival must still settle the network"


def test_the_published_elapsed_time_comes_from_the_injected_clock_not_the_wall():
    """1250.0 ms is a number the machine cannot produce by accident in a test that does no work."""
    page = FakePage()
    cost = census.arrive(page, url_for, clock=clock_of(0.0, 1.25))
    assert cost["elapsed_ms"] == 1250.0


def test_a_retry_publishes_the_successful_attempt_and_keeps_the_failed_ones():
    """The successful attempt's own time, not the sum -- and the failures are beside it, not replaced.

    Item 42's closes-when is "a retry that is counted and published rather than performed by a human
    re-running the command". A single `elapsed_ms` of 22500.0 would be true of nothing that happened.
    """
    page = FakePage(fail_first=2)
    cost = census.arrive(page, url_for,
                         clock=clock_of(0.0, 10.0,      # attempt 1: failed after 10 s
                                        10.0, 22.5,     # attempt 2: failed after 12.5 s
                                        22.5, 23.1))    # attempt 3: arrived in 0.6 s
    assert cost["attempts"] == 3
    assert cost["elapsed_ms"] == 600.0
    assert cost["failed_attempt_ms"] == [10000.0, 12500.0]


def test_a_failed_attempt_does_not_wait_for_networkidle():
    """Otherwise the published failure time is arrival plus a settle on a page that never arrived."""
    page = FakePage(fail_first=1)
    census.arrive(page, url_for, clock=clock_of(0.0, 9.0, 9.0, 9.5))
    assert page.load_states == ["networkidle"], (
        f"one settle, on the attempt that arrived; got {page.load_states}")


def test_every_attempt_navigates_to_a_distinct_url():
    """A HashRouter behind a cache-busting query: a repeated URL is served from cache.

    The retry would then report a time the first attempt could not have achieved, which is the failure
    mode that makes a published timing worthless.
    """
    page = FakePage(fail_first=2)
    census.arrive(page, url_for, clock=clock_of(0.0, 1.0, 1.0, 2.0, 2.0, 3.0))
    assert len(page.goto_urls) == 3
    assert len(set(page.goto_urls)) == 3, f"cache-warmed retry: {page.goto_urls}"


def test_a_double_that_claims_success_without_navigating_is_caught():
    """The lying double (`feedback_unreachable_branch_in_fake`).

    `arrive()` returning a cost dict is not evidence that a navigation happened; a fake page that never
    records a `goto` returns exactly the same dict. This arm is the reason the arm above asserts against
    `goto_urls` rather than against the return value.
    """
    liar = FakePage(navigates=False)
    cost = census.arrive(liar, url_for, clock=clock_of(0.0, 0.5))
    assert cost["attempts"] == 1, "the liar's cost dict is indistinguishable from an honest one"
    assert liar.goto_urls == [], "this double is the one that lies -- if it navigated, it is not lying"


def test_exhausting_every_attempt_raises_with_all_of_them_named():
    page = FakePage(fail_first=99)
    with pytest.raises(census.ArrivalFailed) as e:
        census.arrive(page, url_for, attempts_allowed=3,
                      clock=clock_of(0.0, 4.0, 4.0, 8.0, 8.0, 12.0))
    assert e.value.waits_ms == [4000.0, 4000.0, 4000.0]
    assert isinstance(e.value.last, Timeout), "the last failure is carried, not swallowed"
    assert len(page.goto_urls) == 3


def test_one_attempt_allowed_means_one_navigation():
    """An off-by-one in the retry bound is a quiet doubling of the walk's worst case."""
    page = FakePage(fail_first=99)
    with pytest.raises(census.ArrivalFailed) as e:
        census.arrive(page, url_for, attempts_allowed=1, clock=clock_of(0.0, 45.0))
    assert len(page.goto_urls) == 1
    assert e.value.waits_ms == [45000.0]


def test_the_floor_and_the_timeout_reach_the_browser():
    """The two constants item 42 exists to replace are useless if they never leave Python."""
    page = FakePage()
    census.arrive(page, url_for, min_chars=400, timeout_ms=45_000, clock=clock_of(0.0, 0.1))
    assert page.waits == [(400, 45_000)]


def test_the_defaults_are_the_modules_published_constants():
    """The census document publishes `timeout_ms_per_attempt` and `max_attempts`; they must be these."""
    page = FakePage()
    census.arrive(page, url_for, clock=clock_of(0.0, 0.1))
    assert page.waits == [(census.MIN_RENDERED_CHARS_PER_ROUTE, census.ROUTE_ARRIVAL_TIMEOUT_MS)]


def test_the_timeout_is_a_stated_multiple_of_a_measured_maximum():
    """Item 42's whole complaint: the number was "somebody once found this sufficient".

    It is now `SLOWEST_OBSERVED_MS * ARRIVAL_TIMEOUT_MULTIPLE`, where the first figure is the maximum of
    136 recorded navigations and the second is a stated headroom.

    This arm checks the ARITHMETIC and cannot check the DERIVATION -- see the arm below, which is the
    one that survived a mutant this one passed.
    """
    assert census.ROUTE_ARRIVAL_TIMEOUT_MS == \
        census.SLOWEST_OBSERVED_MS * census.ARRIVAL_TIMEOUT_MULTIPLE


def test_the_timeout_is_written_as_a_product_and_not_as_its_own_answer():
    """The arm above is vacuous against the mutant that matters, and this is the record of why.

    Mutation run 2026-09-21 replaced `SLOWEST_OBSERVED_MS * ARRIVAL_TIMEOUT_MULTIPLE` with the literal
    `30_000` and the arm above **passed**: 1200 * 25 is 30_000, so at runtime the derivation and its own
    answer are the same object. No assertion over module attributes can tell them apart
    (`feedback_identical_output_wrong_assertion` -- a byte-identical surviving mutant means the
    assertion is measuring the wrong quantity). It was the only survivor of 25.

    What item 42 asks for is not the value 30_000; it is that the value be *written down as its
    derivation*, so that moving the headroom is impossible without seeing the measurement it multiplies.
    That is a property of the source text, so this arm reads the source.
    """
    tree = ast.parse((BUILD / f"{SUBJECT_MODULE_NAME}.py").read_text(encoding="utf-8"))
    assigned = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "ROUTE_ARRIVAL_TIMEOUT_MS"
                        for t in n.targets)]
    assert len(assigned) == 1, f"{len(assigned)} assignments to the timeout; expected exactly one"
    rhs = assigned[0]
    assert isinstance(rhs, ast.BinOp) and isinstance(rhs.op, ast.Mult), (
        f"the timeout is assigned a {type(rhs).__name__}, not a product. A literal here is the defect "
        f"item 42 names, even when it happens to equal the right number.")
    names = {side.id for side in (rhs.left, rhs.right) if isinstance(side, ast.Name)}
    assert names == {"SLOWEST_OBSERVED_MS", "ARRIVAL_TIMEOUT_MULTIPLE"}, (
        f"the product is over {sorted(names)}; both factors must be the named measurement and the "
        f"named headroom, so neither can move unseen")


def test_the_headroom_is_generous_because_the_timeout_bounds_a_hang_not_a_latency():
    """A timeout near the observed distribution turns a loaded machine into a refusal.

    That is not hypothetical -- it is item 42: the census went red and then green on an unchanged tree,
    and the lesson a flake teaches is "run it again", which is the same keystroke that discards a real
    regression. 10x is the floor this repo is willing to publish; the current value is 25x.
    """
    assert census.ARRIVAL_TIMEOUT_MULTIPLE >= 10


def test_before_attempt_runs_once_per_attempt_with_its_index():
    """The walk clears its pageerror list here: an error from a timed-out attempt must not fail the
    retry that succeeded."""
    page = FakePage(fail_first=2)
    seen: list[int] = []
    census.arrive(page, url_for, before_attempt=seen.append,
                  clock=clock_of(0.0, 1.0, 1.0, 2.0, 2.0, 3.0))
    assert seen == [0, 1, 2]


# --------------------------------------------------------------------------- fingerprint()


def test_fingerprint_keeps_link_text_and_drops_the_href():
    """`md.tsx:74` renders an anchor whose visible text is the bracketed half."""
    assert census.fingerprint("see [the register](/register) for more") == \
        census.fingerprint("see the register for more")


def test_fingerprint_drops_a_table_divider_row():
    """`md.tsx:110` treats `|---|---|` as structure and renders no text for it."""
    payload = "| case | verdict |\n|:---|:---|\n| F2-2 | FALSE |"
    assert census.fingerprint(payload) == census.fingerprint("case verdict F2-2 FALSE")


def test_fingerprint_drops_a_list_marker():
    """`md.tsx:204` renders `<li>`; the `-` is never text."""
    assert census.fingerprint("- one\n- two") == census.fingerprint("one two")


def test_fingerprint_is_whitespace_blind_because_stripping_syntax_leaves_gaps():
    """Removing a backtick from ``the `ceiling`.`` leaves `the ceiling .` against a DOM `the ceiling.`.

    Collapsing whitespace is not enough; it has to go. That is a real cost -- two adjacent words with no
    separator now fingerprint the same as one -- and it is why the ceiling is re-read once, by hand, with
    its cause recorded, rather than trusted silently.
    """
    assert census.fingerprint("the `ceiling`.") == census.fingerprint("the ceiling.")


def test_fingerprint_of_pure_syntax_is_empty_so_it_can_never_be_matched():
    """A payload string of nothing but markup must not be reported as rendering everywhere.

    `"" in anything` is True, so the caller guards on a non-empty fingerprint. Without the guard, a
    divider row in the payload would claim to render on all 16 routes in both locales -- and, being
    present in both, would then be counted as translated.
    """
    assert census.fingerprint("|---|---|") == ""
    assert census.fingerprint("***") == ""


def test_fingerprint_does_not_conflate_two_different_sentences():
    """The negative control: a lossy matcher that maps everything together matches everything."""
    assert census.fingerprint("the gate refused the payload") != \
        census.fingerprint("the gate accepted the payload")


# --------------------------------------------------------------------------- classify_rows()


EN = ("Guardrails are configured before the model is invoked. "
      "See the register for the cases that tested this. "
      "case verdict F2-2 FALSE "
      "Every number on this page is derived. ")
ZH = ("護欄在呼叫模型之前就設定好。 "
      "Every number on this page is derived. "
      "case verdict F2-2 FALSE ")


def walked_of(en: str = EN, zh: str = ZH, routes=("/design", "/register")) -> dict:
    return {(r, loc): {"text": txt} for r in routes for loc, txt in (("en", en), ("zh-TW", zh))}


ROUTES = ["/design", "/register"]


def test_no_mutant_control_a_verbatim_string_matches_and_nothing_is_dropped():
    rows, dropped = census.classify_rows(
        {"Guardrails are configured before the model is invoked.": ["practices.json/bp[0]/en"]},
        walked_of(), ROUTES, artifacts=set(), curated=set())
    assert dropped == []
    assert len(rows) == 1
    assert rows[0]["match_basis"] == "verbatim"
    assert rows[0]["renders_on"] == ROUTES
    assert rows[0]["classification"] == "AUTHORED"


def test_a_markdown_body_matches_only_after_stripping_and_says_so():
    """This is item 43. Before the second pass this string was dropped at a `continue`."""
    payload = "See [the register](/register) for the **cases** that tested this."
    rows, dropped = census.classify_rows(
        {payload: ["practices.json/bp[0]/body_md"]}, walked_of(), ROUTES,
        artifacts=set(), curated=set())
    assert dropped == [], f"a rendered sentence was reported as reaching no reader: {dropped}"
    assert rows[0]["match_basis"] == "markdown_stripped"
    assert rows[0]["renders_on"] == ROUTES


def test_the_zh_side_is_matched_on_the_same_basis_as_the_en_side():
    """The arm the untranslated ceiling depends on.

    `also_renders_in_zh` is what marks a string untranslated. If the English half matched only after
    stripping Markdown while the Chinese half were still compared verbatim, every `body_md` string on a
    translated page would come back as "does not render in zh" -- absent from the backlog, and the
    ceiling would fall for the wrong reason.
    """
    payload = "Every **number** on this page is derived."
    rows, _ = census.classify_rows({payload: ["p"]}, walked_of(), ROUTES,
                                   artifacts=set(), curated=set())
    assert rows[0]["match_basis"] == "markdown_stripped"
    assert rows[0]["also_renders_in_zh"] == ROUTES, (
        "this sentence is on the Chinese page untranslated; a stripped en match compared verbatim "
        "against zh would report []")


def test_a_string_that_reaches_no_reader_is_published_with_what_is_known_about_it():
    """The count item 43 says was 0 by construction. A drop is now a row, not a `continue`."""
    # The fence is at the start of its own line, because that is the only place `md.tsx` recognises one
    # and therefore the only place this flag should fire. An inline pair of triple backticks is not a
    # fence, and a flag that reported it as one would be telling the reader to chase the wrong thing.
    payload = "This sentence is in the payload and on no page. [link](/nowhere)\n```\nfence\n```"
    rows, dropped = census.classify_rows({payload: ["z.json/dead"]}, walked_of(), ROUTES,
                                         artifacts=set(), curated=set())
    assert rows == []
    assert len(dropped) == 1
    assert dropped[0]["payload_paths"] == ["z.json/dead"]
    assert dropped[0]["chars"] == len(payload)
    assert dropped[0]["contains_link"] is True
    assert dropped[0]["contains_code_fence"] is True


def test_the_drop_list_grows_with_the_number_of_unmatched_strings():
    """A counter that is always 1, or always the length of something else, is not a count."""
    payload = {f"Sentence number {i} appears in no rendered page at all.": ["z"] for i in range(5)}
    rows, dropped = census.classify_rows(payload, walked_of(), ROUTES,
                                         artifacts=set(), curated=set())
    assert rows == []
    assert len(dropped) == 5


def test_a_payload_string_of_pure_markup_is_dropped_rather_than_matching_every_route():
    """The empty-fingerprint guard, from the caller's side."""
    rows, dropped = census.classify_rows({"|:---|:---|:---|:---|": ["t"]}, walked_of(), ROUTES,
                                         artifacts=set(), curated=set())
    assert rows == [], f"an empty fingerprint claimed to render on {rows and rows[0]['renders_on']}"
    assert len(dropped) == 1


def test_a_string_with_no_word_separator_is_an_identifier_whichever_corpus_holds_it():
    """A digest is owed no translation regardless of who wrote it, so IDENTIFIER is tested first."""
    digest = "a" * 64
    rows, _ = census.classify_rows({digest: ["figures.json/sha256"]},
                                   walked_of(en=EN + digest, zh=ZH + digest), ROUTES,
                                   artifacts={digest}, curated={digest})
    assert rows[0]["classification"] == "IDENTIFIER"
    assert rows[0]["also_in_curation"] is True


def test_a_quoted_artifact_sentence_is_an_artifact_and_authored_prose_is_not():
    quote = "See the register for the cases that tested this."
    rows, _ = census.classify_rows({quote: ["audit.json/markdown"]}, walked_of(), ROUTES,
                                   artifacts={quote}, curated=set())
    assert rows[0]["classification"] == "ARTIFACT"

    rows, _ = census.classify_rows({quote: ["strings.ts/design"]}, walked_of(), ROUTES,
                                   artifacts=set(), curated=set())
    assert rows[0]["classification"] == "AUTHORED"


def test_a_row_carries_more_of_its_text_than_a_drop_does():
    """400 against 200: a drop is a lead to chase, a row is quoted in the backlog somebody edits."""
    long_en = "Q" * 500
    rows, _ = census.classify_rows({long_en: ["p"]}, walked_of(en=EN + long_en, zh=ZH), ROUTES,
                                   artifacts=set(), curated=set())
    assert len(rows[0]["text"]) == 400
    _, dropped = census.classify_rows({long_en: ["p"]}, walked_of(), ROUTES,
                                      artifacts=set(), curated=set())
    assert len(dropped[0]["text"]) == 200


# ------------------------------------------------ what the ledger PUBLISHES, read by the gate itself

def load_gate():
    """`check_redaction.py`, loaded by path: it is a root-level script, not an importable package."""
    spec = importlib.util.spec_from_file_location("_gate", REPO / "check_redaction.py")
    assert spec and spec.loader
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


def gate_findings(path: Path) -> list[tuple[str, str]]:
    """Every unwaived finding the redaction gate's OWN patterns read in `path`.

    Derived from `PATTERNS` and `allowed()` rather than from a list of shapes this test thought of, so
    a pattern added to the gate tomorrow is a pattern this ledger is checked against tomorrow
    (`feedback_derive_both_sides_of_a_gate`). It deliberately does not shell out to the gate: the gate
    scans the whole tree and would answer a different question, and a fixture written under `/tmp` is
    outside the tree it scans at all.
    """
    gate = load_gate()
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        for name, rx, _desc in gate.PATTERNS:
            if rx.search(line) and gate.allowed(REPO / "platform" / "census" / path.name,
                                                name, line) is None:
                out.append((name, line.strip()[:120]))
    return out


def ledger_with_a_sliced_arn_and_a_private_range() -> dict:
    """The document the six ledgers of 2026-09-21 were, reduced to the two strings that failed.

    Both identifier shapes are assembled at runtime, for the reason `lib/tests/test_redact.py` states
    at length: the redaction gate scans this file too, and a test about a leak that has to be waived
    by the gate has stopped being evidence. The ARN is sliced exactly the way a 200-character excerpt
    sliced it -- four characters into the placeholder of the second ARN on the line.
    """
    a = "a" + "rn"
    quoted = (f"User: {a}:aws:sts::<account>:assumed-role/grx-attacker/grx-harness is not authorized "
              f"to perform: UpdateGateway on resource: {a}:aws:bedrock-agentcore:us-east-1:<account>"
              f":gateway/grx-gw-1")
    cut = quoted[:quoted.rindex("<account>") + 4]
    cidr = "10." + "61.0.0/16"
    return {
        "counts": {"payload_strings_of_prose_length": 2},
        "dropped": [{"chars": 4000, "payload_paths": ["cases/F5-4a.json/record/x"], "text": cut}],
        "backlog": [{"chars": 300, "payload_paths": ["cases/F5-7b.json/record/instrument"],
                     "text": f"A VPC built for this case alone: {cidr}, a public subnet"}],
    }


def test_the_ledger_the_writer_produces_carries_no_unwaived_identifier(tmp_path):
    """Measured 2026-09-22: 36 findings, 6 in each of six ledgers, all in published excerpts.

    Five were the slice's own doing -- a 200-character cut through the `<account>` placeholder of the
    second ARN on a line, which the gate cannot tell from a truncated identifier and must therefore
    fail closed on -- and one was F5-7b's VPC CIDR quoted into a file with no waiver for it. Nothing
    upstream could have prevented either: the payload strings were already masked, and it was the
    slicing that was not. `write_ledger` masks at the writer, so this arm reads what the writer wrote.
    """
    out = tmp_path / "rendered-surfaces-20260101T000000Z.json"
    census.write_ledger(ledger_with_a_sliced_arn_and_a_private_range(), out)
    assert not gate_findings(out), (
        "the ledger this writer produces would fail the release gate, so it could not be pushed")


def test_the_same_fixture_unwritten_is_what_the_gate_reports(tmp_path):
    """The premise, so the arm above cannot pass by testing a fixture that was never a finding.

    A clean report over a document with nothing in it is the vacuous shape
    (`feedback_vacuous_test_check`): this writes the fixture WITHOUT the mask and requires the gate to
    read exactly the two shapes the six ledgers failed on.
    """
    out = tmp_path / "rendered-surfaces-20260101T000000Z.json"
    out.write_text(json.dumps(ledger_with_a_sliced_arn_and_a_private_range(), indent=2,
                              ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    names = {name for name, _line in gate_findings(out)}
    assert names == {"arn", "private-ip"}, (
        f"the unmasked fixture reads {sorted(names)}; it must reproduce the two shapes measured on "
        f"2026-09-21, or the arm above is asserting over a document that was never a finding")


def test_the_writer_cannot_move_a_count_or_a_path(tmp_path):
    """The mask runs last, after every count and every match, and must not touch either.

    A ledger whose numbers moved because of a redaction fix would be a fix that falsified the
    measurement it protects -- and the backlog ceiling in `check_site_invariants.py` is counted over
    the `payload_paths` in this document, so a mask that rewrote a path would make the ceiling a count
    over a ledger that no longer describes the payload.
    """
    doc = ledger_with_a_sliced_arn_and_a_private_range()
    out = tmp_path / "rendered-surfaces-20260101T000000Z.json"
    census.write_ledger(doc, out)
    got = json.loads(out.read_text(encoding="utf-8"))
    assert got["counts"] == doc["counts"]
    assert [r["chars"] for r in got["backlog"]] == [r["chars"] for r in doc["backlog"]]
    assert [r["payload_paths"] for r in got["backlog"]] == [r["payload_paths"] for r in doc["backlog"]]
    assert [r["payload_paths"] for r in got["dropped"]] == [r["payload_paths"] for r in doc["dropped"]]
    assert got["backlog"][0]["text"] != doc["backlog"][0]["text"], (
        "the excerpt is unchanged, so this arm is not looking at a masked document at all")
