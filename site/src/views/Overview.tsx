// View 1 — the census.
//
// TWO RULES THIS FILE ENFORCES BY CONSTRUCTION
//
// 1. NO PASS RATE. There is no ratio anywhere on this page and no arithmetic that divides one verdict
//    count by another or by any denominator. The four verdicts are not two outcomes plus noise: a
//    FALSE verdict locates a place where published guidance did not hold under measurement, which is
//    the study's most valuable output, and an INCONCLUSIVE verdict says nothing was established — a
//    result that a percentage would silently convert into a failure. Any summary statistic over the
//    mix would also need a denominator, and the denominators on this page differ for stated reasons, so
//    there is no single number a rate could honestly be taken over.
//
// 2. NO DENOMINATOR WITHOUT ITS DEFINITION. Each count renders beside the prose that says what it
//    counts and the artifact it was derived from, because they differ and the differences are the
//    interesting part. A reader who sees only the numbers will assume the smallest is the real one and
//    the rest are rounding.
//
// Every number on this page comes out of `denominators.json` / `census.json`. None is written here.
//
// SECTION ORDER, AND WHAT IT IS NOT ALLOWED TO CLAIM. The verdict mix and the no-pass-rate denial come
// first, then the denominator cards, then the case table. Until 2026-08-22 it was the other way round:
// five cards, each carrying a definition paragraph, two exclusion lists and a file glob, stood between
// the reader and the only four numbers that say what this study found — the mix was reliably off the
// first screen at 1440×900.
//
// This ordering is ORIENTATION, and that is the whole of the claim. Hornbæk, Bederson & Plaisant 2002
// (ACM ToCHI 9(4) 362-389, n = 32) is the closest measurement to hand, and it measured against the
// comfortable version of this argument: overview-plus-detail produced no reliable improvement in task
// correctness, subjects recalled individual objects BETTER without the overview, and about 80% preferred
// having one regardless of whether it helped them. So: a reader who says the page is clearer now has
// told us about a preference, and a preference is not a validation. Nothing here — not this comment, not
// `ovw.startHere`, not the copy — may say the order helps anyone understand the study. What it does is
// put the counts where a reader who leaves after eight seconds will still have seen them, and the
// definitions one screen further down where a reader who is going to use a number will still meet them
// before using it. Rule 2 is unchanged: no count renders without its definition beside it.
//
// What this order cannot fix, and is not pretending to: a reader who reads only the mix has read four
// integers whose denominators are three screens of prose away, which is exactly the misreading rule 2
// exists to prevent. That is why the mix panel's own note ends by naming the denominators rather than
// by summarising them, and why the cards were moved rather than collapsed.

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { loadCensus, loadDenominators } from "../lib/data";
import type { CensusRow, Denominator, Denominators, Verdict } from "../lib/types";
import { VERDICTS } from "../lib/types";
import { ErrorPanel, Loading, VerdictBadge, useAsync } from "../components/ui";
import { A, T, useT, VerbatimNote } from "../lib/i18n";
import type { Key } from "../lib/strings";
import { byCaseId, distinct } from "../lib/sort";

/** Sentinels, never labels. The facet's state is compared against these, so if the state were the
 *  displayed text then switching language mid-filter would leave the filter set to a value no option
 *  carries: the table would empty while the control still looked normal. `*` cannot occur in a family, a
 *  tier or a verdict, so neither sentinel can collide with a real value. */
const ANY = "*any*";
const NO_VERDICT = "*noverdict*";

