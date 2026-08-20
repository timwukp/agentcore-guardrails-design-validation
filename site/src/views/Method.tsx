// View 10 — how a verdict is made.
//
// EVERY NUMBER ON THIS PAGE IS COUNTED FROM THE CORPUS IT DESCRIBES
//
// A method section is the easiest place in a study for prose and practice to come apart: the text says
// "each case declares named guards with a stated test", and nobody ever counts how many actually do.
// So this page states the method as a chain of steps and, at each step, renders the count derived from
// the verdict files themselves (`method.json`, recomputed on every build). Where the corpus does not
// live up to the description, the number says so on the same screen as the claim — which is the only
// arrangement under which a reader can tell the difference between a method and an intention.
//
// The two gaps this page currently reports, both derived and neither previously written down anywhere:
// most verdicts carry no statement of what they do not prove, and a handful of guards were recorded
// with no name at all. They are rendered as warnings, not hidden behind a total.

import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { loadFamilies, loadMethod } from "../lib/data";
import { ErrorPanel, KV, Loading, useAsync } from "../components/ui";
import { byCaseId } from "../lib/sort";
import type { Method } from "../lib/types";

const UNNAMED_GUARD = "(guard recorded without a name)";

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section>
      <h3>
        <span className="mono" style={{ color: "var(--fg-faint)" }}>
          {n}.
        </span>{" "}
        {title}
      </h3>
      {children}
    </section>
  );
}

function CaseList({ ids }: { ids: string[] }) {
  return (
    <span>
      {[...ids].sort(byCaseId).map((c, i) => (
        <span key={c}>
          {i ? ", " : ""}
          <Link to={`/case/${c}`} className="mono">
            {c}
          </Link>
        </span>
      ))}
    </span>
  );
}

/** kind -> count, and nothing more. Deliberately not a bar chart: the quantity is "how many cases
 *  happen to use this oracle shape", which is a property of what was worth measuring, not a magnitude
 *  anyone should compare across kinds. */
