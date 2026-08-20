// View 1 — the census.
//
// TWO RULES THIS FILE ENFORCES BY CONSTRUCTION
//
// 1. NO PASS RATE. There is no ratio anywhere on this page and no arithmetic that divides one verdict
//    count by another or by any denominator. The four verdicts are not two outcomes plus noise: a
//    FALSE verdict locates a place where published guidance did not hold under measurement, which is
//    the study's most valuable output, and an INCONCLUSIVE verdict says nothing was established — a
//    result that a percentage would silently convert into a failure. Any summary statistic over the
//    mix would also need a denominator, and the four denominators below differ for stated reasons, so
//    there is no single number a rate could honestly be taken over.
//
// 2. NO DENOMINATOR WITHOUT ITS DEFINITION. Each count renders beside the prose that says what it
//    counts and the artifact it was derived from, because the four differ and the differences are the
//    interesting part. A reader who sees only the numbers will assume the smallest is the real one and
//    the rest are rounding.
//
// Every number on this page comes out of `denominators.json` / `census.json`. None is written here.

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { loadCensus, loadDenominators } from "../lib/data";
import type { CensusRow, Denominator, Denominators, Verdict } from "../lib/types";
import { VERDICTS } from "../lib/types";
import { ErrorPanel, Loading, VerdictBadge, useAsync } from "../components/ui";
import { byCaseId, distinct } from "../lib/sort";

const ANY = "— any —";

/** The four denominators read as a narrowing sequence — registered, then eligible, then published,
 *  then mapped — and that order is the argument for why they differ. Alphabetical order (which is what
 *  `Object.entries` gives) puts `claim_mapped` first and makes the set look like five unrelated
 *  integers, which is the reading the definitions exist to prevent. Any key the build adds later that
 *  is not in this list still renders, after these, rather than disappearing. */
const DENOM_ORDER = ["registered", "verdict_eligible", "published", "claim_mapped", "claims_triaged"];

function orderDenominators(d: Denominators): [string, Denominator][] {
  const rank = (k: string) => {
    const i = DENOM_ORDER.indexOf(k);
    return i === -1 ? DENOM_ORDER.length : i;
  };
  // `Object.entries` at runtime, so a key the build adds before the type learns about it is still
  // rendered rather than silently dropped by a hand-written list of five field accesses.
  return (Object.entries(d) as [string, Denominator][]).sort(
    (a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]),
  );
}

function DenominatorCard({ k, d }: { k: string; d: Denominator }) {
  const excluded: [string, string[]][] = [
    ["not mapped to a claim", d.unmapped ?? []],
    ["untestable as written", d.untestable ?? []],
    ["outstanding", d.outstanding ?? []],
  ].filter(([, v]) => (v as string[]).length) as [string, string[]][];
  return (
    <div className="card">
      <div className="n">{d.n}</div>
      <div className="k">{k.replace(/_/g, " ")}</div>
      <div className="def">{d.definition}</div>
      {excluded.map(([label, cases]) => (
        <div className="def" key={label}>
          <strong style={{ color: "var(--fg-dim)" }}>{label}:</strong>{" "}
          {cases.map((c, i) => (
            <span key={c}>
              {i ? ", " : ""}
              <Link to={`/case/${c}`}>{c}</Link>
            </span>
          ))}
        </div>
      ))}
      <div className="src">{d.derived_from}</div>
    </div>
  );
}

function Mix({ mix }: { mix: Record<string, number> }) {
  // Widths are proportional so the bar is readable, but no percentage is ever displayed: the label
  // on each segment is the count itself. A reader can compute a ratio if they want one; the platform
  // will not hand them a rate it cannot honestly define a denominator for.
  const total = VERDICTS.reduce((s, v) => s + (mix[v] ?? 0), 0);
  const extra = Object.keys(mix).filter((k) => !(VERDICTS as readonly string[]).includes(k));
  return (
    <>
      <div className="mix">
        {VERDICTS.map((v) => {
          const n = mix[v] ?? 0;
          if (!n) return null;
          return (
            <div key={v} className={`m-${v}`} style={{ flexGrow: n }} title={`${v}: ${n}`}>
              {n}
            </div>
          );
        })}
      </div>
      <div className="mixlegend">
        {VERDICTS.map((v) => (
          <span key={v}>
            <span className="sw" style={{ background: `var(--v-${v.toLowerCase()})` }} />
            {v} <span className="mono">{mix[v] ?? 0}</span>
          </span>
        ))}
        <span style={{ color: "var(--fg-faint)" }}>
          published verdicts <span className="mono">{total}</span>
        </span>
      </div>
      {extra.length ? (
        <div className="note warn" style={{ marginTop: 12 }}>
          <strong>The payload contains a verdict value this UI does not know about:</strong>{" "}
          {extra.join(", ")}. It is counted in the total above but has no colour and no column, which
          means the census is wider than the vocabulary this build was written against.
        </div>
      ) : null}
    </>
  );
}

