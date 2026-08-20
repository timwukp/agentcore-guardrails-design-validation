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
import { T, useT, VerbatimNote } from "../lib/i18n";
import { ErrorPanel, Loading, useAsync } from "../components/ui";
import type { AuditPage, Control, ControlsDoc } from "../lib/types";

/** The status and observation words are `controls.json`'s own vocabularies — `not_measured`,
 *  `NOT_DECLARED` — and the styling gate keys on them. They stay in English in both languages, like the
 *  verdict tokens: what they MEAN is translated in the prose around them. */
export function StatusBadge({ s, label }: { s: string; label?: string }) {
  return (
    <span className={`badge ${statusClass(s)}`} title={label ?? s} lang="en">
      {s.replace(/_/g, " ")}
    </span>
  );
}

export function ObsBadge({ o }: { o: string }) {
  return (
    <span className={`badge ${obsClass(o)}`} lang="en">
      {o}
    </span>
  );
}

function CommandBlock({ lines }: { lines: string[] }) {
  const [copied, setCopied] = useState<"no" | "yes" | "failed">("no");
  const t = useT();
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
          {t("aud.copy", { n: lines.length })}
        </button>
        <span style={{ color: "var(--fg-faint)", fontSize: 12 }}>
          {copied === "yes"
            ? t("aud.copy.done")
            : copied === "failed"
              ? t("aud.copy.refused")
              : t("aud.copy.orSelect")}
        </span>
      </div>
      {/* A shell command, so `lang="en"` is not a nicety: this is the one block on the page a reader
          is meant to copy and run, and it must never be read — by a person or a screen reader — as
          anything but the literal bytes. */}
      <pre className="verbatim" lang="en">
        <code>{text}</code>
      </pre>
    </div>
  );
}

