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
import { ErrorPanel, Loading, useAsync } from "../components/ui";

const ANY = "— any —";
const COLS = ["claim_id", "cls", "rule", "unit_type", "cases", "anchor", "doc_line", "text"] as const;

export default function Claims() {
  const res = useAsync(loadClaims, []);
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
      .filter((r) =>
        mapped === ANY ? true : mapped === "mapped to a case" ? !!r.cases.trim() : !r.cases.trim(),
      )
      .filter(
        (r) =>
          !needle ||
          r.claim_id.toLowerCase().includes(needle) ||
          r.text.toLowerCase().includes(needle) ||
          r.anchor.toLowerCase().includes(needle) ||
          r.cases.toLowerCase().includes(needle),
      );
  }, [rows, cls, rule, mapped, q]);

  if (res.state === "loading") return <Loading what="the claim triage" />;
  if (res.state === "error") return <ErrorPanel error={res.error} />;

  const nMapped = rows.filter((r) => r.cases.trim()).length;
  const values = (k: "cls" | "rule") => [...new Set(rows.map((r) => r[k]))].sort();

  return (
    <>
      <h2 className="view">Claim triage</h2>
      <p className="lede">
        Every unit of the design document the study extracted, its classification, and the case (if any)
        that measures it. Rendered exactly as the sealed CSV holds it.
      </p>

      <div className="cards" style={{ marginBottom: 18 }}>
        <div className="card">
          <div className="n">{res.data.n_rows}</div>
          <div className="k">triaged rows</div>
          <div className="def">Every row of the sealed triage CSV, including the excluded ones.</div>
        </div>
        <div className="card">
          <div className="n">{nMapped}</div>
          <div className="k">rows naming at least one case</div>
          <div className="def">
            The <code>cases</code> cell is non-empty. Counted from the cell as text, so a row naming two
            cases counts once here — the census counts the other direction.
          </div>
        </div>
        <div className="card">
          <div className="n">{Object.keys(res.data.by_case).length}</div>
          <div className="k">cases with at least one claim</div>
          <div className="def">
            Derived by the build from these same rows, and the basis of the claim-mapped denominator on
            the census page.
          </div>
        </div>
      </div>

      <div className="facets">
        <div className="facet">
          <label>class</label>
          <select value={cls} onChange={(e) => setCls(e.target.value)}>
            {[ANY, ...values("cls")].map((v) => (
              <option key={v}>{v || "(empty)"}</option>
            ))}
          </select>
        </div>
        <div className="facet">
          <label>rule</label>
          <select value={rule} onChange={(e) => setRule(e.target.value)}>
            {[ANY, ...values("rule")].map((v) => (
              <option key={v}>{v || "(empty)"}</option>
            ))}
          </select>
        </div>
        <div className="facet">
          <label>case mapping</label>
          <select value={mapped} onChange={(e) => setMapped(e.target.value)}>
            {[ANY, "mapped to a case", "no case named"].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </div>
        <div className="facet">
          <label>search</label>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="claim id, text, anchor" />
        </div>
        <div className="facet">
          <label>&nbsp;</label>
          <span className="count mono">{filtered.length} shown</span>
        </div>
      </div>

      <div className="scroll">
        <table className="grid">
          <thead>
            <tr>
              {COLS.map((c) => (
                <th key={c}>{c}</th>
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
                  <td
                    key={c}
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
      <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 8 }}>
        The <code>cases</code> column is linked by splitting the raw cell on whitespace for navigation
        only; the cell itself is shown unmodified in every other respect, and the value the study joins
        on is the string, not this split.
      </p>
    </>
  );
}
