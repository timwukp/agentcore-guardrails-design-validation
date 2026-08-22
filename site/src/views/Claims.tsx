// Claim triage — the join between the design document and the measurements.
//
// EVERY CELL IS SHOWN AS THE STRING IT IS
//
// `claims/triage.csv` is a sealed artifact: it was fixed before the measurements ran, and the verdict
// register's claim mapping is defined against it. So the build carries every cell through as text and
// this table renders text — `doc_line` is not parsed into a number, `cases` is not split on whitespace,
// and an empty cell is not turned into a dash that means something. Any of those would be an edit to a
// sealed artifact's meaning performed on the way to the screen, and the reader would have no way to
// see that it happened.

import { useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { loadClaims } from "../lib/data";
import { useT, VerbatimNote } from "../lib/i18n";
import { ErrorPanel, Loading, useAsync } from "../components/ui";

/** The facet's STATE is a stable token; only its label is translated. If the label were the state,
 *  switching language mid-filter would leave a filter set to a value no option carries any more, and
 *  the table would silently show nothing while the control looked normal. */
const ANY = "*any*";
const MAPPED = "*mapped*";
const UNMAPPED = "*unmapped*";

/** The column names of the sealed CSV, not headings this platform chose. Untranslated for the same
 *  reason the cells are unparsed: a reader checking a column against `claims/triage.csv` is looking
 *  for `doc_line`, and `文件行號` is not in that file. */
const COLS = ["claim_id", "cls", "rule", "unit_type", "cases", "anchor", "doc_line", "text"] as const;

export default function Claims() {
  const res = useAsync(loadClaims, []);
  const t = useT();
  const { hash } = useLocation();
  const wanted = hash.replace(/^#/, "");

  const [cls, setCls] = useState(ANY);
  const [rule, setRule] = useState(ANY);
  const [mapped, setMapped] = useState(ANY);
  const [q, setQ] = useState("");

  const rows = res.state === "ok" ? res.data.rows : [];

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows
      .filter((r) => cls === ANY || r.cls === cls)
      .filter((r) => rule === ANY || r.rule === rule)
      .filter((r) => (mapped === ANY ? true : mapped === MAPPED ? !!r.cases.trim() : !r.cases.trim()))
      .filter(
        (r) =>
          !needle ||
          r.claim_id.toLowerCase().includes(needle) ||
          r.text.toLowerCase().includes(needle) ||
          r.anchor.toLowerCase().includes(needle) ||
          r.cases.toLowerCase().includes(needle),
      );
  }, [rows, cls, rule, mapped, q]);

  if (res.state === "loading") return <Loading what={t("clm.loading")} />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;

  const nMapped = rows.filter((r) => r.cases.trim()).length;
  const values = (k: "cls" | "rule") => [...new Set(rows.map((r) => r[k]))].sort();

  return (
    <>
      <h2 className="view">{t("nav.claims")}</h2>
      <VerbatimNote />
      <p className="lede">{t("clm.lede")}</p>

      <div className="cards" style={{ marginBottom: 18 }}>
        <div className="card">
          <div className="n">{res.data.n_rows}</div>
          <div className="k">{t("clm.card.rows")}</div>
          <div className="def">{t("clm.card.rows.def")}</div>
        </div>
        <div className="card">
          <div className="n">{nMapped}</div>
          <div className="k">{t("clm.card.named")}</div>
          <div className="def">{t("clm.card.named.def")}</div>
        </div>
        <div className="card">
          <div className="n">{Object.keys(res.data.by_case).length}</div>
          <div className="k">{t("clm.card.cases")}</div>
          <div className="def">{t("clm.card.cases.def")}</div>
        </div>
      </div>

      <div className="facets">
        <div className="facet">
          <label>{t("clm.facet.class")}</label>
          <select value={cls} onChange={(e) => setCls(e.target.value)}>
            {/* The option TEXT for a triage class is the CSV's own token; only `— any —` and the
                empty-cell marker are this platform's words. */}
            <option value={ANY}>{t("facet.any")}</option>
            {values("cls").map((v) => (
              <option key={v} value={v}>
                {v || t("facet.empty")}
              </option>
            ))}
          </select>
        </div>
        <div className="facet">
          <label>{t("clm.facet.rule")}</label>
          <select value={rule} onChange={(e) => setRule(e.target.value)}>
            <option value={ANY}>{t("facet.any")}</option>
            {values("rule").map((v) => (
              <option key={v} value={v}>
                {v || t("facet.empty")}
              </option>
            ))}
          </select>
        </div>
        <div className="facet">
          <label>{t("clm.facet.mapping")}</label>
          <select value={mapped} onChange={(e) => setMapped(e.target.value)}>
            <option value={ANY}>{t("facet.any")}</option>
            <option value={MAPPED}>{t("clm.facet.mapped")}</option>
            <option value={UNMAPPED}>{t("clm.facet.unmapped")}</option>
          </select>
        </div>
        <div className="facet">
          <label>{t("clm.facet.search")}</label>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("clm.facet.searchHint")} />
        </div>
        <div className="facet">
          <label>&nbsp;</label>
          <span className="count mono">{t("facet.shown", { n: filtered.length })}</span>
        </div>
      </div>

      <div className="scroll">
        <table className="grid">
          <thead>
            <tr>
              {COLS.map((c) => (
                <th key={c} lang="en">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, n) => (
              <tr
                key={`${r.claim_id}-${n}`}
                id={r.claim_id}
                style={r.claim_id === wanted ? { outline: "1px solid var(--accent)" } : undefined}
              >
                {COLS.map((c) => (
                  // Every cell is a `claims/triage.csv` value — the `text` column is the sealed
                  // claim as the design document words it — so the whole row is quoted English in
                  // both editions, like the header above it.
                  <td
                    key={c}
                    lang="en"
                    className={c === "text" ? undefined : "mono"}
                    style={c === "text" ? { minWidth: 320 } : { whiteSpace: "nowrap" }}
                  >
                    {c === "cases" && r.cases.trim() ? (
                      r.cases
                        .split(/\s+/)
                        .filter(Boolean)
                        .map((cid, i) => (
                          <span key={cid}>
                            {i ? " " : ""}
                            <Link to={`/case/${cid}`}>{cid}</Link>
                          </span>
                        ))
                    ) : (
                      r[c] || <span style={{ color: "var(--fg-faint)" }}>—</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 8 }}>{t("clm.splitNote")}</p>
    </>
  );
}
