// View 5 — the deficiency register, plus the side registers.
//
// THE COUNTDOWN IS DERIVED, NOT CONFIGURED
//
// Some register items are commitments with a date: an S3 lifecycle that will delete the only copy of
// certain day-1 call records, a comparison that is only meaningful in a particular billing period. A
// date in a paragraph is a date nobody is reminded of, so every ISO date appearing in any item is a
// candidate. Deliberately not "item 24's deadline" hardcoded here: the next item to acquire a deadline
// would then be invisible, and the register is a living document.
//
// WHICH DATES ARE IN, AND WHY THE CUTOFF IS THE BUILD STAMP RATHER THAN TODAY
//
// Filtering on "still in the future as the browser sees it" is the obvious rule and it has a specific
// failure: a deadline that passes with nothing done LEAVES the table instead of turning red. That is
// the "schedule that quietly stops" failure — the register's most urgent row disappears at exactly the
// moment it starts mattering, and the page looks calm.
//
// So membership is decided against the payload's own BUILD STAMP: a date is listed if it was in the
// future when this payload was derived, and the days remaining are then computed against the reader's
// today. A commitment that expired since the last publish stays on screen with a negative number,
// which also makes a stale publish visible. The window this opens is bounded by publish cadence, not
// by an arbitrary lookback, and it excludes the register's many working-day dates (2026-08-15 is named
// by 13 items) because those were already past when the build ran.
//
// The rule cannot tell a date an item COMMITS to from a date it merely MENTIONS, and does not try. A
// false positive is a row a reader dismisses; a false negative is a deleted artifact nobody was warned
// about. The footnote states this rather than leaving the reader to assume the list is curated.

import { useMemo, useState } from "react";
import { loadManifest, loadRegisters } from "../lib/data";
import { T, useT, VerbatimNote } from "../lib/i18n";
import { Body, ErrorPanel, Loading, useAsync } from "../components/ui";

/** A sentinel, not a label — see the note in `Claims.tsx`. */
const ANY = "*any*";

const ISO = /\b(20\d{2})-(\d{2})-(\d{2})\b/g;

/** `20260819T213444Z` -> `2026-08-19`, or null if the stamp is not that shape. Returning null rather
 *  than guessing keeps "the cutoff is unknown" distinguishable from "the cutoff is today". */
export function buildDateOf(stamp: string): string | null {
  const m = /^(\d{4})(\d{2})(\d{2})T/.exec(stamp);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : null;
}

/** ISO dates named by an item's text that fall strictly AFTER `cutoff` (an ISO date string; lexical
 *  comparison is exact for this format), with days remaining relative to `today`. Negative days mean
 *  the date has passed since the payload was built.
 *
 *  Strictly after, not on-or-after: a date equal to the build day is overwhelmingly a record of what
 *  happened that day rather than a commitment — the build stamp 2026-08-19 and the five items naming
 *  2026-08-19 as the day an incident was found are the same date — and rendering those as expired
 *  deadlines would put five red rows above the one real one. */
function deadlines(text: string, today: Date, cutoff: string): { date: string; days: number }[] {
  const out = new Map<string, number>();
  for (const m of text.matchAll(ISO)) {
    if (m[0] <= cutoff) continue;
    const d = new Date(`${m[0]}T00:00:00Z`);
    if (Number.isNaN(d.getTime())) continue;
    out.set(m[0], Math.round((d.getTime() - today.getTime()) / 86_400_000));
  }
  return [...out.entries()].map(([date, days]) => ({ date, days })).sort((a, b) => a.days - b.days);
}

