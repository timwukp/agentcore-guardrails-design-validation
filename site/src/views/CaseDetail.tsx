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
// The oracle text is quoted verbatim in a monospace block and never paraphrased, summarised or
// truncated, because it is sealed: it was fixed before the measurement ran, its hash is recomputed on
// every build, and a paraphrase on the way to the screen would be an unversioned amendment to the
// thing the verdict is an answer to.

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { loadCase, loadFamilies, loadSeries } from "../lib/data";
import type { ArchiveEntry, CaseDetail as Case, Verdict } from "../lib/types";
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
  if (v === null) return <span style={{ color: "var(--fg-faint)" }}>null</span>;
  if (v === undefined) return <span style={{ color: "var(--fg-faint)" }}>—</span>;
  if (typeof v === "boolean") return <span className="mono">{v ? "true" : "false"}</span>;
  if (typeof v === "number" || typeof v === "string") return <span className="mono">{String(v)}</span>;
  if (Array.isArray(v) && v.every((x) => typeof x === "string" || typeof x === "number"))
    return <Chips items={v.map(String)} />;
  return <RawJson label={Array.isArray(v) ? `${v.length} item(s)` : "object"} value={v} />;
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

/** The caveat section. `absent` is a rendered state, not a skipped one — see the header comment. */
function DoesNotProve({ c }: { c: Case }) {
  const rec = c.record;
  const forFalse = rec["what_false_does_not_prove"];
  const forTrue = rec["what_true_does_not_prove"];
  const mine = c.verdict === "FALSE" ? forFalse : c.verdict === "TRUE" ? forTrue : null;
  const key = c.verdict === "FALSE" ? "what_false_does_not_prove" : "what_true_does_not_prove";
  const other = c.verdict === "FALSE" ? forTrue : forFalse;

  return (
    <section>
      <h3>What this verdict does not prove</h3>
      {c.verdict === "INCONCLUSIVE" ? (
        <div className="note warn">
          <strong>INCONCLUSIVE establishes nothing in either direction.</strong> It is not a weak
          TRUE and not a soft FALSE: the measurement ran and did not decide the claim. It licenses no
          amendment to the design document and may not be cited as evidence for or against the claim.
        </div>
      ) : typeof mine === "string" && mine.trim() ? (
        <div className="note">{mine}</div>
      ) : (
        <div className="note warn">
          <strong>This verdict record carries no such statement.</strong> The artifact has no{" "}
          <code>{key}</code> field, so nothing bounds how far this{" "}
          <span className="mono">{c.verdict ?? "verdict"}</span> may be read. That is a gap in the
          record, not an assertion that the verdict generalises — this section is rendered for every
          case precisely so an unwritten caveat cannot look like an absent need for one.
        </div>
      )}
      {typeof other === "string" && other.trim() ? (
        <details className="raw">
          <summary>the record also carries the caveat for the opposite outcome</summary>
          <div>
            <p style={{ color: "var(--fg-dim)" }}>{other}</p>
          </div>
        </details>
      ) : null}
    </section>
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
  return (
    <section>
      <h3>Replication</h3>
      {!c.archive.length ? (
        <div className="note">
          No archived copy of this verdict exists, so this case has been measured on one occasion only.
          It is not replicated. The dashboard will not call a single measurement a replication however
          many times the case is rendered.
        </div>
      ) : (
        <>
          {disagree.length ? (
            <div className="note warn">
              <strong>
                {disagree.length} archived {disagree.length === 1 ? "copy" : "copies"} of this verdict
                disagree with the live file.
              </strong>{" "}
              A disagreement between two measurement occasions is a finding about the stability of the
              claim, not an error to be resolved by preferring the newer run. Both verdicts are shown.
            </div>
          ) : null}
          <table className="grid">
            <thead>
              <tr>
                <th>label</th>
                <th>verdict in that file</th>
                <th>run id</th>
                <th>sha256</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <span className="badge">live</span> {c.verdict_file ?? "—"}
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
            Distinct calendar days named by the archive labels: {days.size ? [...days].join(", ") : "none"}.
            A replication requires two distinct UTC days; one day repeated is a re-run.
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
  if (!arms.length) return null;

  const t0 = points.length ? (points[0]?.t ?? 0) : 0;
  const t1 = points.length ? (points[points.length - 1]?.t ?? 0) : 0;
  const span = t1 - t0 || 1;
  const cur = points[Math.min(i, points.length - 1)];
  const H = 22 * arms.length + 26;

  return (
    <section>
      <h3>Span join — one tick per recovered request</h3>
      <table className="grid" style={{ marginBottom: 12 }}>
        <thead>
          <tr>
            <th>arm</th>
            <th>wanted</th>
            <th>found</th>
            <th>timed</th>
            <th>queries</th>
            <th>missing</th>
            <th>truncated</th>
          </tr>
        </thead>
        <tbody>
          {arms.map(([arm, a]) => {
            const miss = Array.isArray(a["missing"]) ? (a["missing"] as unknown[]).length : 0;
            const trunc = a["truncated"] === true;
            return (
              <tr key={arm}>
                <td className="mono">{arm}</td>
                <td className="num">{String(a["n_wanted"] ?? "—")}</td>
                <td className="num">{String(a["n_found"] ?? "—")}</td>
                <td className="num">{String(a["n_timed"] ?? "—")}</td>
                <td className="num">{String(a["n_queries"] ?? "—")}</td>
                <td className="num">{miss}</td>
                <td className={trunc ? "num" : "num"} style={trunc ? { color: "var(--warn)" } : undefined}>
                  {trunc ? "TRUNCATED" : "no"}
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
                ["arm", <span className="mono">{cur.arm}</span>],
                ["request id", <span className="mono">{cur.id}</span>],
                [
                  "span time",
                  <span className="mono">
                    {cur.t.toFixed(3)} ({(cur.t - t0).toFixed(3)} s into the window)
                  </span>,
                ],
              ]}
            />
          ) : null}
          <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 8 }}>
            Each tick is the timestamp at which one request's span was recovered from telemetry, not a
            latency. The two arms are separate sets of calls, so a tick in one has no partner in the
            other — this is a coverage view, and the paired estimator lives in the verdict record.
          </p>
        </>
      ) : stubbed.length ? null : (
        <div className="note">
          The arms carry counts but no per-request timestamps, so there is nothing to plot.
        </div>
      )}
      {stubbed.length ? (
        <div className="note">
          <strong>
            {stubbed.length === 1 ? "One arm's" : `${stubbed.length} arms'`} per-request timestamps are
            not on this page yet
          </strong>{" "}
          (<span className="mono">{stubbed.join(", ")}</span>). They were large enough to be published
          as a separate series; load them from <em>Heavy series</em> below and this plot fills in. The
          counts in the table above are the record's own and are complete either way.
        </div>
      ) : null}
    </section>
  );
}

