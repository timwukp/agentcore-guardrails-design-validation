// The findings, in full. Not summarised.
//
// A finding is the unit of this study that carries a caveat, an alternative explanation, and the
// reason a verdict may not be read further than it goes. A dashboard that showed titles and a status
// chip would be showing precisely the layer above the one that matters, so each finding renders its
// whole body, with its provenance beside it — including, where the artifact says so, that it requires
// no replication and why.

import { useState } from "react";
import { loadFindings } from "../lib/data";
import { useT, VerbatimNote } from "../lib/i18n";
import { Body, ErrorPanel, Loading, RawJson, useAsync } from "../components/ui";

/** `absent` is the already-translated words for "the artifact recorded no status" — the ABSENCE is
 *  this platform's observation, so it is translated, while any status the artifact does carry is the
 *  artifact's own token and is not. */
function statusOf(p: Record<string, unknown>, absent: string): string {
  const s = p["status"];
  return typeof s === "string" && s.trim() ? s : absent;
}

export default function Findings() {
  const res = useAsync(loadFindings, []);
  const [open, setOpen] = useState<string | null>(null);
  const t = useT();

  if (res.state === "loading") return <Loading what={t("fnd.loading")} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const items = [...res.data.findings].sort((a, b) => a.file.localeCompare(b.file));
  const absent = t("fnd.noStatus");

  return (
    <>
      <h2 className="view">{t("nav.findings")}</h2>
      <VerbatimNote />
      <p className="lede">{t("fnd.lede", { n: items.length })}</p>

      <table className="grid" style={{ marginBottom: 22 }}>
        <thead>
          <tr>
            <th>{t("fnd.th.file")}</th>
            <th>{t("fnd.th.status")}</th>
            <th>{t("fnd.th.title")}</th>
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
                <span className="chip">{statusOf(f.provenance, absent)}</span>
              </td>
              <td lang="en">{f.title}</td>
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
          <h3 style={{ textTransform: "none" }} lang="en">
            {f.title}
          </h3>
          <div style={{ marginBottom: 10 }}>
            <span className="chip mono" style={{ textTransform: "none" }}>
              {f.file}
            </span>
            <span className="chip">{statusOf(f.provenance, absent)}</span>
            <span className="chip mono">sha256 {f.sha256.slice(0, 16)}…</span>
          </div>
          {typeof f.provenance["note"] === "string" ? (
            <div className="note" lang="en">
              {String(f.provenance["note"])}
            </div>
          ) : null}
          <RawJson label={t("fnd.provenance")} value={f.provenance} />
          <div style={{ marginTop: 12 }}>
            {open === f.file || items.length <= 8 ? (
              <Body src={f.body_md} />
            ) : (
              <details className="raw" open={open === f.file}>
                <summary>{t("fnd.read")}</summary>
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
