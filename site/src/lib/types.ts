// Types transcribed from a REAL payload, not from the builder's source.
//
// `platform/build/build_site_data.py` is the only writer of these files, so its code is the obvious
// place to read the shape from. That would be the wrong artifact: the emitted JSON is what the
// browser actually receives, and the two can differ (a field that is always `None` emits as `null`,
// a dict comprehension can drop a key on real data that the code reads as always-present). Every
// interface below was written against `~/Downloads/grx-site-payload` as built on 2026-08-19, which
// is why the nullable fields are nullable — each one was observed null in that build.
//
// `Verdict` deliberately has no `"PASS"` and no boolean anywhere near it. The four values are the
// study's own construction with no located precedent, INCONCLUSIVE is a first-class outcome, and any
// type that lets a caller write `verdict ? … : …` is a type that invites a pass rate.

export type Verdict = "TRUE" | "FALSE" | "INCONCLUSIVE" | "RECORDED";

export const VERDICTS: readonly Verdict[] = ["TRUE", "FALSE", "INCONCLUSIVE", "RECORDED"];

/** A denominator, and the prose that says what it counts. Never rendered without its definition. */
export interface Denominator {
  n: number;
  definition: string;
  derived_from: string;
  /** Present on some denominators only: the cases the definition excludes, named. */
  unmapped?: string[];
  untestable?: string[];
  outstanding?: string[];
}

export interface Denominators {
  registered: Denominator;
  verdict_eligible: Denominator;
  claim_mapped: Denominator;
  published: Denominator;
  claims_triaged: Denominator;
}

export interface CensusRow {
  case: string;
  family: string;
  tier: string;
  title: string;
  /** null exactly when `has_verdict` is false. Measured: 2 of 93 rows. */
  verdict: Verdict | null;
  has_verdict: boolean;
  n_claims: number;
  claims: string[];
  archive_labels: string[];
  /** A LIST, not a count — the restrictions themselves. Rendering `.length` is the caller's job. */
  citation_restrictions: CitationRestriction[];
  files_without_verdict: string[];
}

export interface Census {
  build_stamp: string;
  rows: CensusRow[];
  verdict_mix: Record<string, number>;
  seal: {
    method: string;
    n_cases_declared: number;
    registry_sha256_declared: string;
    registry_sha256_recomputed: string;
  };
}

export interface CitationRestriction {
  restriction: string;
  reason: string;
  source: string;
  cases?: string[];
  subject?: string;
  citable_as?: string[];
  not_citable_as?: string[];
  verdict_on_disk?: string;
}

export interface CitationPolicy {
  schema: string;
  authoritative_for_tooling: boolean;
  note: string;
  body_md: string;
  restrictions: CitationRestriction[];
  non_case_restrictions: CitationRestriction[];
}

export interface ArchiveEntry {
  file: string;
  label: string;
  run_id: string;
  sha256: string;
  /** The verdict THAT archived file holds — which is the whole point of the replication panel: a
   *  `day2_indecisive_*` entry can carry a different verdict from the live file, and the UI must show
   *  both rather than implying the archive agrees. */
  verdict: string;
}

/** One case, as the drill-down renders it. `record` is the verdict file's own body, untouched. */
export interface CaseDetail {
  case: string;
  family: string;
  tier: string;
  title: string;
  verdict: Verdict | null;
  verdict_file: string | null;
  instrument: string;
  /** The SEALED oracle text. Rendered verbatim and quoted, never paraphrased and never summarised. */
  oracle_text: string;
  oracle_is_sealed: boolean;
  claims: string[];
  archive: ArchiveEntry[];
  citation_restrictions: CitationRestriction[];
  series_available: string[];
  record: Record<string, unknown>;
}

export interface RegisterItem {
  n: number;
  tier: string;
  title: string;
  body_md: string;
}

export interface Registers {
  n_items: number;
  items: RegisterItem[];
  side_registers: Record<string, string | null>;
}

export interface Finding {
  file: string;
  title: string;
  sha256: string;
  body_md: string;
  provenance: Record<string, unknown>;
}

export interface FigurePresent {
  file: string;
  bytes: number;
  sha256: string;
  /** The repo path the served bytes were copied from. Present because the build — not the publisher —
   *  copies the PNGs, so every served image has a manifest hash and a provenance entry pointing here. */
  source: string;
}