function ControlRow({ c }: { c: Control }) {
  const t = useT();
  const hints = Array.isArray(c.detect.type_hint)
    ? c.detect.type_hint
    : c.detect.type_hint
      ? [c.detect.type_hint]
      : [];
  return (
    <tr>
      <td className="mono">{c.id}</td>
      <td lang="en">
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
          <div style={{ color: "var(--fg-dim)", fontSize: 12, marginTop: 4 }} lang="en">
            {c.why_not_measured}
          </div>
        ) : null}
      </td>
      <td>
        {c.measured_by.length ? (
          c.measured_by.map((m) => (
            <Link key={m.case} to={`/case/${m.case}`} className="chip" title={m.title}>
              {m.case}
              {m.verdict ? ` · ${m.verdict}` : ` · ${t("ui.verdict.none")}`}
              {m.restrictions.length ? " ⚠" : ""}
            </Link>
          ))
        ) : (
          <span style={{ color: "var(--fg-faint)" }}>{t("aud.noCase")}</span>
        )}
      </td>
      <td style={{ fontSize: 11.5 }}>
        {/* API field paths out of the botocore model — `targetconfiguration.mcp.lambda` and the like.
            Never translated, so marked English rather than left to inherit the page's locale. */}
        <div className="mono" lang="en" style={{ wordBreak: "break-all" }}>
          {(c.detect.paths ?? []).join("  ")}
        </div>
        {hints.length ? (
          <div style={{ color: "var(--fg-faint)", marginTop: 3 }}>
            <T
              k="aud.typeHint"
              v={{
                hints: (
                  <span className="mono" lang="en">
                    {hints.join(", ")}
                  </span>
                ),
              }}
            />
          </div>
        ) : null}
        {c.detect.paths_source ? (
          <div style={{ color: "var(--fg-faint)", marginTop: 3 }}>
            {/* The API operation these paths were read out of — an SDK model name, English always. */}
            <T
              k="aud.model"
              v={{
                model: (
                  <span className="mono" lang="en">
                    {c.detect.paths_source}
                  </span>
                ),
              }}
            />
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
  const t = useT();

  const commands = aud.state === "ok" ? aud.data.tools.commands : [];
  const composed = useMemo(() => compose(commands, target, asOf), [commands, target, asOf]);

  if (ctl.state === "loading" || aud.state === "loading")
    return <Loading what={t("aud.loading")} />;
  if (ctl.state === "error") return <ErrorPanel error={ctl.error} />;
  if (aud.state === "error") return <ErrorPanel error={aud.error} />;
  const c: ControlsDoc = ctl.data;
  const a: AuditPage = aud.data;

  const controls = [...c.controls].sort((x, y) => x.id.localeCompare(y.id));

  return (
    <>
      <h2>{t("aud.title")}</h2>
      <VerbatimNote />
      <p className="lede">{t("aud.lede", { n: c.n_controls })}</p>

      <h3>{t("aud.h.willNotDo")}</h3>
      <div className="cards">
        {a.boundaries.map((b) => (
          <div className="card" key={b.claim}>
            <div
              className="k"
              style={{ color: "var(--fg)", fontSize: 13.5, marginBottom: 6 }}
              lang="en"
            >
              {b.claim}
            </div>
            <div className="def" lang="en">
              {b.how}
            </div>
          </div>
        ))}
      </div>

      <h3>{t("aud.h.point")}</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        <T
          k="aud.point.body"
          v={{
            parse: <span className="mono">{a.tools.parse}</span>,
            report: <span className="mono">{a.tools.report}</span>,
          }}
        />
      </p>
      <div className="intake">
        <label>
          <span>{t("aud.field.repo")}</span>
          <input
            type="text"
            value={target}
            spellCheck={false}
            placeholder="git@github.com:your-org/your-infra.git"
            onChange={(e) => setTarget(e.target.value)}
          />
        </label>
        <label>
          <span>{t("aud.field.date")}</span>
          <input
            type="text"
            value={asOf}
            spellCheck={false}
            placeholder={t("aud.field.datePlaceholder")}
            onChange={(e) => setAsOf(e.target.value)}
          />
        </label>
      </div>
      {/* The refusal arrives from `lib/audit.ts` as a key plus the reader's own value, and is rendered
          here — that module decides WHAT to refuse, this one decides in which language to say so. */}
      {composed.refusal ? (
        <div className="note warn">{t(composed.refusal.key, composed.refusal.vars)}</div>
      ) : null}
      <CommandBlock lines={composed.lines} />
      <p style={{ color: "var(--fg-dim)", marginTop: 10 }}>
        <T
          k="aud.afterCommands"
          v={{
            inventory: <span className="mono">inventory.json</span>,
            example: <Link to="/report">{t("aud.afterCommands.exampleLink")}</Link>,
            report: <span className="mono">report.json</span>,
          }}
        />
      </p>

      <h3>{t("aud.h.canLookFor")}</h3>
      <p style={{ color: "var(--fg-dim)" }}>{t("aud.canLookFor.body")}</p>
      <div className="scroll">
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 150 }}>{t("aud.th.control")}</th>
              <th>{t("aud.th.whatItIs")}</th>
              <th style={{ width: 190 }}>{t("aud.th.established")}</th>
              <th style={{ width: 210 }}>{t("aud.th.cases")}</th>
              <th style={{ width: 260 }}>{t("aud.th.detectedBy")}</th>
            </tr>
          </thead>
          <tbody>
            {controls.map((x) => (
              <ControlRow key={x.id} c={x} />
            ))}
          </tbody>
        </table>
      </div>

      <h3>{t("aud.h.coverage", { n: c.n_controls })}</h3>
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
        <T
          k="aud.noDenominator"
          v={{
            n: String(c.n_controls),
            t: <span className="mono">measured_true</span>,
            f: <span className="mono">measured_false</span>,
          }}
        />
      </div>

      <h3>{t("aud.h.unverifiable")}</h3>
      <p style={{ color: "var(--fg-dim)" }}>
        <T
          k="aud.unverifiable.body"
          v={{
            // The instrument's own description of itself, out of `controls.json` — a pinned SDK
            // version and a venv path, quoted rather than translated.
            instrument: (
              <span className="mono" lang="en">
                {c.field_paths.instrument}
              </span>
            ),
            derived: (
              <span className="mono" lang="en">
                {c.field_paths.derived_on}
              </span>
            ),
          }}
        />
      </p>
      <table className="grid">
        <thead>
          <tr>
            <th style={{ width: 300 }}>{t("aud.th.path")}</th>
            <th>{t("aud.th.whyUnverifiable")}</th>
          </tr>
        </thead>
        <tbody>
          {c.unverifiable_paths.map((u) => (
            <tr key={u.path}>
              <td className="mono">{u.path}</td>
              <td style={{ whiteSpace: "pre-wrap" }} lang="en">
                {u.why.trim()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ color: "var(--fg-faint)", fontSize: 12, marginTop: 10 }} lang="en">
        {c.field_paths.note}
      </p>
      <p style={{ color: "var(--fg-faint)", fontSize: 12 }} lang="en">
        {c.note}
      </p>
    </>
  );
}
