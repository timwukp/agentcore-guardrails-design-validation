// View 9 — the test pipeline's actual state: what this platform has observed, and when.
//
// WHAT THIS PAGE IS NOT
//
// It is not a progress bar. A family is a set of cases, not a job with a fraction done, and any
// denominator over a set that contains "never observed" yields a number that reads as progress and is
// not one. There is no percentage and no completion figure anywhere below — the states are the answer,
// and three of the six can never be cleared by running anything.
//
// It is also not live in the sense of a running job: `pipeline.json` is derived at build time from the
// verdict records, the archive, and the authored cadences. Every age on this page is measured from the
// payload's `as_of_utc_day`, which is the day the build was stamped and NOT necessarily today —
// `--stamp` is caller supplied, and a back-dated rebuild is legitimate. Rendering ages against the
// reader's clock instead would silently re-date every observation each time the tab was opened.
//
// THE STATE THAT MATTERS MOST IS THE ABSENT ONE
//
// A schedule that quietly stops looks identical to one that is current, unless staleness is a
// first-class state with a cadence behind it. So STALE and NOT OBSERVED render as loudly as anything
// else here, and the three states that no schedule can clear — CALENDAR GATED, HUMAN DECISION REQUIRED,
// REQUIRES A LOCAL RUN — are deliberately NOT rendered as staleness. Staleness is pressure toward a
// run; for those three the run it would pressure somebody into is the wrong act, and for F6 it is one
// that would invalidate the comparison it appears to refresh.
//
// DISAGREEMENT IS A FINDING, NOT A FAILURE OF THE PAGE
//
// Four cases have an archived verdict that differs from the live one. That is the most valuable row on
// this screen and it is placed first, above the family table: a platform that could only show agreement
// would be a platform whose replication machinery had never been tested.

import { useState } from "react";
import { Link } from "react-router-dom";
import { loadPipeline } from "../lib/data";
import { T, useT, VerbatimNote } from "../lib/i18n";
import { ErrorPanel, Loading, useAsync } from "../components/ui";
import type { PipelineCase, PipelineFamily, PipelineState } from "../lib/types";

/** `WITHIN CADENCE` -> `s-within-cadence`. Derived rather than mapped: a table of state -> class would
 *  silently drop the styling of a state added to the vocabulary later, and an unstyled badge reads as
 *  a state with nothing wrong. */
const stateClass = (s: string) => `s-${s.toLowerCase().replace(/\s+/g, "-")}`;

/** The state words are the payload's own closed vocabulary, keyed on in `families.yaml` and in the
 *  gate. They stay in English, like the verdict tokens: a reader who greps `pipeline.json` for
 *  `REQUIRES A LOCAL RUN` must find the same string this badge shows. What the states MEAN is
 *  translated — in the family rows and the cards below, which are this platform's own prose. */
function StateBadge({ s }: { s: PipelineState | string }) {
  return (
    <span className={`badge ${stateClass(s)}`} lang="en">
      {s}
    </span>
  );
}

function CaseLinks({ ids }: { ids: string[] }) {
  if (!ids.length) return <span style={{ color: "var(--fg-faint)" }}>—</span>;
  return (
    <>
      {ids.map((id) => (
        <Link key={id} to={`/case/${id}`} className="chip" style={{ marginRight: 4 }}>
          {id}
        </Link>
      ))}
    </>
  );
}

