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
import { T, useT, VerbatimNote } from "../lib/i18n";
import { ObsBadge, StatusBadge } from "./Audit";
import { decodeReport } from "../lib/audit";
import type { Key } from "../lib/strings";
import type { Msg } from "../lib/audit";
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
  const t = useT();
  if (!line.sites.length && !line.unresolved.length)
    return <span style={{ color: "var(--fg-faint)" }}>—</span>;
  return (
    <div style={{ fontSize: 11.5 }}>
      {line.sites.map((s, n) => (
        // A file path, a config path and the value read at it — bytes out of the audited repository,
        // Cedar policy text included, so the whole line is quoted rather than translated.
        <div className="mono" key={`s${n}`} lang="en" style={{ wordBreak: "break-all" }}>
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
        <div
          className="mono"
          key={`u${n}`}
          lang="en"
          style={{ color: "var(--warn)", wordBreak: "break-all" }}
        >
          {s.file}:{s.line} · {s.path} = {t("rep.unresolved")}
          {s.unresolved_tag ? ` (${s.unresolved_tag})` : ""}
        </div>
      ))}
    </div>
  );
}

function Measurement({ m }: { m: ReportMeasurement }) {
  const t = useT();
  return (
    <div className="meas">
      <div>
        <StatusBadge s={m.status} label={m.status_label} />{" "}
        <span style={{ color: "var(--fg-dim)", fontSize: 12 }} lang="en">
          {m.status_label}
        </span>
      </div>
      {/* `says`, `consequence`, `scope_note` and `why_not_measured` are the report's own sentences,
          written by `platform/audit/report.py` from the case files. They are the deliverable a reader
          hands to a colleague, so they render verbatim; the labels in front of them are ours. */}
      {m.says ? (
        <p style={{ margin: "6px 0 0", whiteSpace: "pre-wrap" }} lang="en">
          {m.says.trim()}
        </p>
      ) : null}
      {m.consequence ? (
        <p style={{ margin: "6px 0 0", color: "var(--fg-dim)", whiteSpace: "pre-wrap" }} lang="en">
          {m.consequence.trim()}
        </p>
      ) : null}
      {m.scope_note ? (
        <div className="note" style={{ margin: "8px 0 0" }}>
          <strong>{t("rep.scope")}</strong> <span lang="en">{m.scope_note.trim()}</span>
        </div>
      ) : null}
      {m.why_not_measured ? (
        <div className="note warn" style={{ margin: "8px 0 0" }}>
          <strong>{t("rep.neverExamined")}</strong> <span lang="en">{m.why_not_measured.trim()}</span>
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
                {t("rep.doesNotProve")}{" "}
                <span lang="en">{k.what_this_verdict_does_not_prove.trim()}</span>
              </div>
            ) : (
              <div style={{ color: "var(--warn)", fontSize: 12, marginLeft: 4 }}>
                {t("rep.noLimitStated")}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ControlBlock({ line }: { line: ReportControlLine }) {
  const t = useT();
  return (
    <div className="ctl">
      <div className="head">
        <ObsBadge o={line.observation} />
        <strong style={{ marginLeft: 8 }} lang="en">
          {line.label}
        </strong>
        <span className="mono" style={{ marginLeft: 8, color: "var(--fg-faint)", fontSize: 11.5 }}>
          {line.control}
        </span>
      </div>
      <p style={{ color: "var(--fg-dim)", margin: "4px 0 8px" }} lang="en">
        {line.question}
      </p>
      <table className="grid">
        <tbody>
          <tr>
            <th style={{ width: 190 }}>{t("rep.th.declaredValue")}</th>
            <td>
              {line.value !== null ? (
                <span className="mono" lang="en">
                  <strong>{line.value}</strong>
                </span>
              ) : line.values_seen.length ? (
                <span className="mono" lang="en">
                  {line.values_seen.join(", ")}
                </span>
              ) : (
                <span style={{ color: "var(--fg-faint)" }}>{t("rep.noValueRead")}</span>
              )}
              {line.disagreement?.length ? (
                <div className="note warn" style={{ margin: "8px 0 0" }}>
                  <T
                    k="rep.disagreement"
                    v={{
                      head: <strong>{t("rep.disagreement.head")}</strong>,
                      values: <span className="mono">{line.disagreement.join(", ")}</span>,
                    }}
                  />
                </div>
              ) : null}
              {line.values_outside_the_declared_enum?.length ? (
                <div className="note warn" style={{ margin: "8px 0 0" }}>
                  <T
                    k="rep.outsideEnum"
                    v={{
                      values: (
                        <span className="mono">
                          {line.values_outside_the_declared_enum.join(", ")}
                        </span>
                      ),
                    }}
                  />
                </div>
              ) : null}
            </td>
          </tr>
          <tr>
            <th>{t("rep.th.whereFound")}</th>
            <td>
              <Sites line={line} />
            </td>
          </tr>
          {line.why_this_status ? (
            <tr>
              <th>
                <T k="rep.th.whyReads" v={{ o: <span lang="en">{line.observation}</span> }} />
              </th>
              <td lang="en">{line.why_this_status}</td>
            </tr>
          ) : null}
        </tbody>
      </table>
      {line.measurements.length ? (
        line.measurements.map((m, n) => <Measurement key={n} m={m} />)
      ) : (
        <div className="note" style={{ marginTop: 10 }}>
          {t("rep.noMeasurement")}
        </div>
      )}
    </div>
  );
}

function ReportBody({ r }: { r: AuditReport }) {
  const t = useT();
  const h = r.headline;
  // Keyed by the dictionary key rather than by the label, so switching language does not remount the
  // cards and a card can never end up keyed by a string that changed under it.
  const cards: [number, Key, Key | null][] = [
    [h.controls_the_study_covers, "rep.card.covers", null],
    [h.controls_you_declare, "rep.card.youDeclare", null],
    [h.declared_with_a_measurement, "rep.card.measured", "rep.card.measured.def"],
    [h.declared_where_the_guidance_did_not_hold, "rep.card.didNotHold", "rep.card.didNotHold.def"],
    [h.declared_never_measured_by_this_study, "rep.card.neverExamined", "rep.card.neverExamined.def"],
    [h.declared_in_a_state_no_measurement_covers, "rep.card.noCoverage", "rep.card.noCoverage.def"],
    [h.not_seen_in_the_parsed_files, "rep.card.notSeen", "rep.card.notSeen.def"],
  ];

  return (
    <>
      <h3>{t("rep.h.headline")}</h3>
      <p style={{ whiteSpace: "pre-wrap" }} lang="en">
        {h.statement.trim()}
      </p>
      <div className="cards">
        {cards.map(([n, k, def]) => (
          <div className="card" key={k}>
            <div className="n">{n}</div>
            <div className="k">{t(k)}</div>
            {def ? <div className="def">{t(def)}</div> : null}
          </div>
        ))}
      </div>
      <div className="note" style={{ marginTop: 12 }}>
        <strong>{t("rep.noRatio")}</strong>{" "}
        <span lang="en">{h.why_this_report_gives_no_ratio.trim()}</span>
      </div>

      <h3>{t("rep.h.writtenAgainst")}</h3>
      <table className="grid">
        <tbody>
          <tr>
            <th style={{ width: 260 }}>{t("rep.th.reportDate")}</th>
            <td className={r.as_of ? "mono" : undefined}>{r.as_of ?? t("rep.noClock")}</td>
          </tr>
          <tr>
            <th>{t("rep.th.evidenceThrough")}</th>
            <td className={r.evidence_through_at_least ? "mono" : undefined}>
              {r.evidence_through_at_least ?? t("rep.notDerivable")}
            </td>
          </tr>
          <tr>
            <th>{t("rep.th.registeredPublished")}</th>
            <td className="mono">
              {r.study.cases_registered} / {r.study.verdicts_published}
            </td>
          </tr>
          <tr>
            <th>{t("rep.th.verdictMix")}</th>
            <td>
              {Object.entries(r.study.verdict_mix).map(([v, n]) => (
                <span key={v} className={`badge v-${v}`} style={{ marginRight: 6 }} lang="en">
                  {v} {n}
                </span>
              ))}
            </td>
          </tr>
          <tr>
            <th>{t("rep.th.resourcesParsed")}</th>
            <td className="mono">{r.inventory.resources.length}</td>
          </tr>
        </tbody>
      </table>

      <h3>{t("rep.h.recommendations")}</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        {t("rep.recommendations.lede", { n: r.recommendations.length })}
      </p>
      <div className="scroll">
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 170 }}>{t("aud.th.control")}</th>
              <th>{t("rep.th.whatToDo")}</th>
              <th style={{ width: 180 }}>{t("rep.th.licensedBy")}</th>
              <th style={{ width: 170 }}>{t("rep.th.where")}</th>
            </tr>
          </thead>
          <tbody>
            {r.recommendations.map((x, n) => (
              <tr key={n}>
                <td>
                  <div className="mono">{x.control}</div>
                  <div style={{ color: "var(--fg-dim)", fontSize: 12 }} lang="en">
                    {x.label}
                  </div>
                  <div style={{ marginTop: 4 }}>
                    <ObsBadge o={x.observation} />
                  </div>
                </td>
                <td>
                  <div style={{ whiteSpace: "pre-wrap" }} lang="en">
                    {x.recommendation.trim()}
                  </div>
                  <div
                    style={{ color: "var(--fg-dim)", fontSize: 12, marginTop: 6, whiteSpace: "pre-wrap" }}
                    lang="en"
                  >
                    {x.because.trim()}
                  </div>
                  {x.scope_note ? (
                    <div style={{ color: "var(--warn)", fontSize: 12, marginTop: 6 }}>
                      {t("rep.scope")} <span lang="en">{x.scope_note.trim()}</span>
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
                <td className="mono" lang="en" style={{ fontSize: 11.5, wordBreak: "break-all" }}>
                  {x.sites.join(" ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>{t("rep.h.withheld")}</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        {t("rep.withheld.lede", { n: r.recommendations_withheld.length })}
      </p>
      <table className="grid">
        <thead>
          <tr>
            <th style={{ width: 190 }}>{t("aud.th.control")}</th>
            <th style={{ width: 170 }}>{t("pip.th.state")}</th>
            <th>{t("rep.th.whyWithheld")}</th>
          </tr>
        </thead>
        <tbody>
          {r.recommendations_withheld.map((w, n) => (
            <tr key={n}>
              <td className="mono">{w.control}</td>
              <td>
                <StatusBadge s={w.status} />
              </td>
              <td style={{ whiteSpace: "pre-wrap" }} lang="en">
                {w.why_withheld.trim()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>{t("rep.h.controlByControl")}</h3>
      {r.controls.map((line) => (
        <ControlBlock key={line.control} line={line} />
      ))}

      <h3>{t("rep.h.caveats")}</h3>
      <ul lang="en">
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
  // The read failure is held as a `Msg` — a key plus the reader's own value — not as a sentence, so it
  // is rendered in whichever language is on screen when it is shown, not the one that was on screen when
  // the file was picked.
  const [readError, setReadError] = useState<Msg | null>(null);
  const t = useT();

  const shown = useMemo(
    () => (own ? own.report : res.state === "ok" ? res.data.report : null),
    [own, res],
  );

  if (res.state === "loading") return <Loading what={t("rep.loading")} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const a: AuditPage = res.data;

  return (
    <>
      <h2>{t("rep.title")}</h2>
      <VerbatimNote />
      <p className="lede">
        {own ? (
          <T k="rep.lede.own" v={{ name: <span className="mono">{own.name}</span> }} />
        ) : (
          <T
            k="rep.lede.example"
            v={{
              parse: <span className="mono">{a.tools.parse}</span>,
              report: <span className="mono">{a.tools.report}</span>,
              submission: <span className="mono">{a.example.submission}</span>,
              intake: <Link to="/audit">{t("rep.intakeLink")}</Link>,
              n: a.example.n_files,
            }}
          />
        )}
      </p>

      {!own && a.example.is_synthetic ? (
        <div className="note warn">
          <strong>{t("rep.synthetic")}</strong>{" "}
          <span style={{ whiteSpace: "pre-wrap" }} lang="en">
            {a.example.why_synthetic.trim()}
          </span>
        </div>
      ) : null}

      <h3>{t("rep.h.ownReport")}</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        <T
          k="rep.ownReport.body"
          v={{
            intake: <Link to="/audit">{t("rep.intakeLink")}</Link>,
            report: <span className="mono">report.json</span>,
            reader: <span className="mono">FileReader</span>,
          }}
        />
      </p>
      <div className="intake">
        <label>
          <span>{t("rep.field.file")}</span>
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
                (err) => setReadError({ key: "rep.readFailed", vars: { why: String(err) } }),
              );
            }}
          />
        </label>
        {own ? (
          <button type="button" className="btn" onClick={() => setOwn(null)}>
            {t("rep.backToExample")}
          </button>
        ) : null}
      </div>
      {readError ? (
        <div className="note warn">{t(readError.key, readError.vars)}</div>
      ) : null}

      {!own ? (
        <p>
          <Download
            name="grx-audit-example.md"
            text={a.markdown}
            type="text/markdown"
            label={t("rep.dl.md")}
          />{" "}
          <Download
            name="grx-audit-example.json"
            text={JSON.stringify(a.report, null, 2)}
            type="application/json"
            label={t("rep.dl.json")}
          />{" "}
          <Download
            name="grx-audit-example-inventory.json"
            text={JSON.stringify(a.inventory, null, 2)}
            type="application/json"
            label={t("rep.dl.inventory")}
          />
        </p>
      ) : null}

      {shown ? <ReportBody r={shown} /> : null}

      {!own ? (
        <>
          <h3>{t("rep.h.markdown")}</h3>
          <p style={{ color: "var(--fg-dim)" }}>{t("rep.markdown.body")}</p>
          <details className="raw">
            <summary>{t("rep.markdown.lines", { n: a.markdown.split("\n").length })}</summary>
            <div>
              {/* The report as the audit emitted it. English verbatim in both editions — a reader
                  pastes these bytes into a repository, so a translated word would be a defect. */}
              <pre lang="en">
                <code>{a.markdown}</code>
              </pre>
            </div>
          </details>
        </>
      ) : null}

      <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 16 }} lang="en">
        {a.note}
      </p>
    </>
  );
}
