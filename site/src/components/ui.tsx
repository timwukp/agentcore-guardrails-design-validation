// Shared presentational pieces. Nothing here fetches; everything takes typed data.

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { PayloadError } from "../lib/data";
import { T, useT } from "../lib/i18n";
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

/** `what` is already-translated text naming the thing being fetched, supplied by the calling view —
 *  the view knows which payload file it is waiting for, and the sentence around it has to inflect
 *  differently per language, so the whole sentence is one dictionary entry with `{what}` in it. */
export function Loading({ what }: { what: string }) {
  const t = useT();
  return <div className="loading">{t("ui.loading", { what })}</div>;
}

export function ErrorPanel({ error }: { error: unknown }) {
  const p = error instanceof PayloadError ? error : null;
  const t = useT();
  return (
    <div className="err">
      <h3>
        {t(
          p
            ? p.kind === "missing"
              ? "ui.err.missing"
              : p.kind === "not-json"
                ? "ui.err.notJson"
                : "ui.err.other"
            : "ui.err.generic",
        )}
      </h3>
      {/* The message itself is the thrown error's own text — a fetch status, a path, a parse position.
          It is diagnostic output, not prose, and translating it would make it unsearchable. */}
      <p className="mono" lang="en">
        {error instanceof Error ? error.message : String(error)}
      </p>
      <p style={{ marginBottom: 0, color: "var(--fg-dim)" }}>
        <T k="ui.err.note" />
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
  const t = useT();
  if (v === null || v === "") return <span className="badge v-none">{t("ui.verdict.none")}</span>;
  const known = (VERDICTS as readonly string[]).includes(v);
  if (!known)
    return (
      <span className="badge v-none" title={t("ui.verdict.unknown")} lang="en">
        {v} *
      </span>
    );
  // TRUE / FALSE / INCONCLUSIVE / RECORDED are never translated: they are the literal tokens in
  // `results/phase1/<case>.json`, and a reader comparing the page to the file searches for the token.
  return (
    <span className={`badge v-${v}`} lang="en">
      {v}
    </span>
  );
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
  const t = useT();
  if (!items.length) return null;
  return (
    <>
      {items.map((r, n) => (
        <div className="note warn" key={n}>
          <div>
            <span className="badge restrict">{r.restriction}</span>{" "}
            {r.subject ? (
              <strong lang="en">{r.subject}</strong>
            ) : null}
          </div>
          {/* `reason`, `citable_as` and `not_citable_as` are `citation_policy.json`'s own wording —
              the rule as the artifact states it. The labels around them are this SPA's. */}
          <div style={{ marginTop: 6 }} lang="en">
            {r.reason}
          </div>
          {r.citable_as?.length ? (
            <div style={{ marginTop: 6 }}>
              <strong>{t("ui.restrict.citableAs")}</strong>{" "}
              <span lang="en">{r.citable_as.join("; ")}</span>
            </div>
          ) : null}
          {r.not_citable_as?.length ? (
            <div style={{ marginTop: 4 }}>
              <strong>{t("ui.restrict.notCitableAs")}</strong>{" "}
              <span lang="en">{r.not_citable_as.join("; ")}</span>
            </div>
          ) : null}
          {r.verdict_on_disk ? (
            <div style={{ marginTop: 4, color: "var(--fg-faint)" }}>
              {t("ui.restrict.onDisk")}{" "}
              <span className="mono" lang="en">
                {r.verdict_on_disk}
              </span>
            </div>
          ) : null}
          <div style={{ marginTop: 6, color: "var(--fg-faint)", fontSize: 11.5 }}>
            {/* A list of repository paths. Marked English for the same reason the census cards mark
                `derived_from`: a path is a string to be typed into a shell, and a screen reader
                inheriting `zh-TW` reads it with the wrong phonology. */}
            {t("ui.restrict.source")}{" "}
            <span className="mono" lang="en">
              {r.source}
            </span>
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
        {/* `lang="en"` because this is the bytes on disk: the keys are the artifact's own field names
            and the strings are its own English. A reader comparing it to
            `results/phase1/<case>.json` is reading a file, not a translation. */}
        <pre lang="en">
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