function FamilyRow({ fam, open, onToggle }: { fam: PipelineFamily; open: boolean; onToggle: () => void }) {
  const t = useT();
  return (
    <>
      <tr onClick={onToggle} style={{ cursor: "pointer" }}>
        <td className="mono">{fam.family}</td>
        <td lang="en">{fam.label}</td>
        <td>
          <StateBadge s={fam.state} />
        </td>
        <td className="num">{fam.cadence_days ?? "—"}</td>
        <td className="mono">{fam.last_observed_utc_day ?? t("pip.never")}</td>
        <td className="num">{fam.days_since_last_observation ?? "—"}</td>
        <td className="num">{fam.n_cases}</td>
        <td className="num">{fam.n_with_verdict}</td>
        <td className="num">{fam.n_with_no_observed_day}</td>
        <td className="num">{fam.n_with_two_or_more_archived_days}</td>
        <td className="num">{fam.cases_in_disagreement.length}</td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={11} style={{ background: "var(--bg-inset)" }}>
            <div style={{ padding: "4px 2px 10px" }}>
              {/* `statement`, `why_not_schedulable`, `replication_requirement` and `why_cadence` are
                  the authored cadence file's own sentences, quoted. They are the material this page
                  reports on, so they render verbatim; the labels around them are ours. */}
              <p style={{ margin: "6px 0" }} lang="en">
                {fam.statement}
              </p>
              {fam.schedulable ? null : (
                <div className="note warn">
                  <div>{t("pip.notSchedulable")}</div>
                  {fam.why_not_schedulable ? (
                    <div style={{ marginTop: 6, whiteSpace: "pre-wrap" }} lang="en">
                      {fam.why_not_schedulable.trim()}
                    </div>
                  ) : null}
                </div>
              )}
              {fam.network_position_sensitive && fam.replication_requirement ? (
                <div className="note warn">
                  <strong>{t("pip.replReq")}</strong>
                  <div style={{ marginTop: 6, whiteSpace: "pre-wrap" }} lang="en">
                    {fam.replication_requirement.trim()}
                  </div>
                </div>
              ) : null}
              {fam.why_cadence ? (
                <p style={{ color: "var(--fg-dim)", whiteSpace: "pre-wrap", margin: "6px 0" }}>
                  <strong>{t("pip.whyCadence")}</strong>{" "}
                  <span lang="en">{fam.why_cadence.trim()}</span>
                </p>
              ) : null}
              <table className="grid" style={{ marginTop: 6 }}>
                <tbody>
                  <tr>
                    <th style={{ width: 260 }}>{t("pip.th.disagreement")}</th>
                    <td>
                      <CaseLinks ids={fam.cases_in_disagreement} />
                    </td>
                  </tr>
                  <tr>
                    <th>{t("pip.th.owesSecond")}</th>
                    <td>
                      <CaseLinks ids={fam.cases_owing_a_second_day} />
                    </td>
                  </tr>
                  <tr>
                    <th>{t("pip.th.dayUnknown")}</th>
                    <td>
                      <CaseLinks ids={fam.cases_whose_observation_day_is_unknown} />
                    </td>
                  </tr>
                  <tr>
                    <th>{t("pip.th.noDay")}</th>
                    <td>
                      <CaseLinks ids={fam.cases_with_no_observed_day} />
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

export default function Pipeline() {
  const res = useAsync(loadPipeline, []);
  const [open, setOpen] = useState<string | null>(null);
  const t = useT();

  if (res.state === "loading") return <Loading what={t("pip.loading")} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const p = res.data;

  const families = Object.values(p.families).sort((a, b) => a.family.localeCompare(b.family));
  // Counts per state, over the closed vocabulary the payload declares — not over the states that happen
  // to occur, so a state with zero families is visible as zero rather than absent.
  const perState = p.states.map((s) => [s, families.filter((f) => f.state === s).length] as const);
  const disagreeing = Object.values(p.cases).filter((c) => c.replication === "disagreeing");

  return (
    <>
      <h2>{t("nav.pipeline")}</h2>
      <VerbatimNote />
      <p className="lede">
        <T k="pip.lede" v={{ day: <span className="mono">{p.as_of_utc_day}</span> }} />{" "}
        <span lang="en">{p.as_of_note}</span>
      </p>

      {p.as_of_precedes_some_observations.length ? (
        <div className="note warn">
          <T
            k="pip.asOfWarn"
            v={{
              n: p.as_of_precedes_some_observations.length,
              cases: (
                <span className="mono">{p.as_of_precedes_some_observations.join(", ")}</span>
              ),
            }}
          />
        </div>
      ) : null}

      <div className="cards" style={{ marginTop: 14 }}>
        {perState.map(([s, n]) => (
          <div className="card" key={s}>
            <div className="n">{n}</div>
            <div className="k">
              <StateBadge s={s} />
            </div>
          </div>
        ))}
      </div>

      <h3>{t("pip.h.disagree")}</h3>
      <p>{t("pip.disagree.body", { n: disagreeing.length, total: p.totals.n_cases })}</p>
      <table className="grid">
        <thead>
          <tr>
            <th>{t("pip.th.case")}</th>
            <th>{t("pip.th.archivedDays")}</th>
            <th>{t("pip.th.archivedVerdicts")}</th>
          </tr>
        </thead>
        <tbody>
          {disagreeing.map((c: PipelineCase) => (
            <tr key={c.case}>
              <td>
                <Link to={`/case/${c.case}`} className="mono">
                  {c.case}
                </Link>
              </td>
              <td className="mono">{c.days_from_the_archive.join(", ") || "—"}</td>
              <td>
                {c.disagreements.map((d) => (
                  <div key={d.file}>
                    <span className="badge v-none" lang="en">
                      {d.verdict}
                    </span>{" "}
                    <span className="mono" style={{ fontSize: 11.5 }}>
                      {d.label}
                    </span>
                  </div>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>{t("pip.h.byFamily")}</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        <T
          k="pip.byFamily.note"
          v={{
            file: (
              <span className="mono">
                {families.find((f) => f.source)?.source ?? t("pip.byFamily.unstated")}
              </span>
            ),
          }}
        />
      </p>
      <div className="scroll">
        <table className="grid">
          <thead>
            <tr>
              <th>{t("pip.th.family")}</th>
              <th>{t("pip.th.measures")}</th>
              <th>{t("pip.th.state")}</th>
              <th>{t("pip.th.cadence")}</th>
              <th>{t("pip.th.lastObserved")}</th>
              <th>{t("pip.th.age")}</th>
              <th>{t("pip.th.cases")}</th>
              <th>{t("pip.th.withVerdict")}</th>
              <th>{t("pip.th.noObservedDay")}</th>
              <th>{t("pip.th.twoArchived")}</th>
              <th>{t("pip.th.disagreeing")}</th>
            </tr>
          </thead>
          <tbody>
            {families.map((f) => (
              <FamilyRow
                key={f.family}
                fam={f}
                open={open === f.family}
                onToggle={() => setOpen(open === f.family ? null : f.family)}
              />
            ))}
          </tbody>
        </table>
      </div>

      <h3>{t("pip.h.replCounts")}</h3>
      <div className="cards">
        <div className="card">
          <div className="n">{p.totals.n_with_two_or_more_archived_days}</div>
          <div className="k">{t("pip.card.twoArchived")}</div>
          <div className="def">{t("pip.card.twoArchived.def")}</div>
        </div>
        <div className="card">
          <div className="n">{p.totals.n_one_archived_prior_day}</div>
          <div className="k">{t("pip.card.oneArchived")}</div>
        </div>
        <div className="card">
          <div className="n">{p.totals.n_no_archived_prior_day}</div>
          <div className="k">{t("pip.card.noArchived")}</div>
          <div className="def">{t("pip.card.noArchived.def")}</div>
        </div>
        <div className="card">
          <div className="n">{p.totals.n_with_no_observed_day}</div>
          <div className="k">{t("pip.card.noObservedDay")}</div>
          <div className="def">{t("pip.card.noObservedDay.def")}</div>
        </div>
      </div>
      <div className="note" style={{ marginTop: 12 }} lang="en">
        {p.totals.why_replication_is_counted_from_the_archive_only}
      </div>
      <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 10 }} lang="en">
        {p.note}
      </p>
    </>
  );
}
