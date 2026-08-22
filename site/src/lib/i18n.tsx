// Two languages for one set of claims — the mechanism, and the rule about what may be translated.
//
// WHAT IS TRANSLATED, AND WHAT MAY NEVER BE
//
// Everything on a page here comes from one of two places, and they are governed differently:
//
//   * The CHROME — navigation, headings, column headers, buttons, and the explanatory prose this SPA
//     itself authors about how to read a number. That text is written in `strings.ts` and exists in
//     both languages. It is a description of the platform, so a second wording of it is a translation.
//
//   * The PAYLOAD — case titles, `oracle_text`, verdicts, `why_this_status`, register items, findings
//     bodies, scenario justifications, the audit report. That text is the artifacts' own words, and it
//     renders VERBATIM IN ENGLISH in both languages. Translating it would be a second rendering of a
//     sealed claim: `oracle_text` is hashed into `meta.oracle_registry` and quoted rather than
//     paraphrased precisely so that no restatement can drift from it, and a Chinese paraphrase of a
//     verdict is a restatement whose only provenance is this file. The reader is told this, in their
//     own language, by `payload.verbatim.note` — an untranslated block that says nothing about why it
//     is untranslated is indistinguishable from a missing translation.
//
// AND THE PART OF THAT DIVISION THAT WAS FALSE
//
// The second bullet said "the payload is the artifacts' own words" and the site was built on it: every
// payload surface renders `lang="en"` and the Chinese banner tells the reader that the English they are
// looking at is quoted evidence. A browser census of both locales over every route
// (`platform/build/census_rendered_surfaces.py`, first run 2026-08-22) measured what is actually on
// screen and the claim did not survive: of 1,946 payload strings a reader reaches, 767 are quoted
// artifact and 310 are THIS PLATFORM'S OWN PROSE — the denominator definitions, the audit boundary
// promises, the architecture status sentences. The banner was not describing a translation gap; it was
// telling the reader that the gap was a principle.
//
// So the payload is not one thing, and a comment cannot be what sorts it. An authored payload value now
// has the SHAPE `{en, zh}` (`types.Authored`, emitted by `build_site_data.authored`) and a sealed
// quotation stays a bare string, which makes the default — writing a plain string literal — render
// verbatim English. `useAuthored` below resolves the shape, and marks `lang="en"` only on the values
// where English is what the reader gets. What has not been converted yet is counted, not described: the
// census publishes the remaining number and `check_site_invariants.py` holds it as a ceiling that may
// only fall.
//
// WHY THE DICTIONARY IS KEYED ONCE, WITH BOTH LANGUAGES IN ONE ENTRY
//
// The obvious shape is two objects, `en` and `zh`, and the obvious failure is a key in one and not the
// other — which ships as a blank heading or, worse, as a lookup falling back to English on a page that
// claims to be Chinese. `Record<Key, [string, string]>` makes that unrepresentable rather than
// checked: there is only one key set, so a missing translation is not a missing key but a tuple of the
// wrong length, which is a type error at build time. What a type cannot see — an EMPTY or
// English-identical second element — `i18n.test.ts` asserts over the same object, and
// `check_site_invariants.py` asserts over the shipped bundle, because a compile-time check is a claim
// about the source and the reader reads the bundle.
//
// WHY WHOLE SENTENCES, WITH NAMED PLACEHOLDERS
//
// Prose here regularly wraps a file name or a link mid-sentence. Splitting such a paragraph into
// three keys would hand a translator three fragments and no grammar — Chinese puts the clause
// somewhere English does not, and a fragment cannot be reordered. So a whole sentence is one entry
// carrying `{name}` placeholders, and `<T>` substitutes React nodes into it. The translation may put
// `{file}` wherever the sentence needs it.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { STRINGS } from "./strings";
import type { Key } from "./strings";
import type { Authored } from "./types";

export type Locale = "en" | "zh-TW";

/** Index into the tuple in every `STRINGS` entry. Ordered, and the order is the tuple's order. */
export const LOCALES: readonly Locale[] = ["en", "zh-TW"];

