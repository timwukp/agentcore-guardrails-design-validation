// Shared presentational pieces. Nothing here fetches; everything takes typed data.

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { PayloadError } from "../lib/data";
import { VERDICTS } from "../lib/types";
import type { CitationRestriction, Verdict } from "../lib/types";
import { Markdown } from "../lib/md";

/** Async load with the three states rendered distinctly. `null` data is never conflated with an
 *  error, and an error is never conflated with "still loading" — an unresolved fetch that renders as
 *  an empty table is how a dashboard reports zero when it means unknown. */
export type Async<T> = { state: "loading" } | { state: "error"; error: unknown } | { state: "ok"; data: T };

export function useAsync<T>(load: () => Promise<T>, deps: readonly unknown[]): Async<T> {
  const [res, setRes] = useState<Async<T>>({ state: "loading" });
  useEffect(() => {
    let live = true;
    setRes({ state: "loading" });
    load().then(
      (data) => live && setRes({ state: "ok", data }),
      (error) => live && setRes({ state: "error", error }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return res;
}

export function Loading({ what }: { what: string }) {
  return <div className="loading">Loading {what}…</div>;
}

export function ErrorPanel({ error }: { error: unknown }) {
  const p = error instanceof PayloadError ? error : null;
  return (
    <div className="err">
      <h3>
        {p
          ? p.kind === "missing"
            ? "A file this view needs is not in the published payload"
            : p.kind === "not-json"
              ? "A file this view needs was not served as JSON"
              : "Could not read a file this view needs"
          : "This view could not be rendered"}
      </h3>
      <p className="mono">{error instanceof Error ? error.message : String(error)}</p>
      <p style={{ marginBottom: 0, color: "var(--fg-dim)" }}>
        This is a defect in the published build, not a state you can navigate out of. The repository
        markdown and JSON remain the citable form of every number this dashboard shows.
      </p>
    </div>
  );
}

/** One of the four verdicts, the absence of one, or a value from outside that vocabulary.
 *
 * `null` renders as an explicit "no verdict" rather than as a blank cell: some registered cases have
 * no verdict for stated reasons, and a blank cell reads as a rendering bug.
 *
 * A value outside the four is rendered as itself with a marker saying so, because the archive does
 * contain one — an archived F3-10 file carries WITHDRAWN, which is a real state of a real file and not
 * a fifth verdict. Coercing it to a colour would file it under a vocabulary it does not belong to;
 * dropping it would hide that the archive and the live register speak slightly different languages. */
export function VerdictBadge({ v }: { v: Verdict | string | null }) {
  if (v === null || v === "") return <span className="badge v-none">no verdict</span>;
  const known = (VERDICTS as readonly string[]).includes(v);
  if (!known)
    return (
      <span
        className="badge v-none"
        title="not one of the four verdict values — a state recorded by the file itself"
      >
        {v} *
      </span>
    );
  return <span className={`badge v-${v}`}>{v}</span>;
}

export function Chips({ items, cls }: { items: string[]; cls?: string }) {
  if (!items.length) return <span style={{ color: "var(--fg-faint)" }}>—</span>;
  return (
    <>
      {items.map((s) => (
        <span key={s} className={`chip${cls ? ` ${cls}` : ""}`}>
          {s}
        </span>
      ))}
    </>
  );
}

/** Citation restrictions render as data, never as copy — the rule lives in `citation_policy.json`
 *  so that changing what may be cited is a change to an artifact, not to a component. */
export function Restrictions({ items }: { items: CitationRestriction[] }) {
  if (!items.length) return null;
  return (
    <>
      {items.map((r, n) => (
        <div className="note warn" key={n}>
          <div>
            <span className="badge restrict">{r.restriction}</span>{" "}
            {r.subject ? <strong>{r.subject}</strong> : null}
          </div>
          <div style={{ marginTop: 6 }}>{r.reason}</div>
          {r.citable_as?.length ? (
            <div style={{ marginTop: 6 }}>
              <strong>May be cited as:</strong> {r.citable_as.join("; ")}
            </div>
          ) : null}
          {r.not_citable_as?.length ? (
            <div style={{ marginTop: 4 }}>
              <strong>May not be cited as:</strong> {r.not_citable_as.join("; ")}
            </div>
          ) : null}
          {r.verdict_on_disk ? (
            <div style={{ marginTop: 4, color: "var(--fg-faint)" }}>
              Verdict recorded on disk: <span className="mono">{r.verdict_on_disk}</span>
            </div>
          ) : null}
          <div style={{ marginTop: 6, color: "var(--fg-faint)", fontSize: 11.5 }}>
            source: <span className="mono">{r.source}</span>
          </div>
        </div>
      ))}
    </>
  );
}

export function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([k, v], n) => (
        <div key={n} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A verdict record, rendered as its own JSON. Deliberately not prettified into prose: this is the
 *  bytes on disk, and a reader checking the dashboard against `results/phase1/<case>.json` must be
 *  able to compare them character for character. */
export function RawJson({ label, value }: { label: string; value: unknown }) {
  return (
    <details className="raw">
      <summary>{label}</summary>
      <div>
        <pre>
          <code>{JSON.stringify(value, null, 2)}</code>
        </pre>
      </div>
    </details>
  );
}

/** Markdown from an artifact's `body_md`. See lib/md.tsx for why this never produces HTML. */
export function Body({ src }: { src: string }) {
  return <Markdown src={src} />;
}
