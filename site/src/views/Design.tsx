// The recommended design — and, beside every sentence of it, what this study measured about it.
//
// WHY THIS PAGE EXISTS SEPARATELY FROM /architecture
//
// `/architecture` answers "what did the study look at". This page answers "what does the guidance
// recommend, and did it hold". Those are different questions, and putting the closed-loop picture on the
// evidence page would have read as a claim that the recommended design is the thing that was tested. It
// is not: the design is a document, the evidence is 93 cases, and the join between them is the subject
// here rather than the background.
//
// WHY EVERY SENTENCE ON THIS PAGE IS QUOTED FROM A FILE THIS REPOSITORY DOES NOT WRITE
//
// The claim the page makes is that the design was MEASURED on this platform rather than asserted. A
// practice sentence retyped into `strings.ts` would break that claim in both directions at once: the
// page would keep showing the old wording after the document was amended, and a citation typed beside
// it would be this platform vouching for a link the document never made. So `practices_source.py`
// parses both editions — sentence, phase, hop, checklist, and all 324 case references — and
// `practices.json` carries each document's sha256 as an input. The Chinese half of every practice is
// the Chinese DOCUMENT's own wording, which is why the two editions are extracted separately and
// asserted to carry the identical citation multiset.
//
// WHAT THE COLOURS MEAN HERE, AND WHY `not_measured` IS LOUD
//
// The five statuses and their precedence are `build_site_data.box_status()`, shared with the diagram and
// with `check_architecture.py`: one citable FALSE outranks any number of TRUEs, because a practice with
// four confirmations and one finding is a practice with a finding. The status a normal architecture page
// lacks is `not_measured` — a practice this study never tested — and it is deliberately not rendered as
// clean. Nine of the forty-five rest on nothing this study measured, and the page says so on each one
// rather than in a footnote.
//
// WHAT IS DELIBERATELY NOT RENDERED
//
// The adjudicator's reasoning on each contested citation — the `why`, the `reason`, the machine locator
// in `evidence` — is not on this page. It is English judgement prose over file paths and per-metric
// expressions, and rendering it would put a dozen untranslated paragraphs in front of a Chinese reader
// on the one page whose whole subject is that both editions say the same thing. It lives in
// `results/PRACTICE-EVIDENCE-MAP.md`, named below, and what the page does render is the identifier, the
// ruling, the register item, and the span the document itself wrote — in the reader's own language.

