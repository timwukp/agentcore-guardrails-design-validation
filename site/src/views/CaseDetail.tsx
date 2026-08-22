// View 2 — one case, whole chain, in the order the evidence was produced.
//
// THE SECTION THAT MAY NOT BE OMITTED
//
// "What this verdict does not prove" renders for every case, always, and when the artifact carries no
// such statement the section says so in those words instead of disappearing. A missing caveat that
// renders as absence is indistinguishable from a case with nothing to caveat, and the difference
// matters most exactly where the verdict is FALSE: a FALSE verdict is a measurement that the claim did
// not hold under the stated instrument, and it is the single most over-readable output in the study.
// Rendering the absence makes an unwritten caveat a visible deficiency instead of an invisible one —
// and it is visible: of the FALSE verdicts in this build, one carries the statement.
//
// Since then a third state sits between "the record says it" and "nothing says it": an AUTHORED bound,
// written by a later reader of the record for the 49 cases the record leaves silent. It renders in a
// dashed box carrying its own provenance, and it is counted under its own name — never merged into
// `cases_with_what_*_does_not_prove`, whose definition is "the record carries it". Two counts, two
// claims. The absent box still renders for any owed case that has neither.
//
// Two verdicts are owed no caveat of their own and must not be told they are missing one. INCONCLUSIVE
// establishes nothing in either direction, and RECORDED was pre-registered with no expected direction
// at all. Both get a box stating that, derived from the verdict by rule rather than from 22 hand-written
// sentences that could drift from it.
//
// The oracle text is quoted verbatim in a monospace block and never paraphrased, summarised or
// truncated, because it is sealed: it was fixed before the measurement ran, its hash is recomputed on
// every build, and a paraphrase on the way to the screen would be an unversioned amendment to the
// thing the verdict is an answer to.

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { loadCase, loadFamilies, loadSeries } from "../lib/data";
import type {
  ArchiveEntry,
  AuthoredCaveat as AuthoredCaveatType,
  CaseDetail as Case,
  Verdict,
} from "../lib/types";
import { T, useT, VerbatimNote } from "../lib/i18n";
import {
  Body,
  Chips,
  ErrorPanel,
  KV,
  Loading,
  RawJson,
  Restrictions,
  VerdictBadge,
  useAsync,
} from "../components/ui";

/** Renders a value of unknown shape without inventing structure for it: primitives inline, anything
 *  composite as its own JSON. The verdict files are deliberately heterogeneous — each case records
 *  what its instrument produced — so a component that assumed a shape would silently drop fields. */
function Any({ v }: { v: unknown }) {
  const t = useT();
  // `null`, `true` and `false` are the JSON spelling of the stored value, not words about it: a reader
  // comparing this table against the verdict file has to see what the file contains.
  if (v === null) return <span style={{ color: "var(--fg-faint)" }}>null</span>;
  if (v === undefined) return <span style={{ color: "var(--fg-faint)" }}>—</span>;
  // `lang="en"` on every branch: a stored value is as likely to be a whole English sentence
  // (`n_met_basis`, `false_means_what`, a `notes` entry) as an identifier, and the component cannot
  // tell them apart — nor should it try, because both are bytes out of the verdict file and neither is
  // this platform's own prose. Unmarked, the Chinese edition would hand a sealed English sentence to a
  // screen reader as Chinese.
  if (typeof v === "boolean")
    return (
      <span className="mono" lang="en">
        {v ? "true" : "false"}
      </span>
    );
  if (typeof v === "number" || typeof v === "string")
    return (
      <span className="mono" lang="en">
        {String(v)}
      </span>
    );
  if (Array.isArray(v) && v.every((x) => typeof x === "string" || typeof x === "number"))
    return (
      <span lang="en">
        <Chips items={v.map(String)} />
      </span>
    );
  return (
    <RawJson
      label={Array.isArray(v) ? t("cs.any.items", { n: v.length }) : t("cs.any.object")}
      value={v}
    />
  );
}

const PRIM = (v: unknown) => v === null || ["boolean", "number", "string"].includes(typeof v);

/** Split a record into the primitive fields (worth a table) and the composite ones (worth their own
 *  disclosure), preserving the artifact's own key order in both. */