/** What the toggle says, in the language it switches TO — never "Chinese" in English, because the
 *  reader who needs the button is the one who cannot read the label describing it. */
export const LOCALE_LABEL: Record<Locale, string> = { en: "English", "zh-TW": "中文" };

/** The document title, per language. Set from the provider rather than left to `index.html`, whose
 *  single static title is served before any JavaScript decides which language this reader wants. */
const TITLE: Record<Locale, string> = {
  en: "agentcore-guardrails-design-validation",
  "zh-TW": "agentcore-guardrails-design-validation — AgentCore 防護設計驗證",
};

const STORAGE_KEY = "agdv.locale";

function isLocale(v: unknown): v is Locale {
  return typeof v === "string" && (LOCALES as readonly string[]).includes(v);
}

/** Stored choice first, then what the browser asks for, then English.
 *
 *  `navigator.language` is a preference, not a decision: `zh-TW`, `zh-Hant`, `zh-HK` and bare `zh` all
 *  mean a reader who would rather read Chinese, and matching only the exact tag would hand most of
 *  them English while the toggle sat unused two lines below. `zh-CN` is deliberately included: this
 *  edition is Traditional, and Traditional Chinese is far closer to what that reader wants than
 *  English is. Anything unrecognised falls to English, which is the language every artifact is in. */
export function initialLocale(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (isLocale(saved)) return saved;
  } catch {
    // A browser with storage denied is not a browser that should render untranslated.
  }
  const asked = typeof navigator === "undefined" ? "" : navigator.language || "";
  return /^zh\b/i.test(asked) ? "zh-TW" : "en";
}

type Ctx = { locale: Locale; setLocale: (l: Locale) => void };

const LocaleCtx = createContext<Ctx>({ locale: "en", setLocale: () => undefined });

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);

  useEffect(() => {
    // The `lang` attribute is not decoration: it selects the font stack's CJK fallback, it tells a
    // screen reader which phonology to use, and it is what a browser's own translate offer reads.
    document.documentElement.lang = locale;
    document.title = TITLE[locale];
  }, [locale]);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      // The choice still applies to this page; it just will not survive a reload.
    }
  }, []);

  const value = useMemo(() => ({ locale, setLocale }), [locale, setLocale]);
  return <LocaleCtx.Provider value={value}>{children}</LocaleCtx.Provider>;
}

export function useLocale(): Ctx {
  return useContext(LocaleCtx);
}

/** Look one string up in one language. Exported so the test and the non-React helpers can use the
 *  same resolution the components use, rather than a second copy of the index arithmetic. */
export function resolve(locale: Locale, key: Key): string {
  const entry = STRINGS[key];
  return entry[LOCALES.indexOf(locale)] ?? entry[0];
}

export type Vars = Record<string, string | number>;

const PLACEHOLDER = /\{(\w+)\}/g;

/** Plain-text lookup, with `{name}` substitution for values that are themselves plain text.
 *  A placeholder with no value is left in place rather than blanked: `{case}` on the page is a visible
 *  defect, and an empty gap is a sentence that reads as finished and says something else. */
export function useT(): (key: Key, vars?: Vars) => string {
  const { locale } = useLocale();
  return useCallback(
    (key: Key, vars?: Vars) => {
      const raw = resolve(locale, key);
      if (!vars) return raw;
      return raw.replace(PLACEHOLDER, (whole, name: string) =>
        name in vars ? String(vars[name]) : whole,
      );
    },
    [locale],
  );
}

/** The same lookup, for a sentence whose placeholders are React nodes — a link, a `.mono` file name,
 *  a badge. Returns a fragment, so it drops straight inside a `<p>`. */
