// The design diagrams: how a verdict is made, and what the study looked at.
//
// WHY THIS PAGE IS RENDERED FROM COORDINATES IT DOES NOT COMPUTE
//
// Every box position and every polyline point arrives in `architecture.json`, computed by
// `build_site_data._layout()` from the authored edges. `test_architecture_layout.py` then asserts, as
// EQUALITIES, that no two edge segments cross and no segment passes through a box. That assertion is
// what licenses publishing the picture at all — two arrows meeting where no relation exists read as a
// relation, and an architecture diagram is the artifact most likely to be screenshotted and quoted with
// no text beside it. A view that nudged a coordinate to make something look better would invalidate the
// proof while leaving the test green, so nothing below computes geometry: it reads it.
//
// WHY HTML BOXES WITH AN SVG OVERLAY, RATHER THAN AN SVG OF EVERYTHING
//
// The boxes carry a label, a status badge, a count and a click target. In pure SVG each of those is
// hand-positioned `<text>` with no wrapping, no ellipsis and no focus ring; `<foreignObject>` gets the
// layout back but is the least reliably printed and least reliably read-aloud element in SVG. So the
// polylines — which are geometry and nothing else — are an SVG layer, and the boxes are absolutely
// positioned HTML at the same coordinates, in the same scaled coordinate space. The reader gets real
// text; the arrows keep the derived geometry.
//
// WHY THE COLOURS ARE WHAT THEY ARE
//
// Five statuses, and the ordering rule behind them is the load-bearing part: one citable FALSE outranks
// any number of TRUEs. A component with four TRUEs and one FALSE is a component with a finding, and a
// green box would bury it. `not_measured` is deliberately loud rather than pale — an uncoloured box
// reads as "nothing to worry about", where what it means is that this study never looked. And a box
// whose only support is a non-citable case is `context_only`: coloured by none of its cases, because a
// restriction that says "cite this as nothing" cannot make a component green.
//
// The class names are DERIVED from the payload token (`st-<status>`, `e-<route>`), and
// `check_site_invariants.py` greps the built stylesheet for exactly those shapes — so a status added to
// the vocabulary later fails the publish rather than shipping as an unstyled box.

import { useState } from "react";
import { Link } from "react-router-dom";
import { loadArchitecture } from "../lib/data";
import { statusClass } from "../lib/audit";
import { ErrorPanel, Loading, useAsync, VerdictBadge } from "../components/ui";
import { T, useT, VerbatimNote } from "../lib/i18n";
import type { ArchBox, ArchDiagram, ArchEdge, Architecture } from "../lib/types";

/** How much smaller than its own coordinate space each diagram is drawn. The layout is generous — a
 *  200×96 box on a 148 px row pitch — because it was computed for provable separation rather than for a
 *  laptop screen, and the whole width has to be visible at once for the topology to be readable at all.
 *  Scaling the CONTAINER, not the coordinates, keeps the served geometry the geometry the test asserted. */
const SCALE = 0.72;

/** `spine` -> `e-spine`, same derivation as the status classes and for the same reason: a route added to
 *  the payload later must fail the stylesheet check rather than render as an unremarkable line. */
const routeClass = (r: string) => `e-${r.toLowerCase()}`;

function points(e: ArchEdge): string {
  return e.points.map(([x, y]) => `${x},${y}`).join(" ");
}

/** The arrowhead, drawn at the last segment's direction. In SVG a marker would need one `<defs>` entry
 *  per stroke colour to avoid inheriting the wrong one; three explicit points cost less and cannot
 *  disagree with the line they terminate. */
function head(e: ArchEdge): string {
  const n = e.points.length;
  const [px, py] = e.points[n - 2] ?? e.points[n - 1] ?? [0, 0];
  const [x, y] = e.points[n - 1] ?? [0, 0];
  const s = 5;
  if (x === px) {
    const dir = y > py ? 1 : -1;
    return `${x},${y} ${x - s},${y - s * dir} ${x + s},${y - s * dir}`;
  }
  const dir = x > px ? 1 : -1;
  return `${x},${y} ${x - s * dir},${y - s} ${x - s * dir},${y + s}`;
}

/** The verdict mix on the face of a box, as `T10 F2 I2` rather than a bar.
 *
 *  A stacked bar here would be a proportion, and a proportion over these four is the pass rate this
 *  platform refuses to compute: FALSE is a finding rather than a failure, and INCONCLUSIVE is a result
 *  rather than a missing one. Four counts side by side say the same thing without inviting the division.
 *  The verdict class names stay UPPERCASE, matching `.v-TRUE` in the stylesheet and `VerdictBadge`. */
function Mix({ mix }: { mix: Record<string, number> }) {
  const entries = Object.entries(mix).sort(([a], [b]) => a.localeCompare(b));
  if (!entries.length) return null;
  return (
    <span className="archmix">
      {entries.map(([v, n]) => (
        <span key={v} className={`badge v-${v}`} title={`${n} ${v}`}>
          {v.slice(0, 1)}
          {n}
        </span>
      ))}
    </span>
  );
}

