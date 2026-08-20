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
  what: string;
  extra?: (path: string) => ReactNode;
}) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const shown = rows.filter(([p]) => !needle || p.toLowerCase().includes(needle));
  return (
    <>
      <div className="facets">
        <div className="facet">
          <label>filter {what}</label>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="path fragment" />
        </div>
        <div className="facet">
          <label>&nbsp;</label>
          <span className="count mono">
            {shown.length} of {rows.length} shown
          </span>
        </div>
      </div>
      <div className="scroll" style={{ maxHeight: 420 }}>
        <table className="grid">
          <thead>
            <tr>
              <th>path</th>
              <th>sha256</th>
              {extra ? <th>derived from</th> : null}
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
  const m = res.state === "ok" ? res.data : null;
  const a = useMemo(() => (m ? audit(m) : null), [m]);

  if (res.state === "loading") return <Loading what="the build manifest" />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  if (!m || !a) return null;

  const problems = [
    !a.countsAgree &&
      `The manifest declares ${m.n_outputs} outputs but hashes ${a.outputs.length}; those differ by ${
        m.n_outputs - a.outputs.length
      }, and only MANIFEST.json is expected to be unhashed.`,
    !a.inputCountAgrees &&
      `The manifest declares ${m.n_inputs} inputs but hashes ${a.inputs.length}.`,
    a.hashedWithoutProvenance.length &&
      `${a.hashedWithoutProvenance.length} hashed output(s) have no provenance entry: ${a.hashedWithoutProvenance.join(", ")}.`,
    a.provenanceWithoutHash.length &&
      `${a.provenanceWithoutHash.length} provenance entr(ies) name a file that was not hashed: ${a.provenanceWithoutHash.join(", ")}.`,
    a.derivedFromNothing.length &&
      `${a.derivedFromNothing.length} output(s) declare no inputs at all: ${a.derivedFromNothing.join(", ")}. An output derived from nothing is either a constant the build invented or a read it did not record.`,
  ].filter((x): x is string => typeof x === "string" && x.length > 0);

  return (
    <>
      <h2 className="view">Provenance</h2>
      <p className="lede">
        This payload was produced by one program from one tree, and both are named here by hash. Nothing
        on this site was typed; every number was derived, and this is the record of what it was derived
        from.
      </p>

      <div className={problems.length ? "note warn" : "note seal"}>
        {problems.length ? (
          <>
            <strong>The manifest does not agree with itself.</strong>
            <ul style={{ margin: "8px 0 0 18px" }}>
              {problems.map((p, n) => (
                <li key={n}>{p}</li>
              ))}
            </ul>
          </>
        ) : (
          <>
            <strong>The manifest agrees with itself.</strong> {a.outputs.length} hashed outputs plus
            MANIFEST.json equals the declared {m.n_outputs}; {a.inputs.length} hashed inputs equals the
            declared {m.n_inputs}; every hashed output has a provenance entry and every provenance entry a
            hash; no output claims to have been derived from nothing. Checked in the browser, from the
            file, on load.
          </>
        )}
      </div>

      <KV
        rows={[
          ["build stamp", <span className="mono">{m.build_stamp}</span>],
          ["produced by", <span className="mono">{m.tool}</span>],
          ["inputs read", <span className="num">{m.n_inputs}</span>],
          ["outputs written", <span className="num">{m.n_outputs}</span>],
          [
            "how to verify one",
            <>
              <span className="mono">shasum -a 256 &lt;file&gt;</span> — for an input, against the repo
              tree at that stamp; for an output, against the JSON this site fetched. Both hashes are below.
            </>,
          ],
        ]}
      />

      <div className="note">{m.note}</div>

      <section>
        <h3>Inputs — the bytes the build read ({a.inputs.length})</h3>
        <p style={{ color: "var(--fg-dim)", marginTop: 0 }}>
          These are repository paths. A hash here proves which revision of a sealed artifact this payload
          was built from, which is the only way to tell a re-derivation from a re-authoring.
        </p>
        {a.unusedInputs.length ? (
          <div className="note">
            {a.unusedInputs.length} input(s) were hashed but are not named by any output's provenance:{" "}
            <span className="mono">{a.unusedInputs.join(", ")}</span>. That is expected for files read to
            be verified rather than to be rendered — a seal is read to check it, not to publish it — and it
            is listed rather than filtered so the distinction stays visible.
          </div>
        ) : null}
        <HashTable rows={Object.entries(m.inputs_sha256).sort()} what="inputs" />
      </section>

      <section>
        <h3>Outputs — the bytes this site serves ({a.outputs.length})</h3>
        <p style={{ color: "var(--fg-dim)", marginTop: 0 }}>
          Each output's provenance is the set of inputs whose bytes it was derived from. MANIFEST.json is
          the one output with no hash of its own, because a file cannot contain its own digest.
        </p>
        <HashTable
          rows={Object.entries(m.outputs_sha256).sort()}
          what="outputs"
          extra={(p) => {
            const src = m.provenance[p] ?? [];
            return (
              <details>
                <summary className="mono" style={{ fontSize: 11.5 }}>
                  {src.length} input{src.length === 1 ? "" : "s"}
                </summary>
                <div className="mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 4 }}>
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
