// View 13 — the audit report: what the two programs say about a submission, and what licenses each word.
//
// TWO SOURCES, ONE RENDERER, AND WHY THAT MATTERS
//
// This page renders either the worked example that ships in the payload or a `report.json` the reader
// produced on their own machine, through exactly the same components. That is deliberate: if the
// example were rendered by a nicer path than a reader's own output, the page would be a brochure. The
// only difference between the two is the banner at the top saying which one is on screen.
//
// The reader's file is read with `FileReader` and never leaves the browser. There is no upload, no
// fetch, no `POST` — the file input is a local decoder, and the boundary is checkable in the network
// panel: selecting a file produces no request. The schema is checked before anything renders, because
// a JSON file that is not a report would otherwise render as a report with every section empty, which
// reads as "your submission has no problems".
//
// WHY THE HEADLINE IS SEVEN NUMBERS AND NOT ONE
//
// There is no score. A single figure over these controls would have to divide "measured, and the
// guidance did not hold" by the same denominator as "this study never examined it", and those are not
// commensurable — the second is a statement about this study's coverage, not about the reader's
// deployment. So the report states each bucket separately and publishes the sentence explaining why
// there is no ratio; the publish gate fails on any rate, score or percentage in this file.
//
// WHY EVERY RECOMMENDATION CARRIES ITS CASES
//
// A recommendation is the only instruction this platform ever gives. It is licensed by a citable
// verdict or it is withheld, and the cases that license it are rendered beside it so a reader can open
// them and disagree. An INCONCLUSIVE verdict licenses no amendment to this study's own document, so it
// licenses no advice about somebody else's deployment either — those controls appear under "withheld",
// with the reason, rather than silently absent.

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { loadAudit } from "../lib/data";
import { ErrorPanel, Loading, useAsync } from "../components/ui";
import { ObsBadge, StatusBadge } from "./Audit";
import { decodeReport } from "../lib/audit";
import type { AuditPage, AuditReport, ReportControlLine, ReportMeasurement } from "../lib/types";

/** A download of bytes this page already holds. Composed as a Blob URL at click time and revoked
 *  afterwards, so nothing is fetched and nothing is left allocated. */
function Download({ name, text, type, label }: { name: string; text: string; type: string; label: string }) {
  return (
    <button
      type="button"
      className="btn"
      onClick={() => {
        const url = URL.createObjectURL(new Blob([text], { type }));
        const el = document.createElement("a");
        el.href = url;
        el.download = name;
        el.click();
        URL.revokeObjectURL(url);
      }}
    >
      {label}
    </button>
  );
}

function Sites({ line }: { line: ReportControlLine }) {
  if (!line.sites.length && !line.unresolved.length)
    return <span style={{ color: "var(--fg-faint)" }}>—</span>;
  return (
    <div style={{ fontSize: 11.5 }}>
      {line.sites.map((s, n) => (
        <div className="mono" key={`s${n}`} style={{ wordBreak: "break-all" }}>
          {s.file}:{s.line} · {s.path}
          {s.value === null || s.value === undefined ? null : (
            <>
              {" = "}
              <strong>{s.value}</strong>
            </>
          )}
        </div>
      ))}
      {line.unresolved.map((s, n) => (
        <div className="mono" key={`u${n}`} style={{ color: "var(--warn)", wordBreak: "break-all" }}>
          {s.file}:{s.line} · {s.path} = unresolved{s.unresolved_tag ? ` (${s.unresolved_tag})` : ""}
        </div>
      ))}
    </div>
  );
}

