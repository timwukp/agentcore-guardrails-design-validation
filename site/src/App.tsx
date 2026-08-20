import { NavLink, Route, Routes } from "react-router-dom";
import { loadManifest } from "./lib/data";
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

const NAV: [string, string, string][] = [
  ["Results", "/", "Census"],
  ["Results", "/findings", "Findings"],
  ["Results", "/figures", "Figures"],
  ["Method", "/method", "How a verdict is made"],
  ["Method", "/claims", "Claim triage"],
  ["Method", "/citations", "Citation policy"],
  ["Governance", "/register", "Deficiency register"],
  ["Governance", "/provenance", "Build provenance"],
];

function Side() {
  const man = useAsync(loadManifest, []);
  const groups = [...new Set(NAV.map(([g]) => g))];
  return (
    <aside className="side">
      <h1>GRX Live</h1>
      <p className="sub">
        A standing validation of the AgentCore end-to-end security design guidance, derived from its
        own artifacts at every build.
      </p>
      <nav>
        {groups.map((g) => (
          <div key={g}>
            <div className="navgroup">{g}</div>
            {NAV.filter(([gg]) => gg === g).map(([, to, label]) => (
              <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "on" : "")}>
                {label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="build">
        {man.state === "ok" ? (
          <>
            build <span className="mono">{man.data.build_stamp}</span>
            <br />
            {man.data.n_inputs} inputs → {man.data.n_outputs} files
          </>
        ) : man.state === "error" ? (
          <span style={{ color: "var(--warn)" }}>build stamp unavailable</span>
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
          <Route path="/provenance" element={<Provenance />} />
          <Route
            path="*"
            element={
              <div className="err">
                <h3>No such view</h3>
                <p style={{ marginBottom: 0 }}>
                  Nothing is published at this route. Use the navigation on the left.
                </p>
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  );
}