export interface Figures {
  manifest: {
    generated_by: string;
    matplotlib: string;
    note: string;
    register_sha256_recomputed: string;
    figures: Record<string, unknown>;
  };
  present: FigurePresent[];
  missing: string[];
  /** rc of `whitepaper_figures.py --check`. **null means the build did not run it** — which is not
   * the same as a pass, and the freshness badge must say so rather than defaulting to fresh. */
  numeric_check: number | null;
  numeric_check_note: string;
  /** What a text-pattern gate cannot see in a PNG. Rendered on the gallery: an unstated limit reads
   *  as a check that passed. */
  redaction_note: string;
}

/** EVERY FIELD IS A STRING, INCLUDING THE NUMERIC-LOOKING ONES.
 *
 * `claims.json` carries `claims/triage.csv` through as it stands, and that file is SEALED — so the
 * builder does not coerce `doc_line` to a number, split `cases` on whitespace, or turn an empty cell
 * into null, because each of those is an edit to a sealed artifact's meaning performed on the way to
 * the screen. `cases` is the raw cell, so a row naming two cases is one string with a space in it.
 * Anything that needs a number parses it at the point of use and shows the raw cell beside it. */
export interface ClaimRow {
  claim_id: string;
  anchor: string;
  doc_line: string;
  cls: string;
  cases: string;
  canonical: string;
  merge_group: string;
  merged_into: string;
  exclusion_reason: string;
  note: string;
  ordinal: string;
  rule: string;
  sha1: string;
  text: string;
  unit_type: string;
}

export interface Claims {
  n_rows: number;
  rows: ClaimRow[];
  by_case: Record<string, string[]>;
}

/** One family's authored operational classification, from `platform/curation/families.yaml`.
 *
 * The required fields are non-optional here because the build refuses to emit a family that omits
 * any of them, in either direction (a registered family absent from the curation file, or an entry
 * for no registered family, both fail the build). Marking them optional in the type would let a
 * component write `flags?.schedulable` and treat an unclassified family as unrestricted — which is
 * exactly the "safe by omission" reading the build-time check exists to make impossible. */
export interface FamilyFlags {
  label: string;
  cost: string;
  runner: string;
  mutates: string;
  schedulable: boolean;
  network_position_sensitive: boolean;
  n_cases: number;
  why_not_schedulable?: string;
  /** Rendered as a banner over every case in the family. Required by the build when
   *  `network_position_sensitive` is true, so an empty banner cannot ship. */
  why?: string;
  replication_requirement?: string;
  ui_state_when_old?: string;
  ui_state_note?: string;
  calendar_gate?: string;
  note?: string;
  directory?: string | null;
  directory_note?: string;
}

export interface Families {
  schema: string | null;
  vocabularies: Record<string, string[]>;
  families: Record<string, FamilyFlags>;
  note: string;
}

export interface Manifest {
  tool: string;
  build_stamp: string;
  n_inputs: number;
  n_outputs: number;
  note: string;
  inputs_sha256: Record<string, string>;
  outputs_sha256: Record<string, string>;
  /** output path -> the repo paths whose bytes it was derived from. Typed as a list, not `unknown`,
   *  because the provenance view asserts against it: an output whose list is empty was produced from
   *  nothing the build declared reading, and that is a defect the page must be able to state. */
  provenance: Record<string, string[]>;
}

/** Derived at build time from the verdict files and the archive. Nothing here is authored, and no
 *  count is stored: a page that wants a number asks this file, so the method walkthrough cannot
 *  drift from the corpus it describes. */
export interface Method {
  /** oracle kind -> how many published cases use it */
  kinds: Record<string, number>;
  /** guard name -> how many cases name it. Includes the explicit unnamed bucket. */
  guard_names: Record<string, number>;
  caveats: {
    true_verdicts: number;
    false_verdicts: number;
    cases_with_what_true_does_not_prove: number;
    cases_with_what_false_does_not_prove: number;
    true_verdicts_without_the_caveat: string[];
    false_verdicts_without_the_caveat: string[];
    why_this_is_counted: string;
  };
  archive_days_by_case: Record<string, string[]>;
  n_cases_with_an_archive: number;
  n_cases_with_two_distinct_archive_days: number;
  archives_disagreeing_with_the_live_verdict: {
    case: string;
    label: string;
    archived_verdict: string;
    live_verdict: string | null;
  }[];
  note: string;
}
