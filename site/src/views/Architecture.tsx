// The design diagrams page: how a verdict is made, and what the study looked at.
//
// The renderer itself is `components/ArchDiagram.tsx` — geometry, colours, legend and panel — because
// `/design` draws the closed-loop picture out of the same payload and a second renderer would drift
// from this one silently. What this page owns is WHICH diagrams belong here, and the coverage and
// metric tables that are about the study rather than about any one picture.

import { Link } from "react-router-dom";
import { loadArchitecture } from "../lib/data";
import ArchDiagram from "../components/ArchDiagram";
import { ErrorPanel, Loading, useAsync, VerdictBadge } from "../components/ui";
import { T, useT, VerbatimNote } from "../lib/i18n";

/** Which of the payload's diagrams belong to this page. The vocabulary is authored in
 *  `platform/curation/architecture.yaml` and checked there, so a value that no diagram declares fails
 *  the build rather than rendering a page with nothing on it. */
const VIEW = "architecture";


export default function ArchitectureView() {
  const res = useAsync(loadArchitecture, []);
  const t = useT();
  if (res.state === "loading") return <Loading what={t("arc.loading")} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const arch = res.data;

  return (
    <>
      <h2>{t("nav.architecture")}</h2>
      <VerbatimNote />
      <p className="lede">
        <T
          k="arc.lede"
          v={{ file: <span className="mono">platform/curation/architecture.yaml</span> }}
        />
      </p>

      {/* Filtered on the payload's own `view` key, not on a list of diagram ids kept here. The
          closed-loop picture is the recommended DESIGN; this page is what the study measured, and the
          two answer different questions — drawing the design here beside "what the study looked at"
          would read as a claim that the design is what was tested. A page that named the diagrams it
          draws would silently gain the next one added; a page that filters on the property gains
          nothing it did not ask for, and `check_architecture.py` fails the build on a view no diagram
          uses, so a typo here cannot quietly empty the page. */}
      {arch.diagrams
        .filter((d) => d.view === VIEW)
        .map((d) => (
          <ArchDiagram key={d.id} d={d} arch={arch} />
        ))}

      <h3>{t("arc.h.coverage")}</h3>
      <p>
        {t("arc.coverage", {
          placed: arch.coverage.n_placed,
          registered: arch.coverage.n_registered,
          unplaced: arch.coverage.n_unplaced,
        })}{" "}
        <span lang="en">{arch.coverage.why}</span>
      </p>
      {arch.unplaced_cases.length ? (
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 78 }}>{t("pip.th.case")}</th>
              <th style={{ width: 108 }}>{t("arc.th.verdict")}</th>
              <th>{t("arc.th.whyUnplaced")}</th>
            </tr>
          </thead>
          <tbody>
            {arch.unplaced_cases.map((c) => (
              <tr key={c.case}>
                <td>
                  <Link to={`/case/${c.case}`} className="mono">
                    {c.case}
                  </Link>
                </td>
                <td>
                  {/* Same mark as the register, the case page and the design page: this row is an
                      unplaced case, and a bare token here would be the one verdict chip on the site
                      whose silence about an undecided sub-question meant nothing. */}
                  <VerdictBadge v={c.verdict} undecided={c.undecided} />
                  {c.restrictions.map((r) => (
                    <span key={r} className="chip blocked" style={{ marginLeft: 4 }}>
                      {r}
                    </span>
                  ))}
                </td>
                <td style={{ whiteSpace: "pre-wrap" }} lang="en">
                  {c.why.trim()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <h3>{t("arc.h.metrics")}</h3>
      <p style={{ color: "var(--fg-dim)" }}>{t("arc.metrics.body")}</p>
      <table className="grid archmetrics">
        <tbody>
          {Object.entries(arch.metrics)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([k, n]) => (
              <tr key={k}>
                <th className="mono" style={{ width: 340 }}>
                  {k}
                </th>
                <td className="num">{n}</td>
              </tr>
            ))}
        </tbody>
      </table>

      <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 14 }}>
        <T
          k="arc.mappedBy"
          v={{
            // `mapped_by` is a self-description the curation file authored ("the maintainer of this
            // repository"), not a name this SPA can translate, so it is quoted like any other field.
            who: <span lang="en">{arch.mapped_by}</span>,
            when: <span className="mono">{arch.mapped_on}</span>,
          }}
        />{" "}
        <span lang="en">{arch.note}</span>
      </p>
    </>
  );
}
