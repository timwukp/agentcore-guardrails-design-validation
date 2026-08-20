// The findings, in full. Not summarised.
//
// A finding is the unit of this study that carries a caveat, an alternative explanation, and the
// reason a verdict may not be read further than it goes. A dashboard that showed titles and a status
// chip would be showing precisely the layer above the one that matters, so each finding renders its
// whole body, with its provenance beside it — including, where the artifact says so, that it requires
// no replication and why.

import { useState } from "react";
import { loadFindings } from "../lib/data";
import { Body, ErrorPanel, Loading, RawJson, useAsync } from "../components/ui";

function statusOf(p: Record<string, unknown>): string {
  const s = p["status"];
  return typeof s === "string" && s.trim() ? s : "no status recorded";
}

export default function Findings() {
  const res = useAsync(loadFindings, []);
  const [open, setOpen] = useState<string | null>(null);

  if (res.state === "loading") return <Loading what="findings" />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const items = [...res.data.findings].sort((a, b) => a.file.localeCompare(b.file));

  return (
    <>
      <h2 className="view">Findings</h2>
      <p className="lede">
        {items.length} findings, each rendered from the markdown file it is stored as, with the hash of
        those bytes. A finding is where a verdict's meaning is bounded; the summary is not the finding.
      </p>

      <table className="grid" style={{ marginBottom: 22 }}>
        <thead>
          <tr>
            <th>file</th>
            <th>status</th>
            <th>title</th>
          </tr>
        </thead>
        <tbody>
          {items.map((f) => (
            <tr key={f.file}>
              <td className="mono">
                <a
                  href={`#/findings`}
                  onClick={(e) => {
                    e.preventDefault();
                    setOpen(f.file);
                    document.getElementById(f.file)?.scrollIntoView({ behavior: "smooth" });
                  }}
                >
                  {f.file}
                </a>
              </td>
              <td>
                <span className="chip">{statusOf(f.provenance)}</span>
              </td>
              <td>{f.title}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {items.map((f) => (
        <section key={f.file} id={f.file}>
          {/* The heading is the finding's own title, not its filename. `h3` is styled uppercase, which
              turned `FINDING-F1-1.md` into `…MD` and, worse, left a collapsed finding identified only
              by a path — the one line a reader scanning for the relevant finding needs is the sentence
              that says what was found. The filename stays, as a chip, because it is the citable name. */}
          {/* Not uppercased: `h3` shouts by default, which suits a short section label and not a
              100-character sentence. */}
          <h3 style={{ textTransform: "none" }}>{f.title}</h3>
          <div style={{ marginBottom: 10 }}>
            <span className="chip mono" style={{ textTransform: "none" }}>
              {f.file}
            </span>
            <span className="chip">{statusOf(f.provenance)}</span>
            <span className="chip mono">sha256 {f.sha256.slice(0, 16)}…</span>
          </div>
          {typeof f.provenance["note"] === "string" ? (
            <div className="note">{String(f.provenance["note"])}</div>
          ) : null}
          <RawJson label="provenance" value={f.provenance} />
          <div style={{ marginTop: 12 }}>
            {open === f.file || items.length <= 8 ? (
              <Body src={f.body_md} />
            ) : (
              <details className="raw" open={open === f.file}>
                <summary>read the finding</summary>
                <div>
                  <Body src={f.body_md} />
                </div>
              </details>
            )}
          </div>
        </section>
      ))}
    </>
  );
}