/** The denominators read as a narrowing sequence — registered, then eligible, then published, then
 *  mapped, then triaged — and that order is the argument for why they differ. Alphabetical order (which
 *  is what `Object.entries` gives) puts `claim_mapped` first and makes the set look like five unrelated
 *  integers, which is the reading the definitions exist to prevent. Any key the build adds later that
 *  is not in this list still renders, after these, rather than disappearing — which is also why this
 *  comment names the sequence instead of counting it. */
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
  const t = useT();
  const excluded: [Key, string[]][] = (
    [
      ["ovw.excl.unmapped", d.unmapped ?? []],
      ["ovw.excl.untestable", d.untestable ?? []],
      ["ovw.excl.outstanding", d.outstanding ?? []],
    ] as [Key, string[]][]
  ).filter(([, v]) => v.length);
  return (
    <div className="card">
      <div className="n">{d.n}</div>
      {/* The denominator's name is `denominators.json`'s own key — `verdict_eligible`, not a phrase — and
          it is what a reader greps the payload for, so it stays in English in both languages.
          The definition is NOT: this comment used to say it was "the artifact's own prose, quoted for
          the same reason", and it never was. `build_site_data.derive_denominators` composes those five
          sentences; they are this platform explaining why 93, 92, 91 and 90 differ, which is the one
          thing on this page a reader cannot skip. They are `Authored` now, so `<A>` gives the reader
          their own language and marks `lang="en"` only if it is falling back. */}
      <div className="k" lang="en">
        {k.replace(/_/g, " ")}
      </div>
      <div className="def">
        <A v={d.definition} />
      </div>
      {excluded.map(([label, cases]) => (
        <div className="def" key={label}>
          <strong style={{ color: "var(--fg-dim)" }}>{t(label)}</strong>{" "}
          {cases.map((c, i) => (
            <span key={c}>
              {i ? ", " : ""}
              <Link to={`/case/${c}`}>{c}</Link>
            </span>
          ))}
        </div>
      ))}
      {/* NATIVE `<details>`, not a `useState` toggle, and the reason is a measurement rather than a
          preference. `census_rendered_surfaces.py` opens every `<details>` on the page before it
          collects text and records the strings it found that way as `behind_disclosure`, so a native
          disclosure keeps this path inside the rendered census and inside the browser's find-in-page. A
          conditional render would have deleted it from the DOM — and since the translation backlog
          ceiling is a count of rendered untranslated strings, collapsing prose out of the DOM would have
          lowered that number by hiding text rather than by translating it. A gate that a UI change can
          satisfy by hiding its subject is a gate measuring the wrong thing, so the UI must not be able
          to do that.
          What is behind it is a file path or a glob: the reader who wants it is going to open the file,
          and the reader who doesn't was being asked to scroll past five of them to reach the counts. */}
      <details className="srcwrap">
        <summary>{t("ovw.src.summary")}</summary>
        <div className="src" lang="en">
          {d.derived_from}
        </div>
      </details>
    </div>
  );
}