import { Fragment, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { loadArchitecture, loadPractices } from "../lib/data";
import { statusClass } from "../lib/audit";
import ArchDiagram from "../components/ArchDiagram";
import { ErrorPanel, Loading, useAsync, VerdictBadge } from "../components/ui";
import { A, T, useAuthored, useT, VerbatimNote } from "../lib/i18n";
import type { Practice, PracticeCase, PracticeRuling, Practices } from "../lib/types";

/** Which of the payload's diagrams belong to this page — the same `view` filter `/architecture` uses,
 *  for the same reason: a page that named its diagrams would silently gain the next one added, and
 *  `check_architecture.py` fails the build on a view no diagram declares. */
const VIEW = "design";

/** The status token beside a practice or a checkpoint, with the sentence that says what the colour
 *  means. The token stays English in both languages — it is payload vocabulary a reader greps for, like
 *  `not_established` in the diagram legend — and the sentence beside it is the build's own prose.
 *  `label` is what `status_labels[status]` yields, so it admits undefined: a status the vocabulary does
 *  not name renders its token and no sentence, the same shape a missing basis gets on the card. */
function StatusLine({ status, label }: { status: string; label?: { en: string; zh: string } }) {
  return (
    <span className="desstatus">
      <span className={`badge ${statusClass(status)}`} lang="en">
        {status.replace(/_/g, " ")}
      </span>{" "}
      {label ? <A v={label} className="means" /> : null}
    </span>
  );
}

/** The evidence under one practice: the register's verdict, and what the document claims it decided.
 *
 *  Both are shown because they are two sources and `check_practices.py` is what holds them together — a
 *  page that printed only the register's verdict would be asking the reader to trust that the document
 *  agrees, which is precisely the thing the gate exists to check. Where the document names no verdict in
 *  its citation bracket the row says so rather than leaving the column blank; a blank reads as agreement. */
function Evidence({ cases, asserted }: { cases: PracticeCase[]; asserted: Practice["asserted"] }) {
  const t = useT();
  const says = new Map(asserted.map((a) => [a.case, a.asserted]));
  if (!cases.length) return null;
  return (
    <ul className="descases">
      {cases.map((c) => (
        <li key={c.case}>
          <Link to={`/case/${c.case}`} className="mono">
            {c.case}
          </Link>{" "}
          <VerdictBadge v={c.verdict} />
          {says.has(c.case) ? (
            <span className="desasserted">
              {says.get(c.case) ? (
                <>
                  {t("des.docSays")} <span className="mono">{says.get(c.case)}</span>
                </>
              ) : (
                t("des.docSaysNothing")
              )}
            </span>
          ) : null}
          <span className="destitle" lang="en">
            {c.title}
          </span>
          {c.restrictions.map((r) => (
            <span key={r} className="chip blocked">
              {r}
            </span>
          ))}
        </li>
      ))}
    </ul>
  );
}

function PracticeCard({ p, doc }: { p: Practice; doc: Practices }) {
  const t = useT();
  const authored = useAuthored();
  const prose = authored(p.prose);
  const why = authored(p.why_this_status);
  const basis = doc.status_bases[p.status_basis];
  // The basis the colour rests on, resolved from the payload's own vocabulary rather than from a table
  // here: `practice`, `section` and `none` are three different strengths of claim, and flattening them
  // into one colour would make a sentence that inherits its checkpoint's evidence look like one that
  // was tested directly.
  const evidence = p.status_basis === "section" ? doc.sections.find((s) => s.id === p.section)?.cases : p.cases;
  return (
    <article className={`descard ${statusClass(p.status)}`} id={`p-${p.key}`}>
      <div className="deshead">
        <span className="mono deskey">{p.key}</span>
        <StatusLine status={p.status} label={doc.status_labels[p.status]} />
      </div>
      <p className="desprose" lang={prose.lang}>
        {prose.text.trim()}
      </p>
      {p.status_basis === "none" ? (
        <p className="deswhy">{t("des.noEvidence")}</p>
      ) : (
        <>
          <p className="deswhy">
            <strong>{t("des.basis")}</strong> {basis ? <A v={basis} /> : null}
          </p>
          <p className="deswhy">
            <strong>{t("arc.whyColour")}</strong> <span lang={why.lang}>{why.text}</span>
          </p>
          <Evidence cases={evidence ?? []} asserted={p.asserted} />
        </>
      )}
    </article>
  );
}

function Rulings({ rows }: { rows: PracticeRuling[] }) {
  const t = useT();
  const authored = useAuthored();
  if (!rows.length) return null;
  return (
    <table className="grid desrulings">
      <thead>
        <tr>
          <th style={{ width: 78 }}>{t("pip.th.case")}</th>
          <th style={{ width: 64 }}>{t("des.th.where")}</th>
          <th style={{ width: 150 }}>{t("des.th.disposition")}</th>
          <th style={{ width: 96 }}>{t("des.th.item")}</th>
          <th>{t("des.th.quoted")}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const quoted = authored(r.quoted);
          return (
            <tr key={`${r.case}-${r.where}-${i}`}>
              <td>
                <Link to={`/case/${r.case}`} className="mono">
                  {r.case}
                </Link>
              </td>
              <td className="mono">§{r.where}</td>
              <td>
                <span className="chip" lang="en">
                  {r.disposition}
                </span>
                {r.restriction ? (
                  <span className="chip blocked" lang="en">
                    {r.restriction}
                  </span>
                ) : null}
              </td>
              <td>
                {r.register_item !== null ? (
                  <Link to="/register" className="mono">
                    {t("reg.item", { n: r.register_item })}
                  </Link>
                ) : r.blocked_on ? (
                  <span className="desblocked">{t("des.ruling.blocked")}</span>
                ) : null}
              </td>
              <td>
                <span className="desquote" lang={quoted.lang}>
                  {quoted.text.trim()}
                </span>
                <span className="desasserted">
                  {t("des.docSays")} <span className="mono">{r.asserted}</span> · {t("des.registerSays")}{" "}
                  <VerdictBadge v={r.on_disk} />
                </span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default function DesignView() {
  const res = useAsync(loadPractices, []);
  const arch = useAsync(loadArchitecture, []);
  const t = useT();
  const authored = useAuthored();
  const { hash } = useLocation();
  const ready = res.state === "ok" && arch.state === "ok";
  // The diagram panel on `/architecture` links here as `/design#s-<section>`, and HashRouter delivers
  // that fragment as `location.hash` without scrolling to it — the browser's own anchor behaviour is
  // keyed to the URL's first `#`, which the router owns. The jump also cannot happen before the data
  // arrives, because the anchor element does not exist until the sections render; hence `ready` in the
  // dependencies rather than an effect that fires once into an empty page.
  useEffect(() => {
    if (!ready || !hash) return;
    document.getElementById(hash.slice(1))?.scrollIntoView();
  }, [ready, hash]);
  if (res.state === "loading" || arch.state === "loading") return <Loading what={t("des.loading")} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  if (arch.state === "error") return <ErrorPanel error={arch.error} />;
  const doc = res.data;
  const architecture = arch.data;
  const byKey = new Map(doc.practices.map((p) => [p.key, p]));

  return (
    <>
      <h2>{t("nav.design")}</h2>
      <VerbatimNote />
      <p className="lede">
        <T
          k="des.lede"
          v={{
            n: doc.n_practices,
            sections: doc.sections.length,
            doc: <span className="mono">{doc.documents.en.path}</span>,
          }}
        />
      </p>

      {/* The closed loop, drawn by the same renderer as the evidence page's two diagrams. Its boxes are
          coloured by the cases of the checkpoint each one names, so a hop that reads amber here is a hop
          whose recommended practices are the amber ones below. */}
      {architecture.diagrams
        .filter((d) => d.view === VIEW)
        .map((d) => (
          <ArchDiagram key={d.id} d={d} arch={architecture} />
        ))}

      <h3>{t("des.h.coverage")}</h3>
      <p>
        {t("des.cov.basis", {
          practice: doc.coverage.by_status_basis.practice ?? 0,
          section: doc.coverage.by_status_basis.section ?? 0,
          none: doc.coverage.by_status_basis.none ?? 0,
        })}{" "}
        {t("des.cov.cases", {
          cited: doc.coverage.n_cited,
          registered: doc.coverage.n_registered,
          uncited: doc.coverage.n_uncited,
        })}{" "}
        <A v={doc.coverage.why} />
      </p>
      <p style={{ color: "var(--fg-dim)" }}>
        <A v={doc.documents.why} />{" "}
        <span className="mono">{doc.documents.zh.path}</span>{" "}
        <span className="mono">{doc.documents.zh.sha256.slice(0, 12)}</span>
      </p>

      <h3>{t("des.h.practices")}</h3>
      {doc.phases.map((phase) => {
        const sections = doc.sections.filter((s) => s.phase === phase);
        if (!sections.length) return null;
        return (
          <div key={phase} className="desphase">
            <h4>
              <T
                k="des.phase.head"
                v={{
                  phase: (
                    <span className="mono" lang="en">
                      {phase}
                    </span>
                  ),
                  sections: sections.length,
                  practices: sections.reduce((n, s) => n + s.n_practices, 0),
                }}
              />
            </h4>
            {sections.map((s) => {
              const heading = authored(s.heading);
              const why = authored(s.why_this_status);
              return (
                <section key={s.id} className="dessec" id={`s-${s.id}`}>
                  <h5>
                    <span className="mono">§{s.id}</span>{" "}
                    <span lang={heading.lang}>{heading.text.trim()}</span>
                  </h5>
                  <p className="deswhy">
                    <StatusLine status={s.status} label={doc.status_labels[s.status]} />
                  </p>
                  <p className="deswhy">
                    <strong>{t("arc.whyColour")}</strong> <span lang={why.lang}>{why.text}</span>
                  </p>
                  {s.hop ? <p className="deshop">{t("des.hop", { hop: s.hop })}</p> : null}
                  {s.keys.map((k) => {
                    const p = byKey.get(k);
                    return p ? <PracticeCard key={k} p={p} doc={doc} /> : null;
                  })}
                </section>
              );
            })}
          </div>
        );
      })}

      <h3>{t("des.h.principles")}</h3>
      <ol className="desprinciples">
        {doc.principles.map((pr) => {
          const head = authored(pr.principle);
          const why = authored(pr.rationale);
          return (
            <li key={pr.n}>
              <span lang={head.lang}>{head.text.trim()}</span>
              <p lang={why.lang}>{why.text.trim()}</p>
              {pr.cites.length ? (
                <p className="descites">
                  {pr.cites.map((c) => (
                    <Fragment key={c}>
                      <Link to={`/case/${c}`} className="mono">
                        {c}
                      </Link>{" "}
                    </Fragment>
                  ))}
                </p>
              ) : null}
            </li>
          );
        })}
      </ol>

      <h3>{t("des.h.antipatterns")}</h3>
      <ol className="desantipatterns">
        {doc.anti_patterns.map((ap) => {
          const head = authored(ap.anti_pattern);
          const problem = authored(ap.problem);
          const rec = authored(ap.recommendation);
          return (
            <li key={ap.n}>
              <span lang={head.lang}>{head.text.trim()}</span>
              <p>
                <strong>{t("des.ap.problem")}</strong>{" "}
                <span lang={problem.lang}>{problem.text.trim()}</span>
              </p>
              <p>
                <strong>{t("des.ap.rec")}</strong> <span lang={rec.lang}>{rec.text.trim()}</span>
              </p>
              {ap.cites.length ? (
                <p className="descites">
                  {ap.cites.map((c) => (
                    <Fragment key={c}>
                      <Link to={`/case/${c}`} className="mono">
                        {c}
                      </Link>{" "}
                    </Fragment>
                  ))}
                </p>
              ) : null}
            </li>
          );
        })}
      </ol>

      <h3>
        {t("des.h.checklist")} <span className="mono">{doc.n_checklist_items}</span>
      </h3>
      {doc.checklist.map((g, gi) => {
        const label = authored(g.label);
        return (
          <section key={gi} className="deschecklist">
            <h5 lang={label.lang}>{label.text.trim()}</h5>
            <ul>
              {g.items.map((item, ii) => {
                const prose = authored(item.prose);
                const raw = authored(item.raw);
                return (
                  <li key={ii}>
                    <span lang={prose.lang}>{prose.text.trim()}</span>
                    {item.cites.length ? (
                      <span className="descites">
                        {item.cites.map((c) => (
                          <Fragment key={c}>
                            <Link to={`/case/${c}`} className="mono">
                              {c}
                            </Link>{" "}
                          </Fragment>
                        ))}
                      </span>
                    ) : null}
                    {/* The item as the document writes it, brackets and all. The brackets carry the n,
                        the region and the date, so a checklist stripped of them reads as an instruction
                        with no evidence behind it — but they also make the list unreadable at a glance,
                        which is why the stripped form is what shows and this is one click away. */}
                    {raw.text.trim() !== prose.text.trim() ? (
                      <details>
                        <summary>{t("des.checklist.raw")}</summary>
                        <p lang={raw.lang}>{raw.text.trim()}</p>
                      </details>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}

      <h3>{t("des.h.census")}</h3>
      <p>
        {t("des.census.body", {
          assertions: doc.citation_census.n_citations,
          distinct: doc.citation_census.n_distinct,
          inline: doc.citation_census.n_inside_a_practice,
          carrying: doc.citation_census.n_practices_carrying_one,
        })}{" "}
        <A v={doc.citation_census.why_two_numbers} />
      </p>

      <h3>{t("des.h.rulings")}</h3>
      <p>
        <T
          k="des.rulings.body"
          v={{
            needing: doc.adjudications.n_assertions_needing_a_ruling,
            policy: <span className="mono">results/CITATION-POLICY.md</span>,
            legal: doc.adjudications.n_legal,
            open: doc.adjudications.n_open,
            ceiling: doc.adjudications.ceiling,
            map: <span className="mono">results/PRACTICE-EVIDENCE-MAP.md</span>,
          }}
        />
      </p>
      <p style={{ color: "var(--fg-dim)" }}>
        <A v={doc.adjudications.why} />{" "}
        <T
          k="des.rulings.adjudicated"
          v={{
            when: <span className="mono">{doc.adjudications.adjudicated_on}</span>,
            file: <span className="mono">{doc.adjudications.curation.path}</span>,
            sha: <span className="mono">{doc.adjudications.curation.sha256.slice(0, 12)}</span>,
          }}
        />
      </p>
      <Rulings rows={[...doc.adjudications.open, ...doc.adjudications.legal]} />

      <h3>{t("des.h.uncited")}</h3>
      <p>{t("des.uncited.body", { n: doc.coverage.n_uncited })}</p>
      <ul className="descases">
        {doc.coverage.uncited_cases.map((c) => (
          <li key={c.case}>
            <Link to={`/case/${c.case}`} className="mono">
              {c.case}
            </Link>{" "}
            <VerdictBadge v={c.verdict} />
            <span className="destitle" lang="en">
              {c.title}
            </span>
            {c.restrictions.map((r) => (
              <span key={r} className="chip blocked">
                {r}
              </span>
            ))}
          </li>
        ))}
      </ul>
    </>
  );
}
