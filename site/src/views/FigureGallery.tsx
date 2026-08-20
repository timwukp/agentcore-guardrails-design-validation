// View 4 — the canonical figures, with a freshness state that can say "not verified".
//
// WHY THESE ARE PNGs AND NOT CHARTS DRAWN IN THE BROWSER
//
// Each figure is the matplotlib PNG the whitepaper cites, served as-is. Re-drawing them in a
// JavaScript charting library would produce a SECOND rendering of the same measurements, and two
// renderings can disagree — at which point the dashboard and the paper make different claims about
// one number and a reader has no way to tell which is the artifact. The PNGs also already have a
// numeric verifier (`tools/whitepaper_figures.py --check`) that compares the numbers the figures were
// drawn from, never the pixels, because rendered bytes move with matplotlib and freetype versions
// while the measurements do not.
//
// THE FRESHNESS BADGE MUST BE ABLE TO SAY "UNKNOWN"
//
// `figures.numeric_check` is the rc of that verifier, and it is `null` when the build did not run it.
// `null` is rendered as NOT VERIFIED, never as fresh. A badge whose only states are pass and fail has
// to pick one for "the check did not run", and picking pass is how a stale figure gets a green tick.

import { Link } from "react-router-dom";
import { figureUrl, loadFigures, loadRegisters } from "../lib/data";
import { ErrorPanel, Loading, RawJson, useAsync } from "../components/ui";

function FreshnessBadge({ rc }: { rc: number | null }) {
  if (rc === null) return <span className="badge restrict">NOT VERIFIED — the check did not run</span>;
  if (rc === 0) return <span className="badge v-TRUE">numbers verified (rc 0)</span>;
  return <span className="badge v-FALSE">numbers drifted (rc {rc})</span>;
}

export default function FigureGallery() {
  const figs = useAsync(loadFigures, []);
  const regs = useAsync(loadRegisters, []);

  if (figs.state === "loading") return <Loading what="figures" />;
  if (figs.state === "error") return <ErrorPanel error={figs.error} />;
  const f = figs.data;

  const keys = Object.keys(f.manifest.figures).sort();
  const present = new Map(f.present.map((p) => [p.file.replace(/\.png$/, ""), p]));

  return (
    <>
      <h2 className="view">Figures</h2>
      <p className="lede">
        The figures the whitepaper cites, served as the exact PNGs it was written against, each beside
        the numeric specification it was drawn from.
      </p>

      <div className={f.numeric_check === 0 ? "note" : "note warn"}>
        <FreshnessBadge rc={f.numeric_check} />
        <div style={{ marginTop: 8 }}>{f.numeric_check_note}</div>
        {f.numeric_check !== null && f.numeric_check !== 0 ? (
          <div style={{ marginTop: 8 }}>
            <strong>What a drift means, concretely:</strong> a figure on this page shows a number that
            re-deriving from today's artifacts does not reproduce. The figures are NOT redrawn to make
            this badge go green — the PNGs are what the whitepaper was written against, and silently
            re-rendering them would change a published figure to match a later measurement while the
            paper's sentences still describe the earlier one. The drift is the finding; closing it is a
            document decision, not a build step.
          </div>
        ) : null}
        <div style={{ marginTop: 6, fontSize: 12, color: "var(--fg-faint)" }}>
          {f.manifest.note}
        </div>
        <div style={{ marginTop: 6, fontSize: 12, color: "var(--fg-faint)" }} className="mono">
          {f.manifest.generated_by} · matplotlib {f.manifest.matplotlib}
        </div>
      </div>

      <div className="note">
        <strong>What no gate on this platform can check about these images:</strong>{" "}
        {f.redaction_note}
      </div>

      {keys.map((key) => {
        const p = present.get(key);
        const spec = f.manifest.figures[key];
        // Which register items discuss this figure — derived by searching their text, so a figure that
        // cannot currently be drawn links to the item that says why instead of to a sentence here.
        const named =
          regs.state === "ok"
            ? regs.data.items.filter(
                (it) =>
                  it.body_md.includes(key) ||
                  it.body_md.includes(key.replace(/^fig-0?/, "figure ")) ||
                  it.title.includes(key),
              )
            : [];
        return (
          <div className="figrow" key={key}>
            <div className="head">
              <strong className="mono">{key}</strong>
              {p ? (
                <span className="chip">
                  {p.bytes.toLocaleString()} bytes · sha256 {p.sha256.slice(0, 12)}…
                </span>
              ) : (
                <span className="badge restrict">not present in this build</span>
              )}
            </div>

            {p ? (
              <img src={figureUrl(p.file)} alt={`${key} — see the numeric specification below`} />
            ) : (
              <div className="note warn" style={{ marginTop: 10, marginBottom: 0 }}>
                <strong>This figure was not produced.</strong> It is listed in the figure manifest, so
                it is planned rather than forgotten, and its absence is rendered here rather than
                omitted — a gallery that simply skipped it would show seven figures and imply seven
                were intended.
                {named.length ? (
                  <div style={{ marginTop: 8 }}>
                    The deficiency register discusses it:{" "}
                    {named.map((it, n) => (
                      <span key={it.n}>
                        {n ? ", " : ""}
                        <Link to="/register">item {it.n} — {it.title}</Link>
                      </span>
                    ))}
                    .
                  </div>
                ) : null}
              </div>
            )}

            <div style={{ marginTop: 10 }}>
              <RawJson label="numeric specification this figure must reproduce" value={spec} />
            </div>
          </div>
        );
      })}

      {f.missing.length ? (
        <div className="note warn">
          The build reports {f.missing.length} figure(s) missing: {f.missing.join(", ")}.
        </div>
      ) : null}
    </>
  );
}
