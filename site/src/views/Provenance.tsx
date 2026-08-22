// Governance view — where every byte on this site came from.
//
// THE MANIFEST IS CHECKED HERE, NOT JUST DISPLAYED
//
// A build manifest that is only rendered is decoration: it will list hashes nobody compares and
// relationships nobody tests. So this page recomputes the manifest's own internal arithmetic in front
// of the reader — that the output count matches the number of hashed outputs plus the manifest itself,
// that every hashed output has a provenance entry and every provenance entry a hash, and that no output
// claims to have been derived from nothing. Each of those can fail, and a failure is stated as a
// defect in the build rather than smoothed into a total.
//
// The hashes are the point. Every input hash is of the bytes the build actually read, so a reader can
// prove which tree this payload came from; every output hash is of the bytes being served, so a reader
// who downloads one can prove it was not edited after the gate ran. The check is a local
// `shasum -a 256` — no tooling of ours is involved in verifying us.

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { loadManifest } from "../lib/data";
import { T, useT, VerbatimNote } from "../lib/i18n";
import { ErrorPanel, KV, Loading, useAsync } from "../components/ui";
import type { Manifest } from "../lib/types";

/** The manifest's internal consistency, recomputed. Each field is a claim the manifest makes about
 *  itself; a reader should not have to take any of them on trust. */
function audit(m: Manifest) {
  const outputs = Object.keys(m.outputs_sha256);
  const prov = Object.keys(m.provenance);
  const outSet = new Set(outputs);
  const provSet = new Set(prov);
  return {
    outputs,
    inputs: Object.keys(m.inputs_sha256),
    countsAgree: m.n_outputs === outputs.length + 1, // + MANIFEST.json, which cannot hash itself
    inputCountAgrees: m.n_inputs === Object.keys(m.inputs_sha256).length,
    hashedWithoutProvenance: outputs.filter((p) => !provSet.has(p)),
    provenanceWithoutHash: prov.filter((p) => p !== "MANIFEST.json" && !outSet.has(p)),
    derivedFromNothing: prov.filter((p) => (m.provenance[p] ?? []).length === 0),
    unusedInputs: Object.keys(m.inputs_sha256).filter(
      (i) => !prov.some((p) => (m.provenance[p] ?? []).includes(i)),
    ),
  };
}

