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
import { ErrorPanel, Loading, useAsync } from "../components/ui";
import type { PipelineCase, PipelineFamily, PipelineState } from "../lib/types";

/** `WITHIN CADENCE` -> `s-within-cadence`. Derived rather than mapped: a table of state -> class would
 *  silently drop the styling of a state added to the vocabulary later, and an unstyled badge reads as
 *  a state with nothing wrong. */
const stateClass = (s: string) => `s-${s.toLowerCase().replace(/\s+/g, "-")}`;

function StateBadge({ s }: { s: PipelineState | string }) {
  return <span className={`badge ${stateClass(s)}`}>{s}</span>;
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
  return (
    <>
      <tr onClick={onToggle} style={{ cursor: "pointer" }}>
        <td className="mono">{fam.family}</td>
        <td>{fam.label}</td>
        <td>
          <StateBadge s={fam.state} />
        </td>
        <td className="num">{fam.cadence_days ?? "—"}</td>
        <td className="mono">{fam.last_observed_utc_day ?? "never"}</td>
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
              <p style={{ margin: "6px 0" }}>{fam.statement}</p>
              {fam.schedulable ? null : (
                <div className="note warn">
                  <div>
                    Not schedulable, so it carries no cadence and can never be reported stale — nothing
                    on this page should be read as pressure to re-run it.
                  </div>
                  {fam.why_not_schedulable ? (
                    <div style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>
                      {fam.why_not_schedulable.trim()}
                    </div>
                  ) : null}
                </div>
              )}
              {fam.network_position_sensitive && fam.replication_requirement ? (
                <div className="note warn">
                  <strong>What a replication of this family must hold fixed:</strong>
                  <div style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>
                    {fam.replication_requirement.trim()}
                  </div>
                </div>
              ) : null}
              {fam.why_cadence ? (
                <p style={{ color: "var(--fg-dim)", whiteSpace: "pre-wrap", margin: "6px 0" }}>
                  <strong>Why this cadence:</strong> {fam.why_cadence.trim()}
                </p>
              ) : null}
              <table className="grid" style={{ marginTop: 6 }}>
                <tbody>
                  <tr>
                    <th style={{ width: 260 }}>In disagreement with an archive</th>
                    <td>
                      <CaseLinks ids={fam.cases_in_disagreement} />
                    </td>
                  </tr>
                  <tr>
                    <th>Owes a second occasion (has a verdict, nothing archived)</th>
                    <td>
                      <CaseLinks ids={fam.cases_owing_a_second_day} />
                    </td>
                  </tr>
                  <tr>
                    <th>Observation day not derivable from the record</th>
                    <td>
                      <CaseLinks ids={fam.cases_whose_observation_day_is_unknown} />
                    </td>
                  </tr>
                  <tr>
                    <th>No observed day at all</th>
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

  if (res.state === "loading") return <Loading what="the pipeline state" />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const p = res.data;

  const families = Object.values(p.families).sort((a, b) => a.family.localeCompare(b.family));
  // Counts per state, over the closed vocabulary the payload declares — not over the states that happen
  // to occur, so a state with zero families is visible as zero rather than absent.
  const perState = p.states.map((s) => [s, families.filter((f) => f.state === s).length] as const);
  const disagreeing = Object.values(p.cases).filter((c) => c.replication === "disagreeing");

  return (
    <>
      <h2>Pipeline state</h2>
      <p className="lede">
        Derived at build time, as of <span className="mono">{p.as_of_utc_day}</span>. {p.as_of_note}
      </p>

      {p.as_of_precedes_some_observations.length ? (
        <div className="note warn">
          {p.as_of_precedes_some_observations.length} case(s) carry an observation day AFTER the day this
          payload was stamped, which means this build was stamped for an earlier day than the evidence it
          read. Ages below are measured from the stamp and are floors, not exact figures:{" "}
          <span className="mono">{p.as_of_precedes_some_observations.join(", ")}</span>
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

      <h3>Where the live verdict and an archived one disagree</h3>
      <p>
        {disagreeing.length} of {p.totals.n_cases} registered case(s). A disagreement is a finding: it
        means the platform re-measured something and got a different answer, which is the outcome a
        replication exists to be able to report.
      </p>
      <table className="grid">
        <thead>
          <tr>
            <th>Case</th>
            <th>Archived days</th>
            <th>Archived verdict(s) that differ</th>
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
                    <span className="badge v-none">{d.verdict}</span>{" "}
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

      <h3>By family</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        A row is a set of cases, not a job: there is no percentage and no completion figure here. Click a
        row for the cases behind its numbers. The cadences and the sentences inside a row are authored,
        in{" "}
        <span className="mono">{families.find((f) => f.source)?.source ?? "an unstated file"}</span>{" "}
        — read from the payload rather than written into this page, so a page that quoted a file it could
        not name would say so here; every number is derived.
      </p>
      <div className="scroll">
        <table className="grid">
          <thead>
            <tr>
              <th>Family</th>
              <th>What it measures</th>
              <th>State</th>
              <th>Cadence (days)</th>
              <th>Last observed</th>
              <th>Age (days)</th>
              <th>Cases</th>
              <th>With a verdict</th>
              <th>No observed day</th>
              <th>≥2 archived days</th>
              <th>Disagreeing</th>
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

      <h3>What the replication counts mean</h3>
      <div className="cards">
        <div className="card">
          <div className="n">{p.totals.n_with_two_or_more_archived_days}</div>
          <div className="k">case(s) with two or more archived days</div>
          <div className="def">
            Counted from the archive alone, and non-exclusively: today every one of these is also a
            disagreement, so the agreeing bucket below reads 0.
          </div>
        </div>
        <div className="card">
          <div className="n">{p.totals.n_one_archived_prior_day}</div>
          <div className="k">case(s) with exactly one archived prior day</div>
        </div>
        <div className="card">
          <div className="n">{p.totals.n_no_archived_prior_day}</div>
          <div className="k">case(s) with nothing archived</div>
          <div className="def">No prior occasion is established for these, whatever their verdict.</div>
        </div>
        <div className="card">
          <div className="n">{p.totals.n_with_no_observed_day}</div>
          <div className="k">case(s) whose observation day is not derivable</div>
          <div className="def">
            The verdict files carry no machine-readable day stamp in a fixed place, so for these the
            family reads NOT OBSERVED rather than "within cadence". Under-claiming freshness is
            recoverable by reading the case; over-claiming it is what tells somebody a control was
            checked last week.
          </div>
        </div>
      </div>
      <div className="note" style={{ marginTop: 12 }}>
        {p.totals.why_replication_is_counted_from_the_archive_only}
      </div>
      <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 10 }}>{p.note}</p>
    </>
  );
}