export default function Overview() {
  const census = useAsync(loadCensus, []);
  const denom = useAsync(loadDenominators, []);

  const [family, setFamily] = useState(ANY);
  const [tier, setTier] = useState(ANY);
  const [verdict, setVerdict] = useState(ANY);
  const [restricted, setRestricted] = useState(false);
  const [q, setQ] = useState("");

  const rows: CensusRow[] = census.state === "ok" ? census.data.rows : [];

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows
      .filter((r) => family === ANY || r.family === family)
      .filter((r) => tier === ANY || r.tier === tier)
      .filter((r) =>
        verdict === ANY
          ? true
          : verdict === "no verdict"
            ? !r.has_verdict
            : r.verdict === (verdict as Verdict),
      )
      .filter((r) => !restricted || r.citation_restrictions.length > 0)
      .filter(
        (r) =>
          !needle ||
          r.case.toLowerCase().includes(needle) ||
          r.title.toLowerCase().includes(needle) ||
          r.claims.some((c) => c.toLowerCase().includes(needle)),
      )
      .sort((a, b) => byCaseId(a.case, b.case));
  }, [rows, family, tier, verdict, restricted, q]);

  return (
    <>
      <h2 className="view">Census</h2>
      <p className="lede">
        Every registered case, its verdict, and the claim it was derived from. The counts below are
        recomputed from the artifacts on every build and are not stored anywhere as a number.
      </p>

      <section>
        <h3>Denominators, each with what it counts</h3>
        {denom.state === "loading" ? (
          <Loading what="denominators" />
        ) : denom.state === "error" ? (
          <ErrorPanel error={denom.error} />
        ) : (
          <div className="cards">
            {orderDenominators(denom.data).map(([k, d]) => (
              <DenominatorCard key={k} k={k} d={d} />
            ))}
          </div>
        )}
      </section>

      <section>
        <h3>Verdict mix</h3>
        {census.state === "loading" ? (
          <Loading what="the census" />
        ) : census.state === "error" ? (
          <ErrorPanel error={census.error} />
        ) : (
          <>
            <Mix mix={census.data.verdict_mix} />
            <div className="note" style={{ marginTop: 14 }}>
              <strong>There is no pass rate on this platform.</strong> INCONCLUSIVE is a result, not a
              missing one: it records that the measurement did not establish the claim either way, and
              it licenses no amendment to the design document. FALSE is not a defect in the study — it
              is where the guidance did not hold, which is what the work was for. Dividing any of these
              counts by any of the four denominators above would produce a number none of the
              definitions support.
            </div>
            <SealPanel seal={census.data.seal} />
          </>
        )}
      </section>

      <section>
        <h3>
          Cases <span className="count mono">({filtered.length} shown)</span>
        </h3>
        <div className="facets">
          <div className="facet">
            <label>family</label>
            <select value={family} onChange={(e) => setFamily(e.target.value)}>
              {[ANY, ...distinct(rows.map((r) => r.family))].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </div>
          <div className="facet">
            <label>tier</label>
            <select value={tier} onChange={(e) => setTier(e.target.value)}>
              {[ANY, ...distinct(rows.map((r) => r.tier))].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </div>
          <div className="facet">
            <label>verdict</label>
            <select value={verdict} onChange={(e) => setVerdict(e.target.value)}>
              {[ANY, ...VERDICTS, "no verdict"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </div>
          <div className="facet">
            <label>search</label>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="case, title or claim id"
            />
          </div>
          <div className="facet">
            <label>&nbsp;</label>
            <label style={{ textTransform: "none", letterSpacing: 0, fontSize: 13, color: "var(--fg-dim)" }}>
              <input
                type="checkbox"
                checked={restricted}
                onChange={(e) => setRestricted(e.target.checked)}
                style={{ minWidth: 0, marginRight: 6 }}
              />
              citation-restricted only
            </label>
          </div>
          <div className="facet">
            <label>&nbsp;</label>
            <button
              className="plain"
              onClick={() => {
                setFamily(ANY);
                setTier(ANY);
                setVerdict(ANY);
                setRestricted(false);
                setQ("");
              }}
            >
              reset
            </button>
          </div>
        </div>

        {census.state === "ok" ? (
          <div className="scroll">
            <table className="grid">
              <thead>
                <tr>
                  <th>case</th>
                  <th>verdict</th>
                  <th>family</th>
                  <th>tier</th>
                  <th>title</th>
                  <th>claims</th>
                  <th>archived</th>
                  <th>citation</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.case}>
                    <td className="mono">
                      <Link to={`/case/${r.case}`}>{r.case}</Link>
                    </td>
                    <td>
                      <VerdictBadge v={r.verdict} />
                    </td>
                    <td>{r.family}</td>
                    <td>{r.tier}</td>
                    <td>{r.title}</td>
                    <td className="num">{r.n_claims}</td>
                    <td className="num">{r.archive_labels.length}</td>
                    <td>
                      {r.citation_restrictions.length ? (
                        <span className="badge restrict">restricted</span>
                      ) : (
                        <span style={{ color: "var(--fg-faint)" }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {census.state === "ok" && !filtered.length ? (
          <div className="note">
            No case matches this filter combination. That is a statement about the filters, not about
            the register — clear them to see every registered case.
          </div>
        ) : null}
      </section>
    </>
  );
}

function SealPanel({
  seal,
}: {
  seal: {
    method: string;
    n_cases_declared: number;
    registry_sha256_declared: string;
    registry_sha256_recomputed: string;
  };
}) {
  const ok = seal.registry_sha256_declared === seal.registry_sha256_recomputed;
  return (
    <div className={`note ${ok ? "seal" : "warn"}`} style={{ marginTop: 14 }}>
      <strong>Oracle registry seal:</strong> {ok ? "declared hash matches recomputed" : "MISMATCH"}
      <div className="mono" style={{ marginTop: 6, fontSize: 11.5, wordBreak: "break-all" }}>
        declared {seal.registry_sha256_declared}
        <br />
        recomputed {seal.registry_sha256_recomputed}
      </div>
      <div style={{ marginTop: 6, fontSize: 12 }}>
        Recomputed over the {seal.n_cases_declared} declared oracle texts, {seal.method}. Each
        case's oracle was fixed before its measurement ran; a mismatch here would mean an oracle
        changed after the fact, which is why the build recomputes it rather than trusting the recorded
        value.
      </div>
    </div>
  );
}
