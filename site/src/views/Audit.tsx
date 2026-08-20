// View 12 — audit a design of your own: what this study can look for, and how you point it at a repo.
//
// WHY THERE IS NO UPLOAD BUTTON, AND WHY THAT IS THE DESIGN RATHER THAN A MISSING FEATURE
//
// Three reasons, in descending order of how load bearing they are.
//
// 1. The platform must never hold a credential for somebody else's AWS account. The audit reads
//    infrastructure-as-code and nothing else: no `describe`, no assumed role, no account number typed
//    into a form. That boundary is worth more than the extra findings a live read would produce,
//    because a validation platform that collects credentials is a target, and the thing it would be
//    targeted for is access to the very deployments it claims to help secure.
// 2. There is no backend to post a repository to. The site is static files on S3 behind CloudFront;
//    every number on every page was derived at build time from artifacts in the repository. Adding an
//    endpoint that parses an upload would add the first surface on which a reader's bytes exist inside
//    this account.
// 3. The parser is Python, pinned to the same `.venv-oracle` botocore that several verdicts in this
//    study ARE reads of. Re-implementing it in TypeScript to run in the browser would create a second
//    parser that can disagree with the one the report was written against — the same reason the eight
//    canonical whitepaper figures are served as matplotlib PNGs rather than redrawn in Recharts.
//
// So the intake below does the honest thing: it composes the exact commands, and the reader runs them
// on their own machine against their own checkout. Nothing they type is transmitted anywhere.
//
// The composing itself lives in `lib/audit.ts`, not here, because it carries a property that is not
// about appearance: the output of this form is text a reader pastes into their own shell, so the
// repository field is a command fragment rather than display data. That file states the rule and
// `lib/audit.test.ts` pins it.

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { loadAudit, loadControls } from "../lib/data";
import { compose, obsClass, statusClass } from "../lib/audit";
import { ErrorPanel, Loading, useAsync } from "../components/ui";
import type { AuditPage, Control, ControlsDoc } from "../lib/types";

export function StatusBadge({ s, label }: { s: string; label?: string }) {
  return (
    <span className={`badge ${statusClass(s)}`} title={label ?? s}>
      {s.replace(/_/g, " ")}
    </span>
  );
}

export function ObsBadge({ o }: { o: string }) {
  return <span className={`badge ${obsClass(o)}`}>{o}</span>;
}

function CommandBlock({ lines }: { lines: string[] }) {
  const [copied, setCopied] = useState<"no" | "yes" | "failed">("no");
  const text = lines.join("\n");
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <button
          type="button"
          className="btn"
          onClick={() => {
            // Clipboard access is unavailable in a non-secure context and can be denied by policy.
            // Both are reported rather than swallowed: a button that silently does nothing is worse
            // than no button, and the block below stays selectable either way.
            const p = navigator.clipboard?.writeText(text);
            if (!p) {
              setCopied("failed");
              return;
            }
            p.then(
              () => setCopied("yes"),
              () => setCopied("failed"),
            );
          }}
        >
          Copy the three commands
        </button>
        <span style={{ color: "var(--fg-faint)", fontSize: 12 }}>
          {copied === "yes"
            ? "copied"
            : copied === "failed"
              ? "the browser refused clipboard access — select the text below instead"
              : "or select it below"}
        </span>
      </div>
      <pre className="verbatim">
        <code>{text}</code>
      </pre>
    </div>
  );
}

function ControlRow({ c }: { c: Control }) {
  const hints = Array.isArray(c.detect.type_hint)
    ? c.detect.type_hint
    : c.detect.type_hint
      ? [c.detect.type_hint]
      : [];
  return (
    <tr>
      <td className="mono">{c.id}</td>
      <td>
        <div>{c.label}</div>
        <div style={{ color: "var(--fg-dim)", fontSize: 12, marginTop: 3 }}>{c.question}</div>
      </td>
      <td>
        {c.statuses.length ? (
          c.statuses.map((s) => (
            <span key={s} style={{ marginRight: 4 }}>
              <StatusBadge s={s} />
            </span>
          ))
        ) : (
          <span style={{ color: "var(--fg-faint)" }}>—</span>
        )}
        {c.why_not_measured ? (
          <div style={{ color: "var(--fg-dim)", fontSize: 12, marginTop: 4 }}>{c.why_not_measured}</div>
        ) : null}
      </td>
      <td>
        {c.measured_by.length ? (
          c.measured_by.map((m) => (
            <Link key={m.case} to={`/case/${m.case}`} className="chip" title={m.title}>
              {m.case}
              {m.verdict ? ` · ${m.verdict}` : " · no verdict"}
              {m.restrictions.length ? " ⚠" : ""}
            </Link>
          ))
        ) : (
          <span style={{ color: "var(--fg-faint)" }}>no case measured this</span>
        )}
      </td>
      <td style={{ fontSize: 11.5 }}>
        <div className="mono" style={{ wordBreak: "break-all" }}>
          {(c.detect.paths ?? []).join("  ")}
        </div>
        {hints.length ? (
          <div style={{ color: "var(--fg-faint)", marginTop: 3 }}>
            on a resource whose type contains: <span className="mono">{hints.join(", ")}</span>
          </div>
        ) : null}
        {c.detect.paths_source ? (
          <div style={{ color: "var(--fg-faint)", marginTop: 3 }}>
            model: <span className="mono">{c.detect.paths_source}</span>
          </div>
        ) : null}
      </td>
    </tr>
  );
}