export function T({ k, v }: { k: Key; v?: Record<string, ReactNode> }) {
  const { locale } = useLocale();
  const raw = resolve(locale, k);
  if (!v) return <>{raw}</>;
  const parts = raw.split(PLACEHOLDER);
  // `String.split` with one capture group yields [text, name, text, name, …, text]: odd indices are
  // the captured names. An unknown name renders as itself, braces included, for the reason above.
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <span key={i} style={{ display: "contents" }}>
            {part in v ? v[part] : `{${part}}`}
          </span>
        ) : (
          <span key={i} style={{ display: "contents" }}>
            {part}
          </span>
        ),
      )}
    </>
  );
}

/** What a payload prose value resolves to: the text to show, and whether it is English on a page that
 *  is not. `lang` is `undefined` when the reader is getting their own language — setting `lang="en"` on
 *  a Chinese sentence would pick the Latin font stack for CJK glyphs and hand a screen reader the wrong
 *  phonology, which is the same defect as omitting it on an English one, in the other direction. */
export type Resolved = { text: string; lang?: "en" };

/** Resolve one authored-or-sealed payload value for this reader.
 *
 *  Takes `Authored | string` rather than `Authored` on purpose. Most payload surfaces are still bare
 *  strings, and a signature that refused them would force every call site to be converted in one commit
 *  — which is how a migration becomes a branch nobody merges. A bare string resolves to English marked
 *  `lang="en"`, which is the correct rendering both for a sealed quotation and for authored prose whose
 *  translation has not been written: the reader sees English either way, and is told it is English.
 *
 *  A component therefore never asks which kind it has, and cannot get the answer wrong. */
export function useAuthored(): (v: Authored | string | null | undefined) => Resolved {
  const { locale } = useLocale();
  return useCallback(
    (v: Authored | string | null | undefined): Resolved => {
      if (v == null) return { text: "" };
      if (typeof v === "string") return { text: v, lang: "en" };
      // `zh` is required by the type and non-blank by the builder, so the fallback is unreachable
      // through the payload. It is here because `v` can also arrive from a hand-written fixture, and a
      // blank sentence on the page is worse than an English one.
      if (locale !== "en" && v.zh?.trim()) return { text: v.zh };
      return { text: v.en, lang: "en" };
    },
    [locale],
  );
}

/** The same resolution, rendered. `<A v={x} />` puts the sentence in a `<span lang="en">` when English
 *  is what the reader is getting, and in a bare fragment when it is their own language — so no call
 *  site has to remember the `lang` rule, and none can apply it to a translated sentence. */
export function A({ v, className }: { v: Authored | string | null | undefined; className?: string }) {
  const a = useAuthored();
  const { text, lang } = a(v);
  if (!lang && !className) return <>{text}</>;
  return (
    <span lang={lang} className={className}>
      {text}
    </span>
  );
}

/** The language switch. Two buttons rather than a `<select>`: with exactly two options a select costs
 *  a click to discover what the other one is, and `aria-pressed` states which language is showing
 *  without needing the label to be readable in the language the reader does not have. */
export function LocaleToggle() {
  const { locale, setLocale } = useLocale();
  const t = useT();
  return (
    <div className="localesw" role="group" aria-label={t("locale.switch")}>
      {LOCALES.map((l) => (
        <button
          key={l}
          type="button"
          lang={l}
          onClick={() => setLocale(l)}
          aria-pressed={l === locale}
          className={l === locale ? "on" : ""}
          title={t("locale.switch")}
        >
          {LOCALE_LABEL[l]}
        </button>
      ))}
    </div>
  );
}

/** The standing notice that an English block on a Chinese page is the artifact's own wording.
 *  Rendered by every view that shows payload prose, and a no-op in English — where the sentence would
 *  be telling the reader that English is in English. */
export function VerbatimNote() {
  const { locale } = useLocale();
  const t = useT();
  if (locale === "en") return null;
  return (
    <p className="verbatim">
      {/* The link carries the anchor: the counts sit at the END of an eight-step page, and a link that
          lands the reader at step 1 has told them a number is published without showing it to them. */}
      <T
        k="payload.verbatim.note"
        v={{ link: <Link to="/method#translation">{t("nav.method")}</Link> }}
      />
    </p>
  );
}
