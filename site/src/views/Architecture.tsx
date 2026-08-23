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

import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { loadArchitecture } from "../lib/data";
import { statusClass } from "../lib/audit";
import { ErrorPanel, Loading, useAsync, VerdictBadge } from "../components/ui";
import { A, T, useAuthored, useT, VerbatimNote } from "../lib/i18n";
import type { ArchBox, ArchDiagram, ArchEdge, Architecture } from "../lib/types";

/** How much smaller than its own coordinate space each diagram is drawn. The layout is generous — a
 *  200×96 box on a 148 px row pitch — because it was computed for provable separation rather than for a
 *  laptop screen, and the whole width has to be visible at once for the topology to be readable at all.
 *  Scaling the CONTAINER, not the coordinates, keeps the served geometry the geometry the test asserted. */
const SCALE = 0.72;

/** Which of the payload's diagrams belong to this page. The vocabulary is authored in
 *  `platform/curation/architecture.yaml` and checked there, so a value that no diagram declares fails
 *  the build rather than rendering a page with nothing on it. */
const VIEW = "architecture";

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
  const authored = useAuthored();
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={sel}
      // `box.satellite` is derived in `build_site_data`, where the layout that depends on the same rule
      // reads it. This tested `box.kind === "property"` until 2026-08-23, which was a name list standing
      // in for a property: the `alternative` kind added on the closed-loop diagram has the identical
      // geometry — one parent, no children, its parent's row — and would have been drawn full-width in
      // its parent's lane with nothing failing (`feedback_scope_as_namelist`).
      className={`archbox ${statusClass(box.status)} ${sel ? "on" : ""} ${box.satellite ? "prop" : ""}`}
      style={{ left: box.x, top: box.y, width: box.w, height: box.h }}
      // A `title` is a plain string, so this resolves the value rather than rendering `<A>`: there is no
      // element to hang `lang` on inside an attribute. The tooltip is a CONVENIENCE and nothing rests on
      // it — a tooltip is absent on touch, absent to the keyboard and unreliable to a screen reader, so
      // the same sentence is visible text in the legend above the diagram. It was the only carrier until
      // 2026-08-22, which is how five translated sentences came to render nowhere at all.
      title={authored(box.status_label).text}
    >
      <A v={box.label} className="lab" />
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
  // Resolved here rather than rendered through `<A>` because each of these four needs its `lang` on an
  // element `<A>` does not own — a heading, and three paragraphs one of which keeps its newlines. The
  // resolution is the same one either way, so a panel cannot mark a Chinese sentence `lang="en"`.
  const authored = useAuthored();
  const label = authored(box.label);
  const detail = authored(box.detail);
  const whyThese = authored(box.why_these_cases);
  const whyNot = authored(box.why_not_measured);
  const nonCiting = new Set(arch.non_colouring_restrictions);
  return (
    <div className={`archpanel ${statusClass(box.status)}`}>
      <div className="head">
        <h4 lang={label.lang}>{label.text}</h4>
        <span className={`badge ${statusClass(box.status)}`} lang="en">
          {box.status.replace(/_/g, " ")}
        </span>
      </div>
      {/* `detail`, `why_this_status` and `why_these_cases` are the authored topology file's own
          sentences, quoted rather than paraphrased for the same reason `oracle_text` is — a second
          wording of a claim about a component is a claim whose only provenance is the wording.

          `status_label` is NOT one of them, and this comment named it as one until 2026-08-22. It is
          `build_site_data.ARCH_STATUS_LABEL[box.status]`: five sentences this platform wrote to say what
          each colour means. Quoting those verbatim gave a Chinese reader the legend to the whole picture
          in English, so they are `Authored` and render through `<A>`. */}
      <p className="what" lang={detail.lang}>
        {detail.text.trim()}
      </p>
      <p className="why">
        <strong>{t("arc.whyColour")}</strong> <span lang="en">{box.why_this_status}</span>
      </p>
      <p className="why">
        <strong>{t("arc.colourMeans")}</strong> <A v={box.status_label} />
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
          <div style={{ marginTop: 6, whiteSpace: "pre-wrap" }} lang={whyNot.lang}>
            {whyNot.text.trim()}
          </div>
        </div>
      ) : (
        <>
          <p className="why">
            <strong>{t("arc.whyTheseCases")}</strong>{" "}
            <span lang={whyThese.lang}>{whyThese.text.trim()}</span>
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
  const authored = useAuthored();
  const label = authored(d.label);
  const subtitle = authored(d.subtitle);
  const whyDiagram = authored(d.why_this_diagram);
  const v = d.viewbox;
  const chosen = d.boxes.find((b) => b.id === sel) ?? null;

  return (
    <section className="archsec">
      <h3 lang={label.lang}>{label.text}</h3>
      <p className="lede" lang={subtitle.lang}>
        {subtitle.text.trim()}
      </p>

      {/* Four columns — swatch, payload key, count, meaning — one row per status.

          The meaning used to be a `title` attribute on the row. That is not a small difference: the
          browser census of 2026-08-22 walked both locales over every route and found all five of these
          sentences rendering nowhere as text, because a tooltip is not text. So the five sentences
          this platform wrote to explain its own colours were unreadable without a hover on the very
          page whose picture they are the key to, and translating them changed nothing for the reader
          who needed the translation.

          `lang="en"` sits on the KEY only. `not_established` is a payload identifier a reader greps
          for and stays English in both languages; the sentence beside it is translated and would
          inherit the wrong font stack and the wrong screen-reader phonology from an outer `lang`. */}
      <div className="archlegend">
        {Object.entries(arch.status_labels).map(([s, label]) => (
          <Fragment key={s}>
            <span className={`swcell ${statusClass(s)}`}>
              <span className="sw" />
            </span>
            <span lang="en">{s.replace(/_/g, " ")}</span>
            <span className="n">{d.boxes_by_status[s] ?? 0}</span>
            <A v={label} className="means" />
          </Fragment>
        ))}
      </div>

      <div className="archscroll">
        <div
          className="archcanvas"
          style={{ width: v.width * SCALE, height: v.height * SCALE }}
          role="group"
          aria-label={`${label.text}: ${t("arc.aria", { boxes: d.n_boxes, edges: d.n_edges })}`}
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
        <p style={{ whiteSpace: "pre-wrap", marginBottom: 0 }} lang={whyDiagram.lang}>
          {whyDiagram.text.trim()}
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

      {/* Filtered on the payload's own `view` key, not on a list of diagram ids kept here. The
          closed-loop picture is the recommended DESIGN; this page is what the study measured, and the
          two answer different questions — drawing the design here beside "what the study looked at"
          would read as a claim that the design is what was tested. A page that named the diagrams it
          draws would silently gain the next one added; a page that filters on the property gains
          nothing it did not ask for, and `check_architecture.py` fails the build on a view no diagram
          uses, so a typo here cannot quietly empty the page. */}
      {arch.diagrams
        .filter((d) => d.view === VIEW)
        .map((d) => (
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