function HashTable({
  rows,
  what,
  extra,
}: {
  rows: [string, string][];
  /** Already-translated words naming what is being filtered, supplied by the section around it. */
  what: string;
  extra?: (path: string) => ReactNode;
}) {
  const [q, setQ] = useState("");
  const t = useT();
  const needle = q.trim().toLowerCase();
  const shown = rows.filter(([p]) => !needle || p.toLowerCase().includes(needle));
  return (
    <>
      <div className="facets">
        <div className="facet">
          <label>{t("prv.filter", { what })}</label>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("prv.pathHint")} />
        </div>
        <div className="facet">
          <label>&nbsp;</label>
          <span className="count mono">{t("prv.shownOf", { n: shown.length, total: rows.length })}</span>
        </div>
      </div>
      <div className="scroll" style={{ maxHeight: 420 }}>
        <table className="grid">
          <thead>
            <tr>
              <th>{t("prv.th.path")}</th>
              <th>sha256</th>
              {extra ? <th>{t("prv.th.derivedFrom")}</th> : null}
            </tr>
          </thead>
          <tbody>
            {shown.map(([p, h]) => (
              <tr key={p}>
                <td className="mono">{p}</td>
                <td className="mono" style={{ fontSize: 11 }}>
                  {h}
                </td>
                {extra ? <td>{extra(p)}</td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function Provenance() {
  const res = useAsync(loadManifest, []);
  const t = useT();
  const m = res.state === "ok" ? res.data : null;
  const a = useMemo(() => (m ? audit(m) : null), [m]);

  if (res.state === "loading") return <Loading what={t("prv.loading")} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  if (!m || !a) return null;

  // Each problem is a whole translated sentence with its numbers substituted in, not English glued
  // around a count: the clause order differs between the two languages, and a half-translated defect
  // report is the one sentence on this page a reader must be able to act on.
  const problems = [
    !a.countsAgree &&
      t("prv.bad.outputCount", {
        declared: m.n_outputs,
        hashed: a.outputs.length,
        diff: m.n_outputs - a.outputs.length,
      }),
    !a.inputCountAgrees &&
      t("prv.bad.inputCount", { declared: m.n_inputs, hashed: a.inputs.length }),
    a.hashedWithoutProvenance.length &&
      t("prv.bad.noProvenance", {
        n: a.hashedWithoutProvenance.length,
        files: a.hashedWithoutProvenance.join(", "),
      }),
    a.provenanceWithoutHash.length &&
      t("prv.bad.noHash", {
        n: a.provenanceWithoutHash.length,
        files: a.provenanceWithoutHash.join(", "),
      }),
    a.derivedFromNothing.length &&
      t("prv.bad.noInputs", {
        n: a.derivedFromNothing.length,
        files: a.derivedFromNothing.join(", "),
      }),
  ].filter((x): x is string => typeof x === "string" && x.length > 0);

  return (
    <>
      <h2 className="view">{t("nav.provenance")}</h2>
      <VerbatimNote />
      <p className="lede">{t("prv.lede")}</p>

      <div className={problems.length ? "note warn" : "note seal"}>
        {problems.length ? (
          <>
            <strong>{t("prv.disagrees")}</strong>
            <ul style={{ margin: "8px 0 0 18px" }}>
              {problems.map((p, n) => (
                <li key={n}>{p}</li>
              ))}
            </ul>
          </>
        ) : (
          <>
            <strong>{t("prv.agrees")}</strong>{" "}
            {t("prv.agrees.detail", {
              outputs: a.outputs.length,
              nOutputs: m.n_outputs,
              inputs: a.inputs.length,
              nInputs: m.n_inputs,
            })}
          </>
        )}
      </div>

      <KV
        rows={[
          [t("prv.kv.stamp"), <span className="mono">{m.build_stamp}</span>],
          [t("prv.kv.producedBy"), <span className="mono">{m.tool}</span>],
          [t("prv.kv.inputsRead"), <span className="num">{m.n_inputs}</span>],
          [t("prv.kv.outputsWritten"), <span className="num">{m.n_outputs}</span>],
          [
            t("prv.kv.howToVerify"),
            <T
              k="prv.kv.howToVerify.body"
              // A command the reader runs, so it is marked English inside the translated sentence
              // that tells them to run it — same reason as the audit page's command block.
              v={{
                cmd: (
                  <span className="mono" lang="en">
                    shasum -a 256 &lt;file&gt;
                  </span>
                ),
              }}
            />,
          ],
        ]}
      />

      <div className="note" lang="en">
        {m.note}
      </div>

      <section>
        <h3>{t("prv.h.inputs", { n: a.inputs.length })}</h3>
        <p style={{ color: "var(--fg-dim)", marginTop: 0 }}>{t("prv.inputs.note")}</p>
        {a.unusedInputs.length ? (
          <div className="note">
            <T
              k="prv.unusedInputs"
              v={{
                n: a.unusedInputs.length,
                files: <span className="mono">{a.unusedInputs.join(", ")}</span>,
              }}
            />
          </div>
        ) : null}
        <HashTable rows={Object.entries(m.inputs_sha256).sort()} what={t("prv.what.inputs")} />
      </section>

      <section>
        <h3>{t("prv.h.outputs", { n: a.outputs.length })}</h3>
        <p style={{ color: "var(--fg-dim)", marginTop: 0 }}>{t("prv.outputs.note")}</p>
        <HashTable
          rows={Object.entries(m.outputs_sha256).sort()}
          what={t("prv.what.outputs")}
          extra={(p) => {
            const src = m.provenance[p] ?? [];
            return (
              <details>
                <summary className="mono" style={{ fontSize: 11.5 }}>
                  {t("prv.nInputs", { n: src.length })}
                </summary>
                {/* The input file names this output was derived from — repository paths, marked
                    English like every other path on the site. */}
                <div
                  className="mono"
                  lang="en"
                  style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 4 }}
                >
                  {src.join("\n")}
                </div>
              </details>
            );
          }}
        />
      </section>
    </>
  );
}
