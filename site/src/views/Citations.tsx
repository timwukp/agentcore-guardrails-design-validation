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
import { Body, ErrorPanel, Loading, Restrictions, useAsync } from "../components/ui";

export default function Citations() {
  const res = useAsync(loadCitationPolicy, []);
  if (res.state === "loading") return <Loading what="the citation policy" />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const p = res.data;

  const cases = [...new Set(p.restrictions.flatMap((r) => r.cases ?? []))].sort();

  return (
    <>
      <h2 className="view">Citation policy</h2>
      {/* The lede is this platform's own sentence, not the artifact's `note`. That note reads "the prose
          above explains each entry; this block is what a build reads" — true of the YAML it was written
          in, where the prose IS above, and false here, where the prose is the last section. Carrying an
          artifact's self-reference onto a page that reorders it produces a sentence that points at
          nothing. The note still appears, beside the prose it is talking about. */}
      <p className="lede">
        What these {p.restrictions.length + p.non_case_restrictions.length} restrictions do is govern
        what a verdict may be quoted as saying. A verdict is not automatically a citable fact: a TRUE can
        rest on a measurement too narrow for the sentence it would be quoted in, a RECORDED is an
        observation whose oracle could not adjudicate it, and an INCONCLUSIVE licenses no amendment in
        either direction. Each entry below names the artifact that establishes it, and every case page
        renders its own restrictions from this same file.
      </p>

      <div className={p.authoritative_for_tooling ? "note seal" : "note warn"}>
        <strong>
          {p.authoritative_for_tooling
            ? "This file is authoritative for tooling."
            : "This file is NOT marked authoritative for tooling."}
        </strong>{" "}
        Schema <span className="mono">{p.schema}</span>. Every restriction below is rendered on the
        case pages it names, from this same file, so the rule and its display cannot drift apart.
      </div>

      <section>
        <h3>Restrictions that name specific cases ({p.restrictions.length})</h3>
        <p style={{ color: "var(--fg-dim)", marginTop: 0 }}>
          Cases carrying a restriction:{" "}
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
        <h3>Restrictions that are not about a single case ({p.non_case_restrictions.length})</h3>
        <Restrictions items={p.non_case_restrictions} />
      </section>

      <section>
        <h3>The policy as written</h3>
        <div className="note" style={{ marginTop: 0 }}>
          <strong>The file's own note on this prose:</strong> {p.note}
        </div>
        <Body src={p.body_md} />
      </section>
    </>
  );
}