function Measurement({ m }: { m: ReportMeasurement }) {
  return (
    <div className="meas">
      <div>
        <StatusBadge s={m.status} label={m.status_label} />{" "}
        <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>{m.status_label}</span>
      </div>
      {m.says ? <p style={{ margin: "6px 0 0", whiteSpace: "pre-wrap" }}>{m.says.trim()}</p> : null}
      {m.consequence ? (
        <p style={{ margin: "6px 0 0", color: "var(--fg-dim)", whiteSpace: "pre-wrap" }}>
          {m.consequence.trim()}
        </p>
      ) : null}
      {m.scope_note ? (
        <div className="note" style={{ margin: "8px 0 0" }}>
          <strong>Scope:</strong> {m.scope_note.trim()}
        </div>
      ) : null}
      {m.why_not_measured ? (
        <div className="note warn" style={{ margin: "8px 0 0" }}>
          <strong>Why this study never examined it:</strong> {m.why_not_measured.trim()}
        </div>
      ) : null}
      <div style={{ marginTop: 8 }}>
        {m.cases.map((k) => (
          <div key={k.case} style={{ marginBottom: 4 }}>
            <Link to={`/case/${k.case}`} className="chip">
              {k.case} · {k.verdict}
            </Link>
            {k.restrictions.map((r) => (
              <span key={r} className="badge restrict" style={{ marginRight: 4 }}>
                {r}
              </span>
            ))}
            {k.limits_stated_by_the_case && k.what_this_verdict_does_not_prove ? (
              <div style={{ color: "var(--fg-dim)", fontSize: 12, marginLeft: 4 }}>
                What it does not prove: {k.what_this_verdict_does_not_prove.trim()}
              </div>
            ) : (
              <div style={{ color: "var(--warn)", fontSize: 12, marginLeft: 4 }}>
                This case file states no limit on its own verdict, so treat the verdict as narrower than
                it reads.
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ControlBlock({ line }: { line: ReportControlLine }) {
  return (
    <div className="ctl">
      <div className="head">
        <ObsBadge o={line.observation} />
        <strong style={{ marginLeft: 8 }}>{line.label}</strong>
        <span className="mono" style={{ marginLeft: 8, color: "var(--fg-faint)", fontSize: 11.5 }}>
          {line.control}
        </span>
      </div>
      <p style={{ color: "var(--fg-dim)", margin: "4px 0 8px" }}>{line.question}</p>
      <table className="grid">
        <tbody>
          <tr>
            <th style={{ width: 190 }}>Declared value</th>
            <td>
              {line.value !== null ? (
                <span className="mono">
                  <strong>{line.value}</strong>
                </span>
              ) : line.values_seen.length ? (
                <span className="mono">{line.values_seen.join(", ")}</span>
              ) : (
                <span style={{ color: "var(--fg-faint)" }}>
                  no value read — this control is detected by the presence of its properties, not by a
                  value
                </span>
              )}
              {line.disagreement?.length ? (
                <div className="note warn" style={{ margin: "8px 0 0" }}>
                  <strong>Two different values are declared across your files:</strong>{" "}
                  <span className="mono">{line.disagreement.join(", ")}</span>. Every measurement below
                  is stated per value, because a staging template that disagrees with production is a
                  real state and not a parse error.
                </div>
              ) : null}
              {line.values_outside_the_declared_enum?.length ? (
                <div className="note warn" style={{ margin: "8px 0 0" }}>
                  Value(s) outside the vocabulary this control knows:{" "}
                  <span className="mono">{line.values_outside_the_declared_enum.join(", ")}</span>. No
                  measurement covers them.
                </div>
              ) : null}
            </td>
          </tr>
          <tr>
            <th>Where it was found</th>
            <td>
              <Sites line={line} />
            </td>
          </tr>
          {line.why_this_status ? (
            <tr>
              <th>Why this reads {line.observation}</th>
              <td>{line.why_this_status}</td>
            </tr>
          ) : null}
        </tbody>
      </table>
      {line.measurements.length ? (
        line.measurements.map((m, n) => <Measurement key={n} m={m} />)
      ) : (
        <div className="note" style={{ marginTop: 10 }}>
          This study has no measurement that applies to what your files declare here. That is a statement
          about this study's coverage, not about your deployment.
        </div>
      )}
    </div>
  );
}

function ReportBody({ r }: { r: AuditReport }) {
  const h = r.headline;
  const cards: [number, string, string | null][] = [
    [h.controls_the_study_covers, "controls this study can speak to", null],
    [h.controls_you_declare, "of them your files declare", null],
    [
      h.declared_with_a_measurement,
      "declared, and measured by this study",
      "The only bucket where a finding rests on a measurement of the value you declare.",
    ],
    [
      h.declared_where_the_guidance_did_not_hold,
      "declared, and the guidance did NOT hold",
      "Measured, and the documented behaviour was not observed. These are the findings.",
    ],
    [
      h.declared_never_measured_by_this_study,
      "declared, never examined here",
      "Not a clean result. Nothing was tested, so nothing is claimed.",
    ],
    [
      h.declared_in_a_state_no_measurement_covers,
      "declared in a state no measurement covers",
      "The control was measured, but not at the value your files declare.",
    ],
    [
      h.not_seen_in_the_parsed_files,
      "not seen in the parsed files",
      "NOT_DECLARED means the parser did not find it. It is not evidence the control is absent.",
    ],
  ];

  return (
    <>
      <h3>Headline</h3>
      <p style={{ whiteSpace: "pre-wrap" }}>{h.statement.trim()}</p>
      <div className="cards">
        {cards.map(([n, k, def]) => (
          <div className="card" key={k}>
            <div className="n">{n}</div>
            <div className="k">{k}</div>
            {def ? <div className="def">{def}</div> : null}
          </div>
        ))}
      </div>
      <div className="note" style={{ marginTop: 12 }}>
        <strong>Why there is no pass rate here:</strong> {h.why_this_report_gives_no_ratio.trim()}
      </div>

      <h3>What the report was written against</h3>
      <table className="grid">
        <tbody>
          <tr>
            <th style={{ width: 260 }}>Report date</th>
            <td className="mono">
              {r.as_of ?? "none — the tool reads no clock, so the report is byte-identical on re-run"}
            </td>
          </tr>
          <tr>
            <th>Evidence through at least</th>
            <td className="mono">{r.evidence_through_at_least ?? "not derivable"}</td>
          </tr>
          <tr>
            <th>Cases registered / verdicts published</th>
            <td className="mono">
              {r.study.cases_registered} / {r.study.verdicts_published}
            </td>
          </tr>
          <tr>
            <th>Verdict mix behind every line below</th>
            <td>
              {Object.entries(r.study.verdict_mix).map(([v, n]) => (
                <span key={v} className={`badge v-${v}`} style={{ marginRight: 6 }}>
                  {v} {n}
                </span>
              ))}
            </td>
          </tr>
          <tr>
            <th>Resources parsed</th>
            <td className="mono">{r.inventory.resources.length}</td>
          </tr>
        </tbody>
      </table>

      <h3>Recommendations</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        {r.recommendations.length} recommendation(s), each licensed by a citable verdict named beside it.
        A recommendation with no case is not written at all.
      </p>
      <div className="scroll">
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 170 }}>Control</th>
              <th>What to do, and why</th>
              <th style={{ width: 180 }}>Licensed by</th>
              <th style={{ width: 170 }}>Where</th>
            </tr>
          </thead>
          <tbody>
            {r.recommendations.map((x, n) => (
              <tr key={n}>
                <td>
                  <div className="mono">{x.control}</div>
                  <div style={{ color: "var(--fg-dim)", fontSize: 12 }}>{x.label}</div>
                  <div style={{ marginTop: 4 }}>
                    <ObsBadge o={x.observation} />
                  </div>
                </td>
                <td>
                  <div style={{ whiteSpace: "pre-wrap" }}>{x.recommendation.trim()}</div>
                  <div
                    style={{ color: "var(--fg-dim)", fontSize: 12, marginTop: 6, whiteSpace: "pre-wrap" }}
                  >
                    {x.because.trim()}
                  </div>
                  {x.scope_note ? (
                    <div style={{ color: "var(--warn)", fontSize: 12, marginTop: 6 }}>
                      Scope: {x.scope_note.trim()}
                    </div>
                  ) : null}
                </td>
                <td>
                  {x.licensed_by.map((l) => (
                    <Link key={l.case} to={`/case/${l.case}`} className="chip">
                      {l.case} · {l.verdict}
                    </Link>
                  ))}
                </td>
                <td className="mono" style={{ fontSize: 11.5, wordBreak: "break-all" }}>
                  {x.sites.join(" ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Recommendations deliberately withheld</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        {r.recommendations_withheld.length} control(s) where something was declared and this study
        declines to advise. Listed rather than omitted: an absent row would read as a control with
        nothing to say about it.
      </p>
      <table className="grid">
        <thead>
          <tr>
            <th style={{ width: 190 }}>Control</th>
            <th style={{ width: 170 }}>State</th>
            <th>Why nothing is recommended</th>
          </tr>
        </thead>
        <tbody>
          {r.recommendations_withheld.map((w, n) => (
            <tr key={n}>
              <td className="mono">{w.control}</td>
              <td>
                <StatusBadge s={w.status} />
              </td>
              <td style={{ whiteSpace: "pre-wrap" }}>{w.why_withheld.trim()}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Control by control</h3>
      {r.controls.map((line) => (
        <ControlBlock key={line.control} line={line} />
      ))}

      <h3>Caveats that apply to every line above</h3>
      <ul>
        {r.caveats.map((cv, n) => (
          <li key={n} style={{ marginBottom: 8 }}>
            {cv}
          </li>
        ))}
      </ul>
    </>
  );
}

export default function Report() {
  const res = useAsync(loadAudit, []);
  const [own, setOwn] = useState<{ name: string; report: AuditReport } | null>(null);
  const [readError, setReadError] = useState<string | null>(null);

  const shown = useMemo(
    () => (own ? own.report : res.state === "ok" ? res.data.report : null),
    [own, res],
  );

  if (res.state === "loading") return <Loading what="the audit report" />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const a: AuditPage = res.data;

  return (
    <>
      <h2>Audit report</h2>
      <p className="lede">
        {own ? (
          <>
            Rendering <span className="mono">{own.name}</span>, decoded in this browser. It was not
            uploaded: selecting it produced no network request, which you can confirm in your browser's
            network panel.
          </>
        ) : (
          <>
            The worked example, produced at build time by running{" "}
            <span className="mono">{a.tools.parse}</span> and <span className="mono">{a.tools.report}</span>{" "}
            over <span className="mono">{a.example.submission}</span> — the same two programs the{" "}
            <Link to="/audit">intake page</Link> composes commands for, run over{" "}
            {a.example.n_files} checked-in files. Nothing here was written by hand.
          </>
        )}
      </p>

      {!own && a.example.is_synthetic ? (
        <div className="note warn">
          <strong>This submission is synthetic.</strong>{" "}
          <span style={{ whiteSpace: "pre-wrap" }}>{a.example.why_synthetic.trim()}</span>
        </div>
      ) : null}

      <h3>Render a report of your own</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        Run the three commands from the <Link to="/audit">intake page</Link> and select the{" "}
        <span className="mono">report.json</span> they wrote. The file is decoded with{" "}
        <span className="mono">FileReader</span> in this tab; this site has no endpoint that accepts a
        request body, so there is nowhere for it to be sent even if a future version tried.
      </p>
      <div className="intake">
        <label>
          <span>Your report.json</span>
          <input
            type="file"
            accept=".json,application/json"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              setReadError(null);
              f.text().then(
                (t) => {
                  const out = decodeReport(t);
                  if ("error" in out) {
                    setOwn(null);
                    setReadError(out.error);
                  } else {
                    setOwn({ name: f.name, report: out.report });
                  }
                },
                (err) => setReadError(`Could not read the file: ${String(err)}`),
              );
            }}
          />
        </label>
        {own ? (
          <button type="button" className="btn" onClick={() => setOwn(null)}>
            Back to the worked example
          </button>
        ) : null}
      </div>
      {readError ? <div className="note warn">{readError}</div> : null}

      {!own ? (
        <p>
          <Download
            name="grx-audit-example.md"
            text={a.markdown}
            type="text/markdown"
            label="Download this report as Markdown"
          />{" "}
          <Download
            name="grx-audit-example.json"
            text={JSON.stringify(a.report, null, 2)}
            type="application/json"
            label="Download it as JSON"
          />{" "}
          <Download
            name="grx-audit-example-inventory.json"
            text={JSON.stringify(a.inventory, null, 2)}
            type="application/json"
            label="Download the inventory the parser wrote"
          />
        </p>
      ) : null}

      {shown ? <ReportBody r={shown} /> : null}

      {!own ? (
        <>
          <h3>The Markdown the tool wrote, verbatim</h3>
          <p style={{ color: "var(--fg-dim)" }}>
            Rendered as text rather than as formatted Markdown on purpose: this is the deliverable a
            reader hands to a colleague, and the point of showing it here is that it is the same bytes,
            not a prettier version of them.
          </p>
          <details className="raw">
            <summary>{a.markdown.split("\n").length} lines of Markdown</summary>
            <div>
              <pre>
                <code>{a.markdown}</code>
              </pre>
            </div>
          </details>
        </>
      ) : null}

      <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 16 }}>{a.note}</p>
    </>
  );
}