export default function Audit() {
  const ctl = useAsync(loadControls, []);
  const aud = useAsync(loadAudit, []);
  const [target, setTarget] = useState("");
  const [asOf, setAsOf] = useState("");

  const commands = aud.state === "ok" ? aud.data.tools.commands : [];
  const composed = useMemo(() => compose(commands, target, asOf), [commands, target, asOf]);

  if (ctl.state === "loading" || aud.state === "loading") return <Loading what="the audit tooling" />;
  if (ctl.state === "error") return <ErrorPanel error={ctl.error} />;
  if (aud.state === "error") return <ErrorPanel error={aud.error} />;
  const c: ControlsDoc = ctl.data;
  const a: AuditPage = aud.data;

  const controls = [...c.controls].sort((x, y) => x.id.localeCompare(y.id));

  return (
    <>
      <h2>Audit a design of your own</h2>
      <p className="lede">
        This study measured {c.n_controls} controls of an AgentCore deployment. Two programs in the
        repository read a repository's infrastructure-as-code, report which of those {c.n_controls} it
        declares, and state — per control, citing the case — what was measured about the value it
        declares. Everything runs on your machine.
      </p>

      <h3>What this page will not do</h3>
      <div className="cards">
        {a.boundaries.map((b) => (
          <div className="card" key={b.claim}>
            <div className="k" style={{ color: "var(--fg)", fontSize: 13.5, marginBottom: 6 }}>
              {b.claim}
            </div>
            <div className="def">{b.how}</div>
          </div>
        ))}
      </div>

      <h3>Point the tools at your repository</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        Fill either field and the commands below change. They are the commands as{" "}
        <span className="mono">{a.tools.parse}</span> and <span className="mono">{a.tools.report}</span>{" "}
        define them, read from the payload rather than typed into this page. Nothing you enter is sent
        anywhere: there is no endpoint on this site that accepts a request body.
      </p>
      <div className="intake">
        <label>
          <span>Your repository — a git URL or a local path</span>
          <input
            type="text"
            value={target}
            spellCheck={false}
            placeholder="git@github.com:your-org/your-infra.git"
            onChange={(e) => setTarget(e.target.value)}
          />
        </label>
        <label>
          <span>Report date (optional)</span>
          <input
            type="text"
            value={asOf}
            spellCheck={false}
            placeholder="YYYY-MM-DD — leave empty for a byte-identical report"
            onChange={(e) => setAsOf(e.target.value)}
          />
        </label>
      </div>
      {composed.refusal ? <div className="note warn">{composed.refusal}</div> : null}
      <CommandBlock lines={composed.lines} />
      <p style={{ color: "var(--fg-dim)", marginTop: 10 }}>
        The second command writes <span className="mono">inventory.json</span> — what the parser saw,
        with a file and line for every site, and no reference to this study. The third joins it to the
        study and writes the report as both JSON and Markdown.{" "}
        <Link to="/report">See the worked example</Link>, which is that output for a synthetic
        submission in this repository, produced by the same two programs at build time. The report view
        will also render a <span className="mono">report.json</span> you produce yourself, without
        uploading it.
      </p>

      <h3>What this study can look for</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        The property paths are shown because they are the whole of what a DECLARED result rests on: a
        control is found when a template carries that path, and reported NOT_DECLARED when the parsed
        files do not — which is never evidence that the control is absent from a system. Paths are
        lower-cased and dot-joined, because a template may spell them in camelCase or PascalCase.
      </p>
      <div className="scroll">
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 150 }}>Control</th>
              <th>What it is</th>
              <th style={{ width: 190 }}>What this study established</th>
              <th style={{ width: 210 }}>Cases</th>
              <th style={{ width: 260 }}>Detected by</th>
            </tr>
          </thead>
          <tbody>
            {controls.map((x) => (
              <ControlRow key={x.id} c={x} />
            ))}
          </tbody>
        </table>
      </div>

      <h3>Coverage of the {c.n_controls} controls, by what was established</h3>
      <div className="cards">
        {(c.vocabularies.status ?? []).map((s) => (
          <div className="card" key={s}>
            <div className="n">{c.controls_by_status[s] ?? 0}</div>
            <div className="k">
              <StatusBadge s={s} />
            </div>
          </div>
        ))}
      </div>
      <div className="note" style={{ marginTop: 12 }}>
        These counts do not sum to {c.n_controls} and no denominator over them means anything: a single
        control can carry a <span className="mono">measured_true</span> finding for one declared value
        and a <span className="mono">measured_false</span> finding for another, and it is counted under
        both. For the same reason there is no pass rate on this page, or on any other here.
      </div>

      <h3>Paths this study names but cannot verify against the service model</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        Detection paths were checked against the pinned instrument —{" "}
        <span className="mono">{c.field_paths.instrument}</span>, derived{" "}
        <span className="mono">{c.field_paths.derived_on}</span>. The paths below are matched anyway,
        and they are listed here because the reason they cannot be checked is itself worth knowing
        before you trust a result that rests on one.
      </p>
      <table className="grid">
        <thead>
          <tr>
            <th style={{ width: 300 }}>Path</th>
            <th>Why it cannot be verified against an API model</th>
          </tr>
        </thead>
        <tbody>
          {c.unverifiable_paths.map((u) => (
            <tr key={u.path}>
              <td className="mono">{u.path}</td>
              <td style={{ whiteSpace: "pre-wrap" }}>{u.why.trim()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 10 }}>{c.field_paths.note}</p>
      <p style={{ color: "var(--fg-faint)", fontSize: 12 }}>{c.note}</p>
    </>
  );
}
