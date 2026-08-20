import { NavLink, Route, Routes } from "react-router-dom";
import { loadManifest } from "./lib/data";
import { LocaleToggle, T, useT } from "./lib/i18n";
import type { Key } from "./lib/strings";
import { useAsync } from "./components/ui";
import Overview from "./views/Overview";
import CaseDetail from "./views/CaseDetail";
import Findings from "./views/Findings";
import FigureGallery from "./views/FigureGallery";
import Register from "./views/Register";
import Citations from "./views/Citations";
import Claims from "./views/Claims";
import Method from "./views/Method";
import Provenance from "./views/Provenance";
import Pipeline from "./views/Pipeline";
import Audit from "./views/Audit";
import Report from "./views/Report";
import Architecture from "./views/Architecture";

/** The name in the heading is the REPOSITORY name, not a product name.
 *
 *  "GRX Live" was a label that existed only here — nothing a reader could look up, check out, or file
 *  an issue against. `agentcore-guardrails-design-validation` is the thing itself: the repository whose
 *  artifacts every number on every page below is derived from, so a reader who wants the citable form
 *  of what they are looking at already has its address. It stays in `mono` and untranslated in both
 *  languages for the same reason a case identifier does — it is a string you search for, not a phrase.
 *
 *  Deliberately NOT renamed: the CDK stack id and the CloudFront/S3 resource names under
 *  `platform/infra/`. A stack id is a physical identity — changing it replaces the distribution and
 *  the bucket rather than relabelling them — and the operator scripts' own console output is not a
 *  page a reader visits. The name a reader sees and the name AWS holds are allowed to differ; a
 *  destroyed distribution to make them match is not a rename. */
const REPO_NAME = "agentcore-guardrails-design-validation";

const NAV: [Key, string, Key][] = [
  ["nav.group.results", "/", "nav.census"],
  ["nav.group.results", "/findings", "nav.findings"],
  ["nav.group.results", "/figures", "nav.figures"],
  ["nav.group.method", "/architecture", "nav.architecture"],
  ["nav.group.method", "/method", "nav.method"],
  ["nav.group.method", "/claims", "nav.claims"],
  ["nav.group.method", "/citations", "nav.citations"],
  ["nav.group.pipeline", "/pipeline", "nav.pipeline"],
  ["nav.group.audit", "/audit", "nav.audit"],
  ["nav.group.audit", "/report", "nav.report"],
  ["nav.group.governance", "/register", "nav.register"],
  ["nav.group.governance", "/provenance", "nav.provenance"],
];

function Side() {
  const man = useAsync(loadManifest, []);
  const t = useT();
  const groups = [...new Set(NAV.map(([g]) => g))];
  return (
    <aside className="side">
      <h1 className="repo" lang="en">
        {REPO_NAME}
      </h1>
      <LocaleToggle />
      <p className="sub">
        <T k="app.tagline" />
      </p>
      <nav>
        {groups.map((g) => (
          <div key={g}>
            <div className="navgroup">{t(g)}</div>
            {NAV.filter(([gg]) => gg === g).map(([, to, label]) => (
              <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "on" : "")}>
                {t(label)}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="build">
        {man.state === "ok" ? (
          <>
            {t("app.build.label")} <span className="mono">{man.data.build_stamp}</span>
            <br />
            {t("app.build.files", { n_inputs: man.data.n_inputs, n_outputs: man.data.n_outputs })}
          </>
        ) : man.state === "error" ? (
          <span style={{ color: "var(--warn)" }}>{t("app.build.unavailable")}</span>
        ) : (
          "…"
        )}
      </div>
    </aside>
  );
}

export default function App() {
  return (
    <div className="shell">
      <Side />
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/case/:id" element={<CaseDetail />} />
          <Route path="/findings" element={<Findings />} />
          <Route path="/figures" element={<FigureGallery />} />
          <Route path="/register" element={<Register />} />
          <Route path="/citations" element={<Citations />} />
          <Route path="/claims" element={<Claims />} />
          <Route path="/method" element={<Method />} />
          <Route path="/architecture" element={<Architecture />} />
          <Route path="/provenance" element={<Provenance />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/report" element={<Report />} />
          <Route
            path="*"
            element={
              <div className="err">
                <h3>
                  <T k="app.404.title" />
                </h3>
                <p style={{ marginBottom: 0 }}>
                  <T k="app.404.body" />
                </p>
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  );
}
