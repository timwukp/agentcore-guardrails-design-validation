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
//
// WHAT IS TRANSLATED HERE AND WHAT IS NOT
//
// This page is almost entirely this platform's own prose about its own procedure, so almost all of it is
// translated. The exceptions are the sentences that belong to something else and are quoted: `method.json`'s
// `note` and `why_this_is_counted`, and `families.yaml`'s `why`, `replication_requirement` and
// `ui_state_note`. Those render verbatim in English in both languages, as does every vocabulary the
// payload keys on — the four verdict words, the oracle-kind names, the guard names, the family ids and
// the cost/runner/mutates vocabularies.

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { loadFamilies, loadMethod } from "../lib/data";
import { ErrorPanel, KV, Loading, useAsync } from "../components/ui";
import { A, T, useT, VerbatimNote } from "../lib/i18n";
import { byCaseId } from "../lib/sort";
import type { Method } from "../lib/types";

/** The bucket `build_site_data.py` files a nameless guard under. It is a KEY into the payload, not a
 *  label — it is looked up and then excluded from the table, never displayed — so it stays byte-identical
 *  to the producer's string in both languages. */
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
  const t = useT();
  const rows = Object.entries(kinds).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return (
    <div className="scroll" style={{ maxHeight: 360 }}>
      <table className="grid">
        <thead>
          <tr>
            <th>{t("mth.kind.th.kind")}</th>
            <th>{t("mth.kind.th.cases")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, n]) => (
            <tr key={k}>
              <td className="mono" lang="en">
                {k}
              </td>
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
  const t = useT();
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
        <T
          k="mth.g.body"
          v={{ test: <code>test</code>, why: <code>why</code> }}
        />
      </p>
      <div className="cards" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="n">{entries.length}</div>
          <div className="k">{t("mth.g.card.distinct")}</div>
          <div className="def">{t("mth.g.card.distinct.def")}</div>
        </div>
        <div className="card">
          <div className="n">{once}</div>
          <div className="k">{t("mth.g.card.once")}</div>
          <div className="def">{t("mth.g.card.once.def")}</div>
        </div>
      </div>

      {unnamed ? (
        <div className="note warn">
          <strong>{t("mth.g.unnamed.head", { n: unnamed })}</strong>{" "}
          {t("mth.g.unnamed.body", { named: entries.length })}
        </div>
      ) : null}

      <div className="facets">
        <div className="facet">
          <label>{t("mth.g.search")}</label>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("mth.g.placeholder")}
          />
        </div>
        <div className="facet">
          <label>&nbsp;</label>
          <span className="count mono">{t("mth.g.shown", { n: shown.length })}</span>
        </div>
      </div>
      <div className="scroll" style={{ maxHeight: 420 }}>
        <table className="grid">
          <thead>
            <tr>
              <th>{t("mth.g.th.guard")}</th>
              <th>{t("mth.g.th.cases")}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map(([k, n]) => (
              <tr key={k}>
                {/* A guard's name is the producer's identifier, and the case pages print it as stored.
                    A translated name here would be a name that exists on no record. */}
                <td className="mono" lang="en">
                  {k}
                </td>
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
  const t = useT();
  return (
    <>
      <p>
        <T
          k="mth.cav.body"
          v={{
            t: <code>what_true_does_not_prove</code>,
            f: <code>what_false_does_not_prove</code>,
          }}
        />
      </p>
      <div className="cards" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="n">
            {c.cases_with_what_false_does_not_prove} / {c.false_verdicts}
          </div>
          <div className="k">
            <T k="mth.cav.card.false" v={{ v: <span lang="en">FALSE</span> }} />
          </div>
          <div className="def">{t("mth.cav.card.false.def")}</div>
        </div>
        <div className="card">
          <div className="n">
            {c.cases_with_what_true_does_not_prove} / {c.true_verdicts}
          </div>
          <div className="k">
            <T k="mth.cav.card.true" v={{ v: <span lang="en">TRUE</span> }} />
          </div>
          <div className="def">{t("mth.cav.card.true.def")}</div>
        </div>
      </div>
      <div className="note warn">
        {/* `why_this_is_counted` is `method.json`'s own sentence, quoted. */}
        <strong>{t("mth.cav.gap.head")}</strong> <span lang="en">{c.why_this_is_counted}</span>
        <div style={{ marginTop: 8 }}>
          {t("mth.cav.without", {
            v: "FALSE",
            n: c.false_verdicts_without_the_caveat.length,
          })}{" "}
          <CaseList ids={c.false_verdicts_without_the_caveat} />
        </div>
        <div style={{ marginTop: 6 }}>
          {t("mth.cav.without", {
            v: "TRUE",
            n: c.true_verdicts_without_the_caveat.length,
          })}{" "}
          <CaseList ids={c.true_verdicts_without_the_caveat} />
        </div>
      </div>
    </>
  );
}

/** The translation measurement. Four cards over one denominator, the backlog as a warning, and the
 *  producers that owe the most.
 *
 *  Every number here is rendered `x / rendered` rather than alone, because a bare "310 authored" is a
 *  count with no window: it reads as a share of the site to anyone who does not already know that the
 *  chrome is fully bilingual and outside the measurement entirely. The one figure that is not a
 *  fraction is `rendered` itself, which is why its own card states what it is out of.
 *
 *  The producer table's field paths are payload keys, so they render `lang="en"` and mono in both
 *  languages — `audit.json/report/controls[]` is not a sentence to be translated, it is a place to
 *  look. */
function Translation({ m }: { m: Method }) {
  const tr = m.translation;
  const t = useT();
  return (
    <>
      <p>
        <T
          k="mth.s9.body"
          v={{
            tool: <span className="mono">build_site_data.py</span>,
            census: <span className="mono">census_rendered_surfaces.py</span>,
            routes: <strong>{tr.routes_walked}</strong>,
            file: <span className="mono">{tr.measured_in}</span>,
            prov: <Link to="/provenance">{t("nav.provenance")}</Link>,
          }}
        />
      </p>
      <div className="cards" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="n">{tr.rendered}</div>
          <div className="k">{t("mth.tr.card.rendered")}</div>
          <div className="def">{t("mth.tr.card.rendered.def")}</div>
        </div>
        <div className="card">
          <div className="n">
            {tr.identifiers} / {tr.rendered}
          </div>
          <div className="k">{t("mth.tr.card.identifiers")}</div>
          <div className="def">{t("mth.tr.card.identifiers.def")}</div>
        </div>
        <div className="card">
          <div className="n">
            {tr.quoted_artifact} / {tr.rendered}
          </div>
          <div className="k">{t("mth.tr.card.artifact")}</div>
          <div className="def">{t("mth.tr.card.artifact.def")}</div>
        </div>
        <div className="card">
          <div className="n">
            {tr.authored} / {tr.rendered}
          </div>
          <div className="k">{t("mth.tr.card.authored")}</div>
          <div className="def">{t("mth.tr.card.authored.def")}</div>
        </div>
      </div>

      <div className="note warn">
        <strong>{t("mth.tr.backlog.head")}</strong>{" "}
        <T
          k="mth.tr.backlog.body"
          v={{
            n: <strong>{tr.authored_untranslated}</strong>,
            a: <strong>{tr.authored}</strong>,
            gate: <span className="mono">check_site_invariants.py</span>,
          }}
        />
      </div>

      <p style={{ marginBottom: 6 }}>{t("mth.tr.producers.head")}</p>
      <div className="scroll" style={{ maxHeight: 260 }}>
        <table className="grid">
          <thead>
            <tr>
              <th>{t("mth.tr.col.producer")}</th>
              <th>{t("mth.tr.col.chars")}</th>
              <th>{t("mth.tr.col.strings")}</th>
              <th>{t("mth.tr.col.routes")}</th>
            </tr>
          </thead>
          <tbody>
            {tr.largest_producers.map((p) => (
              <tr key={p.producer}>
                <td className="mono" lang="en">
                  {p.producer}
                </td>
                <td className="num">{p.chars}</td>
                <td className="num">{p.strings}</td>
                <td className="mono" lang="en">
                  {p.routes.join(" ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="note" style={{ marginTop: 12 }}>
        {/* `what_this_is_not` is one of the sentences this measurement is about, so it is bilingual in
            the payload and resolved by `<A>` — a paragraph explaining the translation backlog, readable
            only in the language the backlog is against, would be the first entry in it. */}
        <strong>{t("mth.tr.notwhat")}</strong> <A v={tr.what_this_is_not} />
      </div>
    </>
  );
}

function Replication({ m }: { m: Method }) {
  const t = useT();
  const twoDay = Object.entries(m.archive_days_by_case)
    .filter(([, d]) => new Set(d).size >= 2)
    .map(([c]) => c);
  const oneDay = Object.entries(m.archive_days_by_case)
    .filter(([, d]) => new Set(d).size < 2)
    .map(([c]) => c);

  return (
    <>
      <p>
        <T
          k="mth.rep.body"
          v={{
            dir: <span className="mono">results/phase1/archive/</span>,
            days: <strong>{t("mth.rep.distinctDays")}</strong>,
          }}
        />
      </p>
      <div className="cards" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="n">{m.n_cases_with_an_archive}</div>
          <div className="k">{t("mth.rep.card.archive")}</div>
          <div className="def">{t("mth.rep.card.archive.def")}</div>
        </div>
        <div className="card">
          <div className="n">{m.n_cases_with_two_distinct_archive_days}</div>
          <div className="k">{t("mth.rep.card.twoDays")}</div>
          <div className="def">{t("mth.rep.card.twoDays.def")}</div>
        </div>
        <div className="card">
          <div className="n">{m.archives_disagreeing_with_the_live_verdict.length}</div>
          <div className="k">{t("mth.rep.card.disagree")}</div>
          <div className="def">{t("mth.rep.card.disagree.def")}</div>
        </div>
      </div>

      {m.archives_disagreeing_with_the_live_verdict.length ? (
        <table className="grid" style={{ marginBottom: 14 }}>
          <thead>
            <tr>
              <th>{t("mth.rep.th.case")}</th>
              <th>{t("mth.rep.th.archived")}</th>
              <th>{t("mth.rep.th.live")}</th>
              <th>{t("mth.rep.th.label")}</th>
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
                  <td className="mono" lang="en">
                    {d.archived_verdict}
                  </td>
                  <td className="mono" lang="en">
                    {d.live_verdict ?? "—"}
                  </td>
                  <td className="mono">{d.label}</td>
                </tr>
              ))}
          </tbody>
        </table>
      ) : null}

      <KV
        rows={[
          [t("mth.rep.kv.twoDays"), twoDay.length ? <CaseList ids={twoDay} /> : t("mth.rep.none")],
          [t("mth.rep.kv.oneDay"), oneDay.length ? <CaseList ids={oneDay} /> : t("mth.rep.none")],
        ]}
      />
    </>
  );
}

function FamilyTable() {
  const t = useT();
  const res = useAsync(loadFamilies, []);
  if (res.state === "loading") return <Loading what={t("mth.fam.loading")} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const f = res.data;
  const rows = Object.entries(f.families).sort((a, b) =>
    a[0].localeCompare(b[0], undefined, { numeric: true }),
  );

  return (
    <>
      <p>
        <T
          k="mth.fam.body"
          v={{ file: <span className="mono">platform/curation/families.yaml</span> }}
        />
      </p>
      <div className="scroll">
        <table className="grid">
          <thead>
            <tr>
              <th>{t("mth.fam.th.family")}</th>
              <th>{t("mth.fam.th.cases")}</th>
              <th>{t("mth.fam.th.cost")}</th>
              <th>{t("mth.fam.th.runner")}</th>
              <th>{t("mth.fam.th.mutates")}</th>
              <th>{t("mth.fam.th.schedulable")}</th>
              <th>{t("mth.fam.th.whyNot")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([id, x]) => (
              <tr key={id}>
                <td className="mono">{id}</td>
                <td className="num">{x.n_cases}</td>
                {/* The cost, runner and mutates values are `families.yaml`'s closed vocabularies, listed
                    verbatim in the note below the table. They stay in the words the file uses. */}
                <td className="mono" lang="en">
                  {x.cost}
                </td>
                <td
                  className="mono"
                  lang="en"
                  style={x.runner === "macbook_only" ? { color: "var(--warn)" } : undefined}
                >
                  {x.runner}
                </td>
                <td className="mono" lang="en">
                  {x.mutates}
                </td>
                <td className="mono">{x.schedulable ? t("mth.fam.yes") : t("mth.fam.no")}</td>
                <td style={{ minWidth: 320 }} lang="en">
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
        <T k="mth.fam.costNote" v={{ cost: <code>cost</code> }} />{" "}
        {t("mth.fam.vocabularies")}{" "}
        <span lang="en">
          {Object.entries(f.vocabularies)
            .map(([k, v]) => `${k} ∈ {${v.join(", ")}}`)
            .join("; ")}
        </span>
        .
      </p>

      {rows
        .filter(([, x]) => x.network_position_sensitive)
        .map(([id, x]) => (
          <div className="note warn" key={id}>
            {/* `why`, `replication_requirement` and `ui_state_note` are the authored classification's
                own sentences: this is the banner `check_scenarios.py` requires, and it must say what the
                file says rather than a paraphrase of it. */}
            <strong>{t("mth.fam.netPos", { id })}</strong> <span lang="en">{x.why}</span>
            <div style={{ marginTop: 6 }} lang="en">
              {x.replication_requirement}
            </div>
            {x.ui_state_note ? (
              <div style={{ marginTop: 6, color: "var(--fg-dim)" }}>
                <T
                  k="mth.fam.uiState"
                  v={{ state: <span className="mono">{x.ui_state_when_old}</span> }}
                />{" "}
                <span lang="en">{x.ui_state_note}</span>
              </div>
            ) : null}
          </div>
        ))}
    </>
  );
}

export default function MethodView() {
  const res = useAsync(loadMethod, []);
  const t = useT();
  // The verbatim banner on every payload view links to `/method#translation`, and it is the only
  // deep link into this page. Without this the reader arrives at step 1 of eight and has to find, by
  // scrolling, the block they were told the number was in — which is the same as not publishing it.
  // Keyed on `res.state` as well as the hash because the target does not exist until the fetch lands.
  const { hash } = useLocation();
  useEffect(() => {
    if (res.state !== "ok" || hash !== "#translation") return;
    document.getElementById("translation")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [res.state, hash]);
  if (res.state === "loading") return <Loading what={t("mth.loading")} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const m = res.data;

  return (
    <>
      <h2 className="view">{t("nav.method")}</h2>
      <VerbatimNote />
      <p className="lede">{t("mth.lede")}</p>

      <div className="note seal">
        <span lang="en">{m.note}</span> {t("mth.note")}
      </div>

      <Step n={1} title={t("mth.s1.title")}>
        <p>
          <T
            k="mth.s1.body"
            v={{
              file: <span className="mono">claims/triage.csv</span>,
              sealed: <strong>{t("mth.sealed")}</strong>,
              claims: <Link to="/claims">{t("nav.claims")}</Link>,
            }}
          />
        </p>
      </Step>

      <Step n={2} title={t("mth.s2.title")}>
        <p>
          <T
            k="mth.s2.body"
            v={{
              pre: <span className="mono">PREREGISTRATION.yaml</span>,
              oracle: <code>oracle_text</code>,
            }}
          />
        </p>
        <p>{t("mth.s2.kinds", { n: Object.keys(m.kinds).length })}</p>
        <KindTable kinds={m.kinds} />
      </Step>

      <Step n={3} title={t("mth.s3.title")}>
        <Guards m={m} />
      </Step>

      <Step n={4} title={t("mth.s4.title")}>
        {/* The pass-rate denial. The publish gate requires that every occurrence of the phrase in the
            shipped bundle be a denial, in each language, so the Chinese sentence cannot be dropped
            without failing the build — a zh page whose only statement about a pass rate was its silence
            would be a different platform from this one. */}
        <p>
          <T
            k="mth.s4.body"
            v={{
              t: <strong lang="en">TRUE</strong>,
              f: <strong lang="en">FALSE</strong>,
              i: <strong lang="en">INCONCLUSIVE</strong>,
              r: <strong lang="en">RECORDED</strong>,
            }}
          />
        </p>
      </Step>

      <Step n={5} title={t("mth.s5.title")}>
        <Caveats m={m} />
      </Step>

      <Step n={6} title={t("mth.s6.title")}>
        <Replication m={m} />
      </Step>

      <Step n={7} title={t("mth.s7.title")}>
        <FamilyTable />
      </Step>

      <Step n={8} title={t("mth.s8.title")}>
        <p>
          <T
            k="mth.s8.body"
            v={{
              i: <span lang="en">INCONCLUSIVE</span>,
              citations: <Link to="/citations">{t("nav.citations")}</Link>,
              register: <Link to="/register">{t("nav.register")}</Link>,
            }}
          />
        </p>
      </Step>

      {/* NOT numbered as a step, deliberately. Steps 1-8 are the chain a verdict passes through, and
          numbering this ninth would state that translating the site is part of adjudicating a claim.
          It is a property of this page rather than of the method, which is also why it is last: a
          reader who came here from the banner is brought to it by the anchor, and a reader working
          through the method in order reaches it after the method is over. */}
      <section id="translation">
        <h3>{t("mth.s9.title")}</h3>
        <Translation m={m} />
      </section>
    </>
  );
}