function Mix({ mix }: { mix: Record<string, number> }) {
  const t = useT();
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
            <span lang="en">{v}</span> <span className="mono">{mix[v] ?? 0}</span>
          </span>
        ))}
        <span style={{ color: "var(--fg-faint)" }}>
          {t("ovw.publishedVerdicts")} <span className="mono">{total}</span>
        </span>
      </div>
      {extra.length ? (
        <div className="note warn" style={{ marginTop: 12 }}>
          <T
            k="ovw.unknownVerdict"
            v={{
              head: <strong>{t("ovw.unknownVerdict.head")}</strong>,
              values: <span lang="en">{extra.join(", ")}</span>,
            }}
          />
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
  const t = useT();

  const rows: CensusRow[] = census.state === "ok" ? census.data.rows : [];

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows
      .filter((r) => family === ANY || r.family === family)
      .filter((r) => tier === ANY || r.tier === tier)
      .filter((r) =>
        verdict === ANY
          ? true
          : verdict === NO_VERDICT
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
      <h2 className="view">{t("nav.census")}</h2>
      <VerbatimNote />
      <p className="lede">{t("ovw.lede")}</p>
      {/* The link label is `nav.method` — the same string the sidebar entry uses — so the sentence names
          the destination the way the reader will recognise it, and a rename happens in one place. No
          anchor: this one points at the top of the page, because the whole page is the answer to "what
          is one verdict". */}
      <p className="starthere">
        <T k="ovw.startHere" v={{ link: <Link to="/method">{t("nav.method")}</Link> }} />
      </p>

      <section>
        <h3>{t("ovw.h.mix")}</h3>
        {census.state === "loading" ? (
          <Loading what={t("ovw.loading.census")} />
        ) : census.state === "error" ? (
          <ErrorPanel error={census.error} />
        ) : (
          <>
            <Mix mix={census.data.verdict_mix} />
            {/* The denial is a whole sentence in both languages. The publish gate requires it: every
                occurrence of the phrase in the shipped bundle must be a denial, in each language, so a
                build that dropped the Chinese sentence fails rather than shipping a zh page whose only
                statement about a pass rate is its absence. */}
            <div className="note" style={{ marginTop: 14 }}>
              <strong>{t("ovw.noRatio.head")}</strong> {t("ovw.noRatio.body")}
            </div>
            <SealPanel seal={census.data.seal} />
          </>
        )}
      </section>

      <section>
        <h3>{t("ovw.h.denominators")}</h3>
        {denom.state === "loading" ? (
          <Loading what={t("ovw.loading.denominators")} />
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
        <h3>
          {t("ovw.h.cases")}{" "}
          <span className="count mono">({t("facet.shown", { n: filtered.length })})</span>
        </h3>
        <div className="facets">
          <div className="facet">
            <label>{t("pip.th.family")}</label>
            <select value={family} onChange={(e) => setFamily(e.target.value)}>
              <option value={ANY}>{t("facet.any")}</option>
              {distinct(rows.map((r) => r.family)).map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div className="facet">
            <label>{t("reg.facet.tier")}</label>
            <select value={tier} onChange={(e) => setTier(e.target.value)}>
              <option value={ANY}>{t("facet.any")}</option>
              {distinct(rows.map((r) => r.tier)).map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div className="facet">
            <label>{t("ovw.facet.verdict")}</label>
            <select value={verdict} onChange={(e) => setVerdict(e.target.value)}>
              <option value={ANY}>{t("facet.any")}</option>
              {VERDICTS.map((v) => (
                <option key={v} value={v} lang="en">
                  {v}
                </option>
              ))}
              <option value={NO_VERDICT}>{t("ui.verdict.none")}</option>
            </select>
          </div>
          <div className="facet">
            <label>{t("clm.facet.search")}</label>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("ovw.facet.searchHint")}
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
              {t("ovw.facet.restrictedOnly")}
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
              {t("ovw.facet.reset")}
            </button>
          </div>
        </div>

        {census.state === "ok" ? (
          <div className="scroll">
            <table className="grid">
              <thead>
                <tr>
                  <th>{t("ovw.th.case")}</th>
                  <th>{t("ovw.facet.verdict")}</th>
                  <th>{t("pip.th.family")}</th>
                  <th>{t("reg.facet.tier")}</th>
                  <th>{t("fnd.th.title")}</th>
                  <th>{t("ovw.th.claims")}</th>
                  <th>{t("ovw.th.archived")}</th>
                  <th>{t("ovw.th.citation")}</th>
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
                    <td lang="en">{r.title}</td>
                    <td className="num">{r.n_claims}</td>
                    <td className="num">{r.archive_labels.length}</td>
                    <td>
                      {r.citation_restrictions.length ? (
                        <span className="badge restrict">{t("ovw.restricted")}</span>
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
          <div className="note">{t("ovw.noMatch")}</div>
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
  const t = useT();
  const ok = seal.registry_sha256_declared === seal.registry_sha256_recomputed;
  return (
    <div className={`note ${ok ? "seal" : "warn"}`} style={{ marginTop: 14 }}>
      <strong>{t("ovw.seal.head")}</strong> {t(ok ? "ovw.seal.ok" : "ovw.seal.mismatch")}
      <div className="mono" style={{ marginTop: 6, fontSize: 11.5, wordBreak: "break-all" }}>
        {t("ovw.seal.declared")} {seal.registry_sha256_declared}
        <br />
        {t("ovw.seal.recomputed")} {seal.registry_sha256_recomputed}
      </div>
      <div style={{ marginTop: 6, fontSize: 12 }}>
        <T
          k="ovw.seal.body"
          v={{ n: seal.n_cases_declared, method: <span lang="en">{seal.method}</span> }}
        />
      </div>
    </div>
  );
}