export default function Register() {
  const res = useAsync(loadRegisters, []);
  const man = useAsync(loadManifest, []);
  const [tier, setTier] = useState(ANY);
  const t = useT();
  // Read once per mount: a countdown that recomputed on every render would tick inconsistently
  // between the items on one screen.
  const today = useMemo(() => {
    const n = new Date();
    return new Date(Date.UTC(n.getUTCFullYear(), n.getUTCMonth(), n.getUTCDate()));
  }, []);

  if (res.state === "loading") return <Loading what={t("reg.loading")} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;
  const r = res.data;

  const tiers = [...new Set(r.items.map((i) => i.tier))].sort();
  const items = r.items.filter((i) => tier === ANY || i.tier === tier).sort((a, b) => a.n - b.n);

  // The cutoff comes from the payload, so the table's membership is a property of the derivation and
  // not of when the page happened to be opened. If the manifest has not arrived (or carries a stamp
  // this parser does not recognise), fall back to the reader's today — which is the narrower, never the
  // wider, set: it can only omit rows, and the footnote below says the cutoff it used.
  const buildDate = man.state === "ok" ? buildDateOf(man.data.build_stamp) : null;
  const cutoff = buildDate ?? today.toISOString().slice(0, 10);
  const upcoming = r.items
    .flatMap((i) =>
      deadlines(`${i.title}\n${i.body_md}`, today, cutoff).map((d) => ({ ...d, n: i.n, title: i.title })),
    )
    .sort((a, b) => a.days - b.days);
  const expired = upcoming.filter((d) => d.days < 0).length;

  return (
    <>
      <h2 className="view">{t("nav.register")}</h2>
      <VerbatimNote />
      <p className="lede">{t("reg.lede", { n: r.n_items })}</p>

      {upcoming.length ? (
        <section>
          <h3>{t("reg.h.dates")}</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>{t("reg.th.date")}</th>
                <th>{t("reg.th.days")}</th>
                <th>{t("reg.th.item")}</th>
              </tr>
            </thead>
            <tbody>
              {upcoming.map((d, n) => (
                <tr key={n}>
                  <td className="mono">{d.date}</td>
                  <td
                    className="num"
                    style={
                      d.days < 0
                        ? { color: "var(--v-false)", fontWeight: 600 }
                        : d.days <= 30
                          ? { color: "var(--warn)" }
                          : undefined
                    }
                  >
                    {d.days < 0 ? t("reg.passed", { n: -d.days }) : d.days}
                  </td>
                  <td>
                    {t("reg.item", { n: d.n })} — <span lang="en">{d.title}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {expired ? (
            <div className="note warn">
              <strong>{t("reg.expired.head", { n: expired })}</strong> {t("reg.expired.body")}
            </div>
          ) : null}
          <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 8 }}>
            <T
              k="reg.cutoffNote"
              v={{
                cutoff: <span className="mono">{cutoff}</span>,
                source: t(buildDate ? "reg.cutoff.fromBuild" : "reg.cutoff.fromReader"),
                commits: <em>{t("reg.cutoff.commits")}</em>,
                mentions: <em>{t("reg.cutoff.mentions")}</em>,
              }}
            />
          </p>
        </section>
      ) : null}

      <section>
        <h3>{t("reg.h.items")}</h3>
        <div className="facets">
          <div className="facet">
            <label>{t("reg.facet.tier")}</label>
            <select value={tier} onChange={(e) => setTier(e.target.value)} style={{ minWidth: 420 }}>
              {/* A tier is the register's own heading text, so the options stay as written. */}
              <option value={ANY}>{t("facet.any")}</option>
              {tiers.map((v) => (
                <option key={v} value={v} lang="en">
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div className="facet">
            <label>&nbsp;</label>
            <span className="count mono">{t("facet.shown", { n: items.length })}</span>
          </div>
        </div>

        {items.map((i) => (
          <details className="raw" key={i.n} style={{ marginBottom: 8 }}>
            <summary lang="en">
              <span className="mono">{String(i.n).padStart(2, "0")}</span> — {i.title}
            </summary>
            <div>
              <div style={{ color: "var(--fg-faint)", fontSize: 11.5, margin: "8px 0" }} lang="en">
                {i.tier}
              </div>
              <Body src={i.body_md} />
            </div>
          </details>
        ))}
      </section>

      <section>
        <h3>{t("reg.h.side")}</h3>
        {Object.entries(r.side_registers).map(([name, body]) => (
          <div key={name} style={{ marginBottom: 10 }}>
            {body === null ? (
              <div className="note warn">
                <T k="reg.side.absent" v={{ name: <strong className="mono">{name}</strong> }} />
              </div>
            ) : (
              <details className="raw">
                <summary>
                  <span className="mono">{name}</span>
                </summary>
                <div>
                  <Body src={body} />
                </div>
              </details>
            )}
          </div>
        ))}
      </section>
    </>
  );
}