function split(o: Record<string, unknown>, skip: string[] = []) {
  const prim: [string, unknown][] = [];
  const comp: [string, unknown][] = [];
  for (const [k, v] of Object.entries(o)) {
    if (skip.includes(k)) continue;
    (PRIM(v) ? prim : comp).push([k, v]);
  }
  return { prim, comp };
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

/** The stub `build_site_data.py` leaves where it lifted a heavy array out of the record. */
type Stub = { $series: string; n: number; bytes: number };

function asStub(v: unknown, path: string): Stub | null {
  const o = asRecord(v);
  return o && o["$series"] === path && typeof o["n"] === "number" && typeof o["bytes"] === "number"
    ? (o as Stub)
    : null;
}

/** Put a fetched series file back where it came from.
 *
 *  The split is the reason a 1.4 MB case renders immediately, but a viewer that can only ever see the
 *  stub is a viewer of the wrong object: the span-join panel below reads `times_s`, and for exactly the
 *  cases whose telemetry is large enough to matter that array is the part that was moved. So the page
 *  loads the series ON REQUEST and splices each array back at the dotted path the stub names.
 *
 *  A path that does not resolve to its own stub is REPORTED, not skipped. `check_site_invariants.py`
 *  asserts at publish time that `series_available`, the stubs and the series file agree; if they
 *  disagree here, the page and the payload disagree, and silently rendering the un-hydrated stub would
 *  make that look like a case whose series was simply small. */
function hydrate(
  rec: Record<string, unknown>,
  series: Record<string, unknown>,
): { record: Record<string, unknown>; unresolved: string[] } {
  const out = structuredClone(rec);
  const unresolved: string[] = [];
  for (const [path, arr] of Object.entries(series)) {
    const parts = path.split(".");
    const leaf = parts[parts.length - 1];
    let node: Record<string, unknown> | null = out;
    for (const p of parts.slice(0, -1)) node = node ? asRecord(node[p]) : null;
    if (!node || leaf === undefined || !asStub(node[leaf], path)) {
      unresolved.push(path);
      continue;
    }
    node[leaf] = arr;
  }
  return { record: out, unresolved };
}

/** Which caveat field is named for a verdict's own direction — and, for the two verdicts that have no
 *  direction, nothing.
 *
 *  This map replaces a ternary chain that fell through: `verdict === "FALSE" ? x : y` gave every
 *  non-FALSE verdict the TRUE field. For INCONCLUSIVE that was invisible, because the INCONCLUSIVE
 *  branch renders first. For the 2 RECORDED cases it was not: F5-4b carries 793 characters under
 *  `what_true_does_not_prove` and the page told the reader "this verdict record carries no such
 *  statement", naming a field the case does carry. A lookup that returns undefined for an unlisted
 *  verdict cannot fall through to a neighbour's field; a ternary chain always can. */
const CAVEAT_FIELD_FOR: Record<string, string> = {
  TRUE: "what_true_does_not_prove",
  FALSE: "what_false_does_not_prove",
};

function caveatText(rec: Record<string, unknown>, field: string | undefined): string | null {
  if (!field) return null;
  const v = rec[field];
  return typeof v === "string" && v.trim() ? v : null;
}

/** The caveat section. `absent` is a rendered state, not a skipped one — see the header comment. */
function DoesNotProve({ c }: { c: Case }) {
  const rec = c.record;
  const t = useT();
  const ownField = c.verdict ? CAVEAT_FIELD_FOR[c.verdict] : undefined;
  const mine = caveatText(rec, ownField);
  const authored = c.authored_caveat;

  // Every caveat field the record carries that is NOT this verdict's own. For a TRUE or FALSE case
  // that is the opposite direction's sentence, which the record genuinely carries as a pair. For an
  // INCONCLUSIVE or RECORDED case there is no "opposite": the sentence bounds a reading the
  // measurement never reached, and 9 cases carry one. Both were previously reachable only through the
  // collapsed raw-record dump at the bottom of the page.
  const others = Object.entries(CAVEAT_FIELD_FOR)
    .filter(([, field]) => field !== ownField && caveatText(rec, field))
    .map(([direction, field]) => ({ direction, text: caveatText(rec, field) as string }));

  return (
    <section>
      <h3>{t("cs.h.doesNotProve")}</h3>
      {c.verdict === "INCONCLUSIVE" ? (
        <div className="note warn">
          <strong>
            <T k="cs.dnp.inconclusive.head" v={{ v: <span lang="en">INCONCLUSIVE</span> }} />
          </strong>{" "}
          <T
            k="cs.dnp.inconclusive.body"
            v={{ t: <span lang="en">TRUE</span>, f: <span lang="en">FALSE</span> }}
          />
        </div>
      ) : c.verdict === "RECORDED" ? (
        <div className="note warn">
          <strong>
            <T k="cs.dnp.recorded.head" v={{ v: <span lang="en">RECORDED</span> }} />
          </strong>{" "}
          {t("cs.dnp.recorded.body")}
        </div>
      ) : mine ? (
        // The caveat is the record's own sentence about its own verdict. Translating it here would
        // produce a bound on the reading whose only source is this website.
        <div className="note" lang="en">
          {mine}
        </div>
      ) : authored ? (
        <AuthoredCaveat a={authored} />
      ) : ownField ? (
        <div className="note warn">
          <strong>{t("cs.dnp.absent.head")}</strong>{" "}
          <T
            k="cs.dnp.absent.body"
            v={{
              field: <code lang="en">{ownField}</code>,
              verdict: (
                <span className="mono" lang="en">
                  {c.verdict ?? t("cs.dnp.verdictWord")}
                </span>
              ),
            }}
          />
        </div>
      ) : null}
      {others.map((o) => (
        <details className="raw" key={o.direction}>
          <summary>
            {ownField ? (
              t("cs.dnp.opposite")
            ) : (
              <T k="cs.dnp.otherDirection" v={{ v: <span lang="en">{o.direction}</span> }} />
            )}
          </summary>
          <div>
            <p style={{ color: "var(--fg-dim)" }} lang="en">
              {o.text}
            </p>
          </div>
        </details>
      ))}
    </section>
  );
}

/** An authored bound, rendered so a reader cannot mistake it for the record's own sentence.
 *
 *  The `note authored` class carries the visual distinction and the provenance line carries the verbal
 *  one, because either alone fails a different reader: a colour is invisible to someone reading the
 *  page as text, and a provenance line four lines down is invisible to someone skimming the box. The
 *  `why` completes the section heading — "What this verdict does not prove: that ..." — which is why it
 *  starts lower-case and mid-clause. */
function AuthoredCaveat({ a }: { a: AuthoredCaveatType }) {
  const t = useT();
  const status =
    a.review_status === "unreviewed_by_a_human" ? t("cs.dnp.authored.unreviewed") : a.review_status;
  return (
    <div className="note authored">
      <strong>{t("cs.dnp.authored.head")}</strong>
      <p lang="en">{a.why}</p>
      <p style={{ color: "var(--fg-dim)", fontSize: "0.85em" }}>
        <T
          k="cs.dnp.authored.provenance"
          v={{
            by: <span lang="en">{a.authored_by}</span>,
            on: <span className="mono">{a.authored_on}</span>,
            from: <span lang="en">{a.authored_from}</span>,
            status: <strong>{status}</strong>,
          }}
        />{" "}
        <code lang="en">{a.derived_from.join(", ")}</code>
      </p>
    </div>
  );
}

/** Replication panel. An archived file's verdict is shown beside the live one rather than assumed to
 *  agree — the day-2 replication of 2026-08-19 produced three archived files whose verdict differs
 *  from the live file, and a panel that only listed dates would have hidden exactly that. */
function Replication({ c }: { c: Case }) {
  const live = c.verdict;
  const disagree = c.archive.filter((a) => a.verdict && live && a.verdict !== live);
  const days = new Set(
    c.archive.map((a) => /(\d{4}-\d{2}-\d{2})/.exec(a.label)?.[1] ?? "").filter(Boolean),
  );
  const t = useT();
  return (
    <section>
      <h3>{t("cs.h.replication")}</h3>
      {!c.archive.length ? (
        <div className="note">{t("cs.rep.none")}</div>
      ) : (
        <>
          {disagree.length ? (
            <div className="note warn">
              <strong>
                {t(
                  disagree.length === 1 ? "cs.rep.disagree.head1" : "cs.rep.disagree.head",
                  { n: disagree.length },
                )}
              </strong>{" "}
              {t("cs.rep.disagree.body")}
            </div>
          ) : null}
          <table className="grid">
            <thead>
              <tr>
                <th>{t("cs.rep.th.label")}</th>
                <th>{t("cs.rep.th.verdict")}</th>
                <th>{t("cs.rep.th.runId")}</th>
                <th>{t("cs.rep.th.sha")}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <span className="badge">{t("cs.rep.live")}</span> {c.verdict_file ?? "—"}
                </td>
                <td>
                  <VerdictBadge v={live} />
                </td>
                <td className="mono" style={{ fontSize: 11.5 }}>
                  {String(c.record["run_id"] ?? "—")}
                </td>
                <td>—</td>
              </tr>
              {[...c.archive]
                .sort((a, b) => a.label.localeCompare(b.label))
                .map((a: ArchiveEntry) => (
                  <tr key={a.file}>
                    <td className="mono">{a.label}</td>
                    <td>
                      <VerdictBadge v={(a.verdict as Verdict) || null} />
                    </td>
                    <td className="mono" style={{ fontSize: 11.5 }}>
                      {a.run_id}
                    </td>
                    <td className="mono" style={{ fontSize: 11 }}>
                      {a.sha256.slice(0, 16)}…
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 8 }}>
            {t("cs.rep.days", { days: days.size ? [...days].join(", ") : t("cs.none") })}
          </p>
        </>
      )}
    </section>
  );
}

/** View 3, inline where the data lives: the per-arm span join, with the found/timed/wanted counts as
 *  first-class numbers. A series with 60% of its spans recovered is a different object from one with
 *  100%, and reading a percentile off the first without seeing that is the error this panel prevents. */
function SpanJoin({ join }: { join: Record<string, unknown> }) {
  const arms = Object.entries(join)
    .map(([arm, v]) => [arm, asRecord(v)] as const)
    .filter((e): e is readonly [string, Record<string, unknown>] => e[1] !== null);

  // An arm whose `times_s` was split out carries a STUB here, not timestamps — and a stub is an
  // object with numeric fields (`n`, `bytes`), so a loop that plots every number it finds would draw
  // two ticks out of the split's own bookkeeping and label them requests. The stub is therefore
  // detected and the arm reported as unloaded, which is also the honest reading: the timestamps exist,
  // this page has not fetched them.
  const { points, stubbed } = useMemo(() => {
    const all: { arm: string; id: string; t: number }[] = [];
    const notLoaded: string[] = [];
    for (const [arm, a] of arms) {
      const times = asRecord(a["times_s"]);
      if (!times) continue;
      if (typeof times["$series"] === "string") {
        notLoaded.push(arm);
        continue;
      }
      for (const [id, t] of Object.entries(times)) if (typeof t === "number") all.push({ arm, id, t });
    }
    all.sort((x, y) => x.t - y.t);
    return { points: all, stubbed: notLoaded };
  }, [join]); // eslint-disable-line react-hooks/exhaustive-deps

  const [i, setI] = useState(0);
  const t = useT();
  if (!arms.length) return null;

  const t0 = points.length ? (points[0]?.t ?? 0) : 0;
  const t1 = points.length ? (points[points.length - 1]?.t ?? 0) : 0;
  const span = t1 - t0 || 1;
  const cur = points[Math.min(i, points.length - 1)];
  const H = 22 * arms.length + 26;

  return (
    <section>
      <h3>{t("cs.h.spanJoin")}</h3>
      <table className="grid" style={{ marginBottom: 12 }}>
        <thead>
          <tr>
            {/* The arm names are the record's own keys and appear untranslated in the rows below; the
                column headings are this page's description of the record's fields. */}
            <th>{t("cs.sj.th.arm")}</th>
            <th>{t("cs.sj.th.wanted")}</th>
            <th>{t("cs.sj.th.found")}</th>
            <th>{t("cs.sj.th.timed")}</th>
            <th>{t("cs.sj.th.queries")}</th>
            <th>{t("cs.sj.th.missing")}</th>
            <th>{t("cs.sj.th.truncated")}</th>
          </tr>
        </thead>
        <tbody>
          {arms.map(([arm, a]) => {
            const miss = Array.isArray(a["missing"]) ? (a["missing"] as unknown[]).length : 0;
            const trunc = a["truncated"] === true;
            return (
              <tr key={arm}>
                <td className="mono" lang="en">
                  {arm}
                </td>
                <td className="num">{String(a["n_wanted"] ?? "—")}</td>
                <td className="num">{String(a["n_found"] ?? "—")}</td>
                <td className="num">{String(a["n_timed"] ?? "—")}</td>
                <td className="num">{String(a["n_queries"] ?? "—")}</td>
                <td className="num">{miss}</td>
                <td className={trunc ? "num" : "num"} style={trunc ? { color: "var(--warn)" } : undefined}>
                  {trunc ? t("cs.sj.truncated") : t("cs.sj.notTruncated")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {points.length ? (
        <>
          <svg className="series-svg" viewBox={`0 0 1000 ${H}`} preserveAspectRatio="none">
            {arms.map(([arm], n) => (
              <g key={arm}>
                <text x={4} y={22 * n + 14} fill="#6c7a8b" fontSize={9} fontFamily="monospace">
                  {arm}
                </text>
                <line
                  x1={0}
                  x2={1000}
                  y1={22 * n + 18}
                  y2={22 * n + 18}
                  stroke="#263140"
                  strokeWidth={1}
                />
              </g>
            ))}
            {points.map((p, n) => {
              const row = arms.findIndex(([a]) => a === p.arm);
              const x = ((p.t - t0) / span) * 998 + 1;
              return (
                <line
                  key={n}
                  x1={x}
                  x2={x}
                  y1={22 * row + 8}
                  y2={22 * row + 18}
                  stroke={row === 0 ? "#2fa19b" : "#8a7bd0"}
                  strokeWidth={0.6}
                  opacity={0.75}
                />
              );
            })}
            {cur ? (
              <line
                x1={((cur.t - t0) / span) * 998 + 1}
                x2={((cur.t - t0) / span) * 998 + 1}
                y1={0}
                y2={H}
                stroke="#5aa9e6"
                strokeWidth={1}
              />
            ) : null}
          </svg>
          <div className="scrub">
            <input
              type="range"
              min={0}
              max={points.length - 1}
              value={Math.min(i, points.length - 1)}
              onChange={(e) => setI(Number(e.target.value))}
            />
            <span className="mono" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
              {i + 1}/{points.length}
            </span>
          </div>
          {cur ? (
            <KV
              rows={[
                [
                  t("cs.sj.th.arm"),
                  <span className="mono" lang="en">
                    {cur.arm}
                  </span>,
                ],
                [t("cs.sj.kv.requestId"), <span className="mono">{cur.id}</span>],
                [
                  t("cs.sj.kv.spanTime"),
                  <span className="mono">
                    {t("cs.sj.kv.spanTime.value", {
                      t: cur.t.toFixed(3),
                      into: (cur.t - t0).toFixed(3),
                    })}
                  </span>,
                ],
              ]}
            />
          ) : null}
          <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 8 }}>{t("cs.sj.note")}</p>
        </>
      ) : stubbed.length ? null : (
        <div className="note">{t("cs.sj.nothingToPlot")}</div>
      )}
      {stubbed.length ? (
        <div className="note">
          <strong>
            {t(stubbed.length === 1 ? "cs.sj.stubbed.head1" : "cs.sj.stubbed.head", {
              n: stubbed.length,
            })}
          </strong>{" "}
          <T
            k="cs.sj.stubbed.body"
            v={{
              arms: (
                <span className="mono" lang="en">
                  {stubbed.join(", ")}
                </span>
              ),
              section: <em>{t("cs.h.heavySeries")}</em>,
            }}
          />
        </div>
      ) : null}
    </section>
  );
}

export default function CaseDetail() {
  const { id = "" } = useParams();
  const res = useAsync(() => loadCase(id), [id]);
  const fam = useAsync(loadFamilies, []);
  const t = useT();

  // The series file is fetched on request, never with the page: it is the larger half of the payload
  // and most readers of most cases never open it. State lives here, above the early returns, because
  // hooks may not be called conditionally.
  //
  // It is KEYED BY CASE ID rather than cleared when the route changes. One `CaseDetail` instance
  // serves every case route, so navigating F3-10 → F9-2 does not unmount it and a plain
  // `useState` holding F3-10's arrays survives into F9-2's render. That is exactly what the browser
  // walk-through showed: F9-2's single series row read `MISSING` and its load button was gone,
  // because another case's fetch still counted as "loaded" here. Clearing it in a `useEffect` would
  // repair the second frame and still render the first one wrong; deriving from a stored case id is
  // correct on the first render, so there is no window in which one case shows another's data.
  const [fetched, setFetched] = useState<{
    case: string;
    state: "loading" | "error" | "ok";
    series?: Record<string, unknown>;
    error?: unknown;
  } | null>(null);
  const mine = fetched && fetched.case === id ? fetched : null;
  const series = mine?.state === "ok" ? (mine.series ?? null) : null;
  const loadingSeries = mine?.state === "loading";
  const loaded = res.state === "ok" ? res.data : null;
  const hydrated = useMemo(
    () => (loaded && series ? hydrate(loaded.record, series) : null),
    [loaded, series],
  );

  if (res.state === "loading") return <Loading what={t("cs.loading", { id })} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const c = res.data;
  const rec = hydrated ? hydrated.record : c.record;
  const adj = asRecord(rec["record"]);
  const guards = asRecord(rec["guards"]);
  const guardDetail = asRecord(rec["guard_detail"]);
  const blockers = asRecord(rec["blockers"]);
  const spanJoin = asRecord(rec["span_join"]);
  const famFlags = fam.state === "ok" ? fam.data.families[c.family] : undefined;

  const IDS = ["run_id", "region", "cell", "gateway_id", "policy_engine_id", "action_id", "expiry"];
  const NARRATIVE = [
    "verdict_reading",
    "verdict_rule",
    "why_this_matters_operationally",
    "public_convention",
    "why_the_mutation_is_mandatory",
  ];

  const shown = new Set([
    "record",
    "guards",
    "guard_detail",
    "blockers",
    "span_join",
    "oracle_text",
    "instrument",
    "verdict",
    "case_id",
    "family",
    "what_true_does_not_prove",
    "what_false_does_not_prove",
    ...IDS,
    ...NARRATIVE,
  ]);
  const rest = split(rec, [...shown]);

  return (
    <>
      <h2 className="view">
        <span className="mono">{c.case}</span> <VerdictBadge v={c.verdict} />
      </h2>
      {/* The case title is the artifact's own one-line statement of what was measured. */}
      <p className="lede" lang="en">
        {c.title}
      </p>
      <VerbatimNote />
      <div style={{ marginBottom: 18 }}>
        <span className="chip">
          {t("cs.chip.family")} <span lang="en">{c.family}</span>
        </span>
        <span className="chip">
          {t("cs.chip.tier")} <span lang="en">{c.tier}</span>
        </span>
        {adj?.["kind"] ? (
          <span className="chip">
            {t("cs.chip.kind")} <span lang="en">{String(adj["kind"])}</span>
          </span>
        ) : null}
        {c.oracle_is_sealed ? <span className="chip sealed">{t("cs.chip.sealed")}</span> : null}
        {c.claims.map((cl) => (
          <Link key={cl} to={`/claims#${cl}`} className="chip">
            {cl}
          </Link>
        ))}
      </div>

      {famFlags?.network_position_sensitive ? (
        <div className="note warn">
          <strong>{t("cs.netPos")}</strong> <span lang="en">{famFlags.why}</span>
          {famFlags.replication_requirement ? (
            <> <span lang="en">{famFlags.replication_requirement}</span></>
          ) : null}
        </div>
      ) : null}

      <Restrictions items={c.citation_restrictions} />

      <section>
        <h3>{t("cs.h.oracle")}</h3>
        {/* The one block on this platform that is quoted with the most force: it is sealed, hashed, and
            answered by the verdict. `lang="en"` states in the markup what the note below states in
            words — this text is not in the reader's language because it may not be restated. */}
        <div className="verbatim" lang="en">
          {c.oracle_text}
        </div>
        <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 8 }}>{t("cs.oracle.note")}</p>
      </section>

      {c.instrument ? (
        <section>
          <h3>{t("cs.h.instrument")}</h3>
          <div className="md">
            <p lang="en">{c.instrument}</p>
          </div>
        </section>
      ) : null}

      {adj ? (
        <section>
          <h3>{t("cs.h.adjudication")}</h3>
          <table className="grid">
            <tbody>
              {split(adj).prim.map(([k, v]) => (
                <tr key={k}>
                  {/* The row headings here are the record's own field names, not descriptions of them:
                      a reader checking this table against the verdict file greps for these strings. */}
                  <th style={{ width: 200 }} lang="en">
                    {k}
                  </th>
                  <td>
                    <Any v={v} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {split(adj).comp.map(([k, v]) => (
            <div key={k} style={{ marginTop: 10 }}>
              <div
                style={{ color: "var(--fg-dim)", fontSize: 12, marginBottom: 4 }}
                className="mono"
                lang="en"
              >
                {k}
              </div>
              <EvidenceBlock v={v} />
            </div>
          ))}
        </section>
      ) : null}

      <DoesNotProve c={c} />

      {NARRATIVE.some((k) => typeof rec[k] === "string") ? (
        <section>
          <h3>{t("cs.h.howRead")}</h3>
          {NARRATIVE.filter((k) => typeof rec[k] === "string").map((k) => (
            <div key={k} style={{ marginBottom: 10 }}>
              <div className="mono" style={{ color: "var(--fg-faint)", fontSize: 11.5 }} lang="en">
                {k}
              </div>
              {/* `verdict_reading` and `verdict_rule` are how the producer read its own measurement.
                  They are the reasoning this page reports, so they are quoted, not rendered again. */}
              <div lang="en">
                <Body src={String(rec[k])} />
              </div>
            </div>
          ))}
        </section>
      ) : null}

      {guards ? (
        <section>
          <h3>{t("cs.h.guards")}</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>{t("cs.g.th.guard")}</th>
                <th>{t("cs.g.th.held")}</th>
                <th>{t("cs.g.th.testWhy")}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(guards).map(([name, ok]) => {
                const d = asRecord(guardDetail?.[name]);
                return (
                  <tr key={name}>
                    <td className="mono" lang="en">
                      {name}
                    </td>
                    <td>
                      {/* `held` is this page's word for `true`; anything else is the stored value,
                          shown as stored rather than interpreted. */}
                      <span className={`badge ${ok === true ? "v-TRUE" : "v-FALSE"}`}>
                        {ok === true ? t("cs.g.held") : String(ok)}
                      </span>
                    </td>
                    <td>
                      {d?.["test"] ? <div lang="en">{String(d["test"])}</div> : null}
                      {d?.["why"] ? (
                        <div style={{ color: "var(--fg-dim)", marginTop: 4 }} lang="en">
                          {String(d["why"])}
                        </div>
                      ) : null}
                      {!d?.["test"] && !d?.["why"] ? (
                        <span style={{ color: "var(--fg-faint)" }}>{t("cs.g.noTestWhy")}</span>
                      ) : null}
                      {d ? <RawJson label={t("cs.g.detail")} value={d} /> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      ) : null}

      {blockers ? (
        <section>
          <h3>{t("cs.h.blockers")}</h3>
          {Array.isArray(blockers["blockers"]) && (blockers["blockers"] as unknown[]).length ? (
            <RawJson
              label={t("cs.bl.count", { n: (blockers["blockers"] as unknown[]).length })}
              value={blockers["blockers"]}
            />
          ) : (
            <div className="note">{t("cs.bl.none")}</div>
          )}
          {typeof blockers["blockers_are_not_exhaustive"] === "string" ? (
            <p style={{ color: "var(--fg-dim)", fontSize: 12.5 }} lang="en">
              {String(blockers["blockers_are_not_exhaustive"])}
            </p>
          ) : null}
        </section>
      ) : null}

      {spanJoin ? <SpanJoin join={spanJoin} /> : null}

      <Replication c={c} />

      <section>
        <h3>{t("cs.h.resources")}</h3>
        <KV
          rows={IDS.filter((k) => rec[k] !== undefined).map((k) => [k, <Any v={rec[k]} />] as [string, ReactNode])}
        />
        <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 8 }}>{t("cs.resources.note")}</p>
      </section>

      {rest.prim.length || rest.comp.length ? (
        <section>
          <h3>{t("cs.h.everythingElse")}</h3>
          {rest.prim.length ? (
            <table className="grid" style={{ marginBottom: 12 }}>
              <tbody>
                {rest.prim.map(([k, v]) => (
                  <tr key={k}>
                    <th style={{ width: 260 }} lang="en">
                      {k}
                    </th>
                    <td>
                      <Any v={v} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {rest.comp.map(([k, v]) => (
            <div key={k} style={{ marginBottom: 8 }}>
              <RawJson label={k} value={v} />
            </div>
          ))}
        </section>
      ) : null}

      {c.series_available.length ? (
        <section>
          <h3>{t("cs.h.heavySeries")}</h3>
          <div className="note">
            <T k="cs.hs.body" v={{ file: <code>data/series/{c.case}.json</code> }} />
          </div>
          <table className="grid" style={{ marginTop: 10, marginBottom: 10 }}>
            <thead>
              <tr>
                <th>{t("cs.hs.th.path")}</th>
                <th>{t("cs.hs.th.elements")}</th>
                <th>{t("cs.hs.th.size")}</th>
                <th>{t("cs.hs.th.loaded")}</th>
              </tr>
            </thead>
            <tbody>
              {c.series_available.map((path) => {
                const parts = path.split(".");
                let node: Record<string, unknown> | null = c.record;
                for (const p of parts.slice(0, -1)) node = node ? asRecord(node[p]) : null;
                const leaf = parts[parts.length - 1];
                const stub = node && leaf !== undefined ? asStub(node[leaf], path) : null;
                const here = series ? series[path] : undefined;
                return (
                  <tr key={path}>
                    <td className="mono" lang="en">
                      {path}
                    </td>
                    <td className="num">{stub ? stub.n : "—"}</td>
                    <td className="num">{stub ? `${Math.round(stub.bytes / 1024)} KB` : "—"}</td>
                    <td className="num">
                      {Array.isArray(here)
                        ? t("cs.hs.loaded.yes", { n: here.length })
                        : series
                          ? t("cs.hs.loaded.missing")
                          : t("cs.hs.loaded.no")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {series ? null : (
            <button
              type="button"
              onClick={() => {
                setFetched({ case: c.case, state: "loading" });
                loadSeries(c.case).then(
                  (d) => setFetched({ case: c.case, state: "ok", series: d.series }),
                  (e) => setFetched({ case: c.case, state: "error", error: e }),
                );
              }}
              disabled={loadingSeries}
            >
              {loadingSeries ? t("cs.hs.loading") : t("cs.hs.load")}
            </button>
          )}
          {mine?.state === "error" ? <ErrorPanel error={mine.error} /> : null}
          {hydrated?.unresolved.length ? (
            <div className="note warn">
              <strong>{t("cs.hs.disagree.head")}</strong>{" "}
              <T
                k="cs.hs.disagree.body"
                v={{
                  paths: (
                    <span className="mono" lang="en">
                      {hydrated.unresolved.join(", ")}
                    </span>
                  ),
                  gate: <code>check_site_invariants.py</code>,
                  field: <code>series_available</code>,
                }}
              />
            </div>
          ) : null}
          {series ? (
            <div className="note">{t("cs.hs.done")}</div>
          ) : null}
        </section>
      ) : null}

      <section>
        <h3>{t("cs.h.verdictFile")}</h3>
        <RawJson label={c.verdict_file ?? t("cs.recordLabel")} value={rec} />
      </section>

      <p style={{ marginTop: 24 }}>
        <Link to="/">{t("cs.back")}</Link>
      </p>
    </>
  );
}

function EvidenceBlock({ v }: { v: unknown }) {
  const o = asRecord(v);
  if (!o) return <Any v={v} />;
  const { prim, comp } = split(o);
  return (
    <>
      {prim.length ? (
        <table className="grid">
          <tbody>
            {prim.map(([k, x]) => (
              <tr key={k}>
                <th style={{ width: 220 }} lang="en">
                  {k}
                </th>
                <td>
                  <Any v={x} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {comp.map(([k, x]) => (
        <div key={k} style={{ marginTop: 6 }}>
          <RawJson label={k} value={x} />
        </div>
      ))}
    </>
  );
}