function Box({ box, sel, onSelect }: { box: ArchBox; sel: boolean; onSelect: () => void }) {
  const t = useT();
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={sel}
      className={`archbox ${statusClass(box.status)} ${sel ? "on" : ""} ${
        box.kind === "property" ? "prop" : ""
      }`}
      style={{ left: box.x, top: box.y, width: box.w, height: box.h }}
      title={box.status_label}
    >
      <span className="lab" lang="en">
        {box.label}
      </span>
      <span className="meta">
        {box.count !== null ? <span className="cnt">{box.count}</span> : null}
        {box.n_cases ? (
          <Mix mix={box.verdict_mix} />
        ) : (
          <span className="none">{t("arc.notMeasured")}</span>
        )}
      </span>
    </button>
  );
}

function Panel({ box, arch }: { box: ArchBox; arch: Architecture }) {
  const t = useT();
  const nonCiting = new Set(arch.non_colouring_restrictions);
  return (
    <div className={`archpanel ${statusClass(box.status)}`}>
      <div className="head">
        <h4 lang="en">{box.label}</h4>
        <span className={`badge ${statusClass(box.status)}`} lang="en">
          {box.status.replace(/_/g, " ")}
        </span>
      </div>
      {/* `detail`, `why_this_status`, `status_label` and `why_these_cases` are the authored topology
          file's own sentences. They are quoted, not paraphrased, for the same reason `oracle_text` is. */}
      <p className="what" lang="en">
        {box.detail.trim()}
      </p>
      <p className="why">
        <strong>{t("arc.whyColour")}</strong> <span lang="en">{box.why_this_status}</span>
      </p>
      <p className="why">
        <strong>{t("arc.colourMeans")}</strong> <span lang="en">{box.status_label}</span>
      </p>

      <table className="grid archkv">
        <tbody>
          <tr>
            <th>{t("arc.kv.kind")}</th>
            <td className="mono">{box.kind}</td>
          </tr>
          {box.program ? (
            <tr>
              <th>{t("arc.kv.program")}</th>
              <td className="mono">{box.program}</td>
            </tr>
          ) : null}
          {box.venv !== "none" ? (
            <tr>
              <th>{t("arc.kv.venv")}</th>
              <td className="mono">{box.venv}</td>
            </tr>
          ) : null}
          {box.machine !== "none" ? (
            <tr>
              <th>{t("arc.kv.machine")}</th>
              <td className="mono">{box.machine}</td>
            </tr>
          ) : null}
          {box.count_from ? (
            <tr>
              <th>{t("arc.kv.count")}</th>
              <td>
                <T
                  k="arc.kv.count.value"
                  v={{
                    n: <span className="mono">{box.count}</span>,
                    from: <span className="mono">{box.count_from}</span>,
                  }}
                />
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>

      {box.measured !== null ? (
        <div className="note warn">
          <strong>{t("arc.neverExamined")}</strong>
          <div style={{ marginTop: 6, whiteSpace: "pre-wrap" }} lang="en">
            {box.why_not_measured?.trim()}
          </div>
        </div>
      ) : (
        <>
          <p className="why">
            <strong>{t("arc.whyTheseCases")}</strong>{" "}
            <span lang="en">{box.why_these_cases?.trim()}</span>
          </p>
          <table className="grid">
            <thead>
              <tr>
                <th style={{ width: 78 }}>{t("pip.th.case")}</th>
                <th style={{ width: 108 }}>{t("arc.th.verdict")}</th>
                <th>{t("arc.th.decided")}</th>
              </tr>
            </thead>
            <tbody>
              {box.cases.map((c) => {
                const blocked = c.restrictions.filter((r) => nonCiting.has(r));
                return (
                  <tr key={c.case}>
                    <td>
                      <Link to={`/case/${c.case}`} className="mono">
                        {c.case}
                      </Link>
                    </td>
                    <td>
                      <VerdictBadge v={c.verdict} />
                    </td>
                    <td>
                      <span lang="en">{c.title}</span>
                      {c.restrictions.length ? (
                        <div style={{ marginTop: 3 }}>
                          {c.restrictions.map((r) => (
                            <span
                              key={r}
                              className={`chip ${blocked.includes(r) ? "blocked" : ""}`}
                              title={t(
                                blocked.includes(r) ? "arc.restrict.blocked" : "arc.restrict.scope",
                              )}
                            >
                              {r}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function Diagram({ d, arch }: { d: ArchDiagram; arch: Architecture }) {
  const [sel, setSel] = useState<string | null>(null);
  const t = useT();
  const v = d.viewbox;
  const chosen = d.boxes.find((b) => b.id === sel) ?? null;

  return (
    <section className="archsec">
      <h3 lang="en">{d.label}</h3>
      <p className="lede" lang="en">
        {d.subtitle.trim()}
      </p>

      <div className="archlegend">
        {Object.entries(arch.status_labels).map(([s, label]) => (
          <span key={s} className="item" title={label} lang="en">
            <span className={`sw ${statusClass(s)}`} />
            {s.replace(/_/g, " ")}
            <span className="n">{d.boxes_by_status[s] ?? 0}</span>
          </span>
        ))}
      </div>

      <div className="archscroll">
        <div
          className="archcanvas"
          style={{ width: v.width * SCALE, height: v.height * SCALE }}
          role="group"
          aria-label={`${d.label}: ${t("arc.aria", { boxes: d.n_boxes, edges: d.n_edges })}`}
        >
          <div
            className="archinner"
            style={{
              width: v.width,
              height: v.height,
              transform: `scale(${SCALE}) translate(${-v.min_x}px, ${-v.min_y}px)`,
            }}
          >
            <svg
              className="archedges"
              width={v.width}
              height={v.height}
              viewBox={`${v.min_x} ${v.min_y} ${v.width} ${v.height}`}
              aria-hidden="true"
            >
              {d.edges.map((e) => (
                <g key={`${e.from}->${e.to}`} className={routeClass(e.route)}>
                  <polyline points={points(e)} fill="none" />
                  <polygon points={head(e)} />
                </g>
              ))}
            </svg>
            {d.boxes.map((b) => (
              <Box key={b.id} box={b} sel={b.id === sel} onSelect={() => setSel(b.id === sel ? null : b.id)} />
            ))}
          </div>
        </div>
      </div>

      <p className="archhint">
        <T
          k="arc.hint"
          v={{
            boxes: d.n_boxes,
            edges: d.n_edges,
            test: <span className="mono">test_architecture_layout.py</span>,
          }}
        />
      </p>

      {chosen ? (
        <Panel box={chosen} arch={arch} />
      ) : (
        <div className="archpanel empty">
          <p style={{ margin: 0 }}>{t("arc.noSelection")}</p>
        </div>
      )}

      <details className="archwhy">
        <summary>{t("arc.whyDiagram")}</summary>
        <p style={{ whiteSpace: "pre-wrap", marginBottom: 0 }} lang="en">
          {d.why_this_diagram.trim()}
        </p>
      </details>
    </section>
  );
}

export default function ArchitectureView() {
  const res = useAsync(loadArchitecture, []);
  const t = useT();
  if (res.state === "loading") return <Loading what={t("arc.loading")} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const arch = res.data;

  return (
    <>
      <h2>{t("nav.architecture")}</h2>
      <VerbatimNote />
      <p className="lede">
        <T
          k="arc.lede"
          v={{ file: <span className="mono">platform/curation/architecture.yaml</span> }}
        />
      </p>

      {arch.diagrams.map((d) => (
        <Diagram key={d.id} d={d} arch={arch} />
      ))}

      <h3>{t("arc.h.coverage")}</h3>
      <p>
        {t("arc.coverage", {
          placed: arch.coverage.n_placed,
          registered: arch.coverage.n_registered,
          unplaced: arch.coverage.n_unplaced,
        })}{" "}
        <span lang="en">{arch.coverage.why}</span>
      </p>
      {arch.unplaced_cases.length ? (
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 78 }}>{t("pip.th.case")}</th>
              <th style={{ width: 108 }}>{t("arc.th.verdict")}</th>
              <th>{t("arc.th.whyUnplaced")}</th>
            </tr>
          </thead>
          <tbody>
            {arch.unplaced_cases.map((c) => (
              <tr key={c.case}>
                <td>
                  <Link to={`/case/${c.case}`} className="mono">
                    {c.case}
                  </Link>
                </td>
                <td>
                  <VerdictBadge v={c.verdict} />
                  {c.restrictions.map((r) => (
                    <span key={r} className="chip blocked" style={{ marginLeft: 4 }}>
                      {r}
                    </span>
                  ))}
                </td>
                <td style={{ whiteSpace: "pre-wrap" }} lang="en">
                  {c.why.trim()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <h3>{t("arc.h.metrics")}</h3>
      <p style={{ color: "var(--fg-dim)" }}>{t("arc.metrics.body")}</p>
      <table className="grid archmetrics">
        <tbody>
          {Object.entries(arch.metrics)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([k, n]) => (
              <tr key={k}>
                <th className="mono" style={{ width: 340 }}>
                  {k}
                </th>
                <td className="num">{n}</td>
              </tr>
            ))}
        </tbody>
      </table>

      <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 14 }}>
        <T
          k="arc.mappedBy"
          v={{
            // `mapped_by` is a self-description the curation file authored ("the maintainer of this
            // repository"), not a name this SPA can translate, so it is quoted like any other field.
            who: <span lang="en">{arch.mapped_by}</span>,
            when: <span className="mono">{arch.mapped_on}</span>,
          }}
        />{" "}
        <span lang="en">{arch.note}</span>
      </p>
    </>
  );
}