export default function CaseDetail() {
  const { id = "" } = useParams();
  const res = useAsync(() => loadCase(id), [id]);
  const fam = useAsync(loadFamilies, []);

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

  if (res.state === "loading") return <Loading what={`case ${id}`} />;
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
      <p className="lede">{c.title}</p>
      <div style={{ marginBottom: 18 }}>
        <span className="chip">family {c.family}</span>
        <span className="chip">tier {c.tier}</span>
        {adj?.["kind"] ? <span className="chip">kind {String(adj["kind"])}</span> : null}
        {c.oracle_is_sealed ? <span className="chip sealed">oracle sealed</span> : null}
        {c.claims.map((cl) => (
          <Link key={cl} to={`/claims#${cl}`} className="chip">
            {cl}
          </Link>
        ))}
      </div>

      {famFlags?.network_position_sensitive ? (
        <div className="note warn">
          <strong>This case is network-position sensitive.</strong> {famFlags.why}
          {famFlags.replication_requirement ? <> {famFlags.replication_requirement}</> : null}
        </div>
      ) : null}

      <Restrictions items={c.citation_restrictions} />

      <section>
        <h3>Sealed oracle — the exact text this verdict answers</h3>
        <div className="verbatim">{c.oracle_text}</div>
        <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 8 }}>
          Quoted verbatim from the sealed oracle registry, whose hash is recomputed at every build. Not
          paraphrased and not shortened: the wording is the claim, and the verdict is an answer to this
          wording rather than to a summary of it.
        </p>
      </section>

      {c.instrument ? (
        <section>
          <h3>Instrument — how the claim was put to a measurement</h3>
          <div className="md">
            <p>{c.instrument}</p>
          </div>
        </section>
      ) : null}

      {adj ? (
        <section>
          <h3>Adjudication</h3>
          <table className="grid">
            <tbody>
              {split(adj).prim.map(([k, v]) => (
                <tr key={k}>
                  <th style={{ width: 200 }}>{k}</th>
                  <td>
                    <Any v={v} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {split(adj).comp.map(([k, v]) => (
            <div key={k} style={{ marginTop: 10 }}>
              <div style={{ color: "var(--fg-dim)", fontSize: 12, marginBottom: 4 }} className="mono">
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
          <h3>How the verdict was read</h3>
          {NARRATIVE.filter((k) => typeof rec[k] === "string").map((k) => (
            <div key={k} style={{ marginBottom: 10 }}>
              <div className="mono" style={{ color: "var(--fg-faint)", fontSize: 11.5 }}>
                {k}
              </div>
              <Body src={String(rec[k])} />
            </div>
          ))}
        </section>
      ) : null}

      {guards ? (
        <section>
          <h3>Guards — the conditions that had to hold for the measurement to count</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>guard</th>
                <th>held</th>
                <th>what it tested, and why</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(guards).map(([name, ok]) => {
                const d = asRecord(guardDetail?.[name]);
                return (
                  <tr key={name}>
                    <td className="mono">{name}</td>
                    <td>
                      <span className={`badge ${ok === true ? "v-TRUE" : "v-FALSE"}`}>
                        {ok === true ? "held" : String(ok)}
                      </span>
                    </td>
                    <td>
                      {d?.["test"] ? <div>{String(d["test"])}</div> : null}
                      {d?.["why"] ? (
                        <div style={{ color: "var(--fg-dim)", marginTop: 4 }}>{String(d["why"])}</div>
                      ) : null}
                      {!d?.["test"] && !d?.["why"] ? (
                        <span style={{ color: "var(--fg-faint)" }}>
                          no test/why recorded for this guard
                        </span>
                      ) : null}
                      {d ? <RawJson label="guard detail" value={d} /> : null}
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
          <h3>Blockers</h3>
          {Array.isArray(blockers["blockers"]) && (blockers["blockers"] as unknown[]).length ? (
            <RawJson label={`${(blockers["blockers"] as unknown[]).length} blocker(s)`} value={blockers["blockers"]} />
          ) : (
            <div className="note">No blocker was recorded for this case.</div>
          )}
          {typeof blockers["blockers_are_not_exhaustive"] === "string" ? (
            <p style={{ color: "var(--fg-dim)", fontSize: 12.5 }}>
              {String(blockers["blockers_are_not_exhaustive"])}
            </p>
          ) : null}
        </section>
      ) : null}

      {spanJoin ? <SpanJoin join={spanJoin} /> : null}

      <Replication c={c} />

      <section>
        <h3>Resources and run identity</h3>
        <KV
          rows={IDS.filter((k) => rec[k] !== undefined).map((k) => [k, <Any v={rec[k]} />] as [string, ReactNode])}
        />
        <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 8 }}>
          Account identifiers and bucket names are masked by the same redaction pass that guards the
          repository, so an identifier here reads as a placeholder rather than a real one.
        </p>
      </section>

      {rest.prim.length || rest.comp.length ? (
        <section>
          <h3>Everything else the record carries</h3>
          {rest.prim.length ? (
            <table className="grid" style={{ marginBottom: 12 }}>
              <tbody>
                {rest.prim.map(([k, v]) => (
                  <tr key={k}>
                    <th style={{ width: 260 }}>{k}</th>
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
          <h3>Heavy series</h3>
          <div className="note">
            This case's large arrays were split out of the case file to keep the page small and are
            published separately at <code>data/series/{c.case}.json</code>. Each one left a stub in the
            record naming its own path, its element count and its size, so this page can tell you what
            it is not showing you before it fetches anything.
          </div>
          <table className="grid" style={{ marginTop: 10, marginBottom: 10 }}>
            <thead>
              <tr>
                <th>path in the record</th>
                <th>elements</th>
                <th>size</th>
                <th>loaded</th>
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
                    <td className="mono">{path}</td>
                    <td className="num">{stub ? stub.n : "—"}</td>
                    <td className="num">{stub ? `${Math.round(stub.bytes / 1024)} KB` : "—"}</td>
                    <td className="num">
                      {Array.isArray(here) ? `yes (${here.length})` : series ? "MISSING" : "no"}
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
              {loadingSeries ? "loading…" : "Load the series into this page"}
            </button>
          )}
          {mine?.state === "error" ? <ErrorPanel error={mine.error} /> : null}
          {hydrated?.unresolved.length ? (
            <div className="note warn">
              <strong>The series file and this page disagree.</strong> These paths were published as
              series but this record carries no matching stub for them:{" "}
              <span className="mono">{hydrated.unresolved.join(", ")}</span>. Every panel above is
              therefore showing the record WITHOUT them. This should be impossible —{" "}
              <code>check_site_invariants.py</code> asserts at publish time that the stubs, the series
              file and <code>series_available</code> agree — so treat it as a payload defect rather
              than as a case whose series happened to be small.
            </div>
          ) : null}
          {series ? (
            <div className="note">
              Loaded. The panels above — the span join in particular — now render the full arrays, not
              the stubs.
            </div>
          ) : null}
        </section>
      ) : null}

      <section>
        <h3>The verdict file as published</h3>
        <RawJson label={c.verdict_file ?? "record"} value={rec} />
      </section>

      <p style={{ marginTop: 24 }}>
        <Link to="/">← back to the census</Link>
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
                <th style={{ width: 220 }}>{k}</th>
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