function KindTable({ kinds }: { kinds: Record<string, number> }) {
  const rows = Object.entries(kinds).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return (
    <div className="scroll" style={{ maxHeight: 360 }}>
      <table className="grid">
        <thead>
          <tr>
            <th>oracle kind</th>
            <th>cases</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, n]) => (
            <tr key={k}>
              <td className="mono">{k}</td>
              <td className="num">{n}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Guards({ m }: { m: Method }) {
  const [q, setQ] = useState("");
  const entries = Object.entries(m.guard_names).filter(([k]) => k !== UNNAMED_GUARD);
  const unnamed = m.guard_names[UNNAMED_GUARD] ?? 0;
  const needle = q.trim().toLowerCase();
  const shown = entries
    .filter(([k]) => !needle || k.toLowerCase().includes(needle))
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const once = entries.filter(([, n]) => n === 1).length;

  return (
    <>
      <p>
        A guard is a condition the measurement had to satisfy before its result was allowed to count —
        that the two arms were disjoint, that the blocking policy was load-bearing before the mutation,
        that the restore was verified afterwards. Guards are named per case, and the case page prints
        each one's <code>test</code> and <code>why</code> beside whether it held.
      </p>
      <div className="cards" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="n">{entries.length}</div>
          <div className="k">distinct named guards</div>
          <div className="def">
            Across every published verdict. Guards are written per case rather than drawn from a fixed
            list, which is why there are this many.
          </div>
        </div>
        <div className="card">
          <div className="n">{once}</div>
          <div className="k">named by exactly one case</div>
          <div className="def">
            A guard used once is not a weaker guard; it means the condition that could have invalidated
            that one measurement was specific to it.
          </div>
        </div>
      </div>

      {unnamed ? (
        <div className="note warn">
          <strong>{unnamed} guard(s) are recorded without a name.</strong> Their records carry a test
          and a result but no identifier, so they cannot be counted as any of the {entries.length} named
          guards above and cannot be searched for here. The build files them under an explicit bucket
          rather than coercing the record into a name — a guard census that silently invented one would
          disagree with the case pages, which show these guards exactly as stored. Recording a guard
          without a name is a defect in the producer, and this is the number.
        </div>
      ) : null}

      <div className="facets">
        <div className="facet">
          <label>search guards</label>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. restore, arms, seal" />
        </div>
        <div className="facet">
          <label>&nbsp;</label>
          <span className="count mono">{shown.length} shown</span>
        </div>
      </div>
      <div className="scroll" style={{ maxHeight: 420 }}>
        <table className="grid">
          <thead>
            <tr>
              <th>guard</th>
              <th>cases naming it</th>
            </tr>
          </thead>
          <tbody>
            {shown.map(([k, n]) => (
              <tr key={k}>
                <td className="mono">{k}</td>
                <td className="num">{n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Caveats({ m }: { m: Method }) {
  const c = m.caveats;
  return (
    <>
      <p>
        A verdict answers exactly one question. What it does <em>not</em> answer is the part a reader
        will get wrong, and the record has a field for it: <code>what_true_does_not_prove</code> and{" "}
        <code>what_false_does_not_prove</code>. Every case page renders that section whether or not the
        record fills it in, so an absent caveat is visible on the case rather than only in this total.
      </p>
      <div className="cards" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="n">
            {c.cases_with_what_false_does_not_prove} / {c.false_verdicts}
          </div>
          <div className="k">FALSE verdicts stating what they do not prove</div>
          <div className="def">
            A FALSE verdict says published guidance did not hold under this measurement. It does not say
            the control is useless, nor that the failure generalises past the configuration measured.
          </div>
        </div>
        <div className="card">
          <div className="n">
            {c.cases_with_what_true_does_not_prove} / {c.true_verdicts}
          </div>
          <div className="k">TRUE verdicts stating what they do not prove</div>
          <div className="def">
            A TRUE verdict says the stated condition held in the configuration measured, on the days
            measured. Anything wider than that is an inference the reader is making, not one recorded.
          </div>
        </div>
      </div>
      <div className="note warn">
        <strong>This is a gap in the corpus, not a rendering choice.</strong> {c.why_this_is_counted}
        <div style={{ marginTop: 8 }}>
          FALSE without the caveat ({c.false_verdicts_without_the_caveat.length}):{" "}
          <CaseList ids={c.false_verdicts_without_the_caveat} />
        </div>
        <div style={{ marginTop: 6 }}>
          TRUE without the caveat ({c.true_verdicts_without_the_caveat.length}):{" "}
          <CaseList ids={c.true_verdicts_without_the_caveat} />
        </div>
      </div>
    </>
  );
}

function Replication({ m }: { m: Method }) {
  const twoDay = Object.entries(m.archive_days_by_case)
    .filter(([, d]) => new Set(d).size >= 2)
    .map(([c]) => c);
  const oneDay = Object.entries(m.archive_days_by_case)
    .filter(([, d]) => new Set(d).size < 2)
    .map(([c]) => c);

  return (
    <>
      <p>
        A measurement made once is a measurement, not a replication. The study keeps day-1 verdict files
        under <span className="mono">results/phase1/archive/</span>, and a case counts as replicated only
        when two <strong>distinct UTC calendar days</strong> exist — one day repeated is a re-run, and it
        cannot distinguish a stable property from a property of that day.
      </p>
      <div className="cards" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="n">{m.n_cases_with_an_archive}</div>
          <div className="k">cases with at least one archived run</div>
          <div className="def">
            An archive exists for the case. This number alone establishes nothing about replication.
          </div>
        </div>
        <div className="card">
          <div className="n">{m.n_cases_with_two_distinct_archive_days}</div>
          <div className="k">cases with archives from two distinct UTC days</div>
          <div className="def">
            The only cases where the archive itself can support the word "replicated". Counted from the
            dates in the archive filenames, not from any status field.
          </div>
        </div>
        <div className="card">
          <div className="n">{m.archives_disagreeing_with_the_live_verdict.length}</div>
          <div className="k">archives whose verdict differs from the live one</div>
          <div className="def">
            A disagreement is a finding. It is not resolved by preferring the newer run, and nothing here
            silently prefers one.
          </div>
        </div>
      </div>

      {m.archives_disagreeing_with_the_live_verdict.length ? (
        <table className="grid" style={{ marginBottom: 14 }}>
          <thead>
            <tr>
              <th>case</th>
              <th>archived verdict</th>
              <th>live verdict</th>
              <th>archive label</th>
            </tr>
          </thead>
          <tbody>
            {[...m.archives_disagreeing_with_the_live_verdict]
              .sort((a, b) => byCaseId(a.case, b.case))
              .map((d, n) => (
                <tr key={n}>
                  <td className="mono">
                    <Link to={`/case/${d.case}`}>{d.case}</Link>
                  </td>
                  <td className="mono">{d.archived_verdict}</td>
                  <td className="mono">{d.live_verdict ?? "—"}</td>
                  <td className="mono">{d.label}</td>
                </tr>
              ))}
          </tbody>
        </table>
      ) : null}

      <KV
        rows={[
          ["two distinct UTC days", twoDay.length ? <CaseList ids={twoDay} /> : "none"],
          ["archive on one day only", oneDay.length ? <CaseList ids={oneDay} /> : "none"],
        ]}
      />
    </>
  );
}

function FamilyTable() {
  const res = useAsync(loadFamilies, []);
  if (res.state === "loading") return <Loading what="the family classification" />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const f = res.data;
  const rows = Object.entries(f.families).sort((a, b) =>
    a[0].localeCompare(b[0], undefined, { numeric: true }),
  );

  return (
    <>
      <p>
        Re-running a measurement is not uniformly safe or uniformly free, so each family carries an
        authored classification in <span className="mono">platform/curation/families.yaml</span>: what a
        re-run costs, where it must run, what it mutates, and whether it may be scheduled at all. The
        build refuses to emit this file if a registered family is missing from it <em>or</em> if it
        classifies a family that does not exist — a family added later must be classified before it can
        be scheduled, rather than becoming schedulable by omission. A family marked not schedulable must
        state why, in the file.
      </p>
      <div className="scroll">
        <table className="grid">
          <thead>
            <tr>
              <th>family</th>
              <th>cases</th>
              <th>cost class</th>
              <th>runner</th>
              <th>mutates</th>
              <th>schedulable</th>
              <th>why not / note</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([id, x]) => (
              <tr key={id}>
                <td className="mono">{id}</td>
                <td className="num">{x.n_cases}</td>
                <td className="mono">{x.cost}</td>
                <td className="mono" style={x.runner === "macbook_only" ? { color: "var(--warn)" } : undefined}>
                  {x.runner}
                </td>
                <td className="mono">{x.mutates}</td>
                <td className="mono">{x.schedulable ? "yes" : "no"}</td>
                <td style={{ minWidth: 320 }}>
                  {x.why_not_schedulable ?? x.calendar_gate ?? x.note ?? (
                    <span style={{ color: "var(--fg-faint)" }}>—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 8 }}>
        <code>cost</code> here is a class, never a dollar figure — money has exactly one source in this
        project, and it is not this file. Vocabularies:{" "}
        {Object.entries(f.vocabularies)
          .map(([k, v]) => `${k} ∈ {${v.join(", ")}}`)
          .join("; ")}
        .
      </p>

      {rows
        .filter(([, x]) => x.network_position_sensitive)
        .map(([id, x]) => (
          <div className="note warn" key={id}>
            <strong>{id} is network-position sensitive.</strong> {x.why}
            <div style={{ marginTop: 6 }}>{x.replication_requirement}</div>
            {x.ui_state_note ? (
              <div style={{ marginTop: 6, color: "var(--fg-dim)" }}>
                UI state when old: <span className="mono">{x.ui_state_when_old}</span> — {x.ui_state_note}
              </div>
            ) : null}
          </div>
        ))}
    </>
  );
}

export default function MethodView() {
  const res = useAsync(loadMethod, []);
  if (res.state === "loading") return <Loading what="the method census" />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const m = res.data;

  return (
    <>
      <h2 className="view">How a verdict is made</h2>
      <p className="lede">
        The chain every case travels, from a sentence in the design document to a verdict that may be
        cited — with the count, at each step, of how many cases actually satisfy the step as described.
      </p>

      <div className="note seal">
        {m.note} Nothing on this page is authored prose about the data; the prose describes the
        procedure, and every number beside it is counted from the verdict files at build time.
      </div>

      <Step n={1} title="A claim is extracted and sealed">
        <p>
          Each unit of the design document becomes a row in <span className="mono">claims/triage.csv</span>{" "}
          with its classification, its anchor, and the document line it came from. That file is{" "}
          <strong>sealed</strong>: it was fixed before any measurement ran, so a claim cannot be quietly
          reworded to match what was later found. The <Link to="/claims">claim triage</Link> view renders
          it exactly as stored.
        </p>
      </Step>

      <Step n={2} title="An oracle is written before the measurement, and hashed">
        <p>
          For each case an oracle states, in advance, the condition under which the claim counts as held —
          a threshold, an enumeration, an interval relation. The oracle text is registered in{" "}
          <span className="mono">PREREGISTRATION.yaml</span> and hashed; the build re-verifies those hashes
          on every run, so a drifted seal fails the publish rather than reaching this page. Case pages quote{" "}
          <code>oracle_text</code> verbatim and never paraphrase it, because a paraphrase of a sealed
          oracle is a new oracle.
        </p>
        <p>
          The {Object.keys(m.kinds).length} oracle shapes in use, and how many cases use each:
        </p>
        <KindTable kinds={m.kinds} />
      </Step>

      <Step n={3} title="An instrument runs, and guards decide whether its output counts">
        <Guards m={m} />
      </Step>

      <Step n={4} title="A verdict is read off the oracle — one of four values">
        <p>
          <strong>TRUE</strong> and <strong>FALSE</strong> are readings of the sealed condition.{" "}
          <strong>INCONCLUSIVE</strong> is a first-class outcome, not a weak TRUE and not a soft FALSE: it
          says the measurement did not establish the condition either way, and it licenses no amendment in
          either direction. <strong>RECORDED</strong> is a written observation that was never adjudicated
          against an oracle at all, and may not be cited as a verdict. There is no pass rate anywhere in
          this platform, because a ratio over four values that do not share an axis would not mean
          anything — and the FALSE verdicts, which locate where published guidance did not hold, are the
          most valuable output the study has.
        </p>
      </Step>

      <Step n={5} title="What the verdict does not prove is stated — or its absence is counted">
        <Caveats m={m} />
      </Step>

      <Step n={6} title="Replication is two distinct days, or it is not replication">
        <Replication m={m} />
      </Step>

      <Step n={7} title="Re-running is classified before it is permitted">
        <FamilyTable />
      </Step>

      <Step n={8} title="Only then may a document change be proposed">
        <p>
          An amendment to the design document must rest on a verdict that survived replication, and the
          gate between "measured" and "proposed" is a script, not a judgment call. An INCONCLUSIVE verdict
          produces zero proposed lines. What may and may not be cited from a given verdict is data, in{" "}
          <Link to="/citations">the citation policy</Link>, rendered on each case page from the same file —
          so the rule and its display cannot drift apart. Where the study falls short of all of this, it is
          written down in <Link to="/register">the deficiency register</Link> rather than fixed silently.
        </p>
      </Step>
    </>
  );
}
