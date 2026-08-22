// The citation policy — the rule about what these verdicts may and may not be used to say.
//
// This page exists because a verdict is not automatically a citable fact. Three situations recur in
// this study and each one is a trap for a reader who sees only a verdict badge: a TRUE that rests on a
// measurement too narrow to support the sentence it would be quoted in; a record that is a written
// observation rather than an adjudicated verdict; and an INCONCLUSIVE, which licenses no amendment in
// either direction. The policy is machine-readable so that every case page renders its own
// restrictions from the same source this page renders — a component cannot disagree with it, because
// no component states it.

import { Link } from "react-router-dom";
import { loadCitationPolicy } from "../lib/data";
import { T, useT, VerbatimNote } from "../lib/i18n";
import { Body, ErrorPanel, Loading, Restrictions, useAsync } from "../components/ui";

export default function Citations() {
  const res = useAsync(loadCitationPolicy, []);
  const t = useT();
  if (res.state === "loading") return <Loading what={t("cit.loading")} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const p = res.data;

  const cases = [...new Set(p.restrictions.flatMap((r) => r.cases ?? []))].sort();

  return (
    <>
      <h2 className="view">{t("nav.citations")}</h2>
      <VerbatimNote />
      {/* The lede is this platform's own sentence, not the artifact's `note`. That note reads "the prose
          above explains each entry; this block is what a build reads" — true of the YAML it was written
          in, where the prose IS above, and false here, where the prose is the last section. Carrying an
          artifact's self-reference onto a page that reorders it produces a sentence that points at
          nothing. The note still appears, beside the prose it is talking about. */}
      <p className="lede">
        {t("cit.lede", { n: p.restrictions.length + p.non_case_restrictions.length })}
      </p>

      <div className={p.authoritative_for_tooling ? "note seal" : "note warn"}>
        <strong>{t(p.authoritative_for_tooling ? "cit.auth.yes" : "cit.auth.no")}</strong>{" "}
        <T k="cit.schema" v={{ schema: <span className="mono">{p.schema}</span> }} />
      </div>

      <section>
        <h3>{t("cit.h.cases", { n: p.restrictions.length })}</h3>
        <p style={{ color: "var(--fg-dim)", marginTop: 0 }}>
          {t("cit.casesCarrying")}{" "}
          {cases.map((c, n) => (
            <span key={c}>
              {n ? ", " : ""}
              <Link to={`/case/${c}`} className="mono">
                {c}
              </Link>
            </span>
          ))}
        </p>
        <Restrictions items={p.restrictions} />
      </section>

      <section>
        <h3>{t("cit.h.nonCase", { n: p.non_case_restrictions.length })}</h3>
        <Restrictions items={p.non_case_restrictions} />
      </section>

      <section>
        <h3>{t("cit.h.asWritten")}</h3>
        <div className="note" style={{ marginTop: 0 }}>
          <strong>{t("cit.fileNote")}</strong> <span lang="en">{p.note}</span>
        </div>
        <Body src={p.body_md} />
      </section>
    </>
  );
}
