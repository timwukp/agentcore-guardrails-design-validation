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
  /** A bound on the reading written by a later reader of the record, for the cases the record itself
   *  leaves silent. Deliberately OUTSIDE `record`, so a reader diffing this page against
   *  `results/phase1/<case>.json` finds the record byte-identical and cannot mistake authored prose for
   *  a producer's own sentence. Absent on every case whose record speaks for itself. */
  authored_caveat?: AuthoredCaveat;
}

/** @see CaseDetail.authored_caveat — the provenance travels with the sentence, because a caveat whose
 *  author is stated somewhere else on the page is a caveat read as the study's own. */
export interface AuthoredCaveat {
  why: string;
  verdict: string;
  derived_from: string[];
  authored_by: string;
  authored_on: string;
  authored_from: string;
  review_status: string;
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

/** View 9's data layer — "what has this platform actually observed lately", derived at build time from
 *  the verdict records, the archive and the authored cadences.
 *
 *  WHY THERE IS NO PROGRESS FIELD IN THIS TYPE
 *
 *  A family is a set of cases, not a job with a fraction done. There is deliberately no percentage and
 *  no completion figure anywhere in this shape, because any denominator over a set containing "never
 *  observed" produces a number that reads as progress and is not one. The states are the answer.
 *
 *  `state` is a closed vocabulary and every member is a first-class outcome, including the three that
 *  no amount of scheduling can clear: CALENDAR GATED (the comparison is only meaningful in a particular
 *  billing period), HUMAN DECISION REQUIRED (the family mutates something a human must approve and
 *  restore), REQUIRES A LOCAL RUN (F6 — the estimator is a paired difference of client-measured wall
 *  clocks, so a re-run from anywhere else is a new measurement, not a replication). None of those may
 *  ever render as STALE: staleness is pressure toward a run, and for those three the run it would
 *  pressure somebody into is the wrong act. */
export type PipelineState =
  | "WITHIN CADENCE"
  | "STALE"
  | "NOT OBSERVED"
  | "CALENDAR GATED"
  | "HUMAN DECISION REQUIRED"
  | "REQUIRES A LOCAL RUN";

/** Counts of the four mutually exclusive replication buckets. `disagreeing` wins over the others, which
 *  is why `n_with_two_or_more_archived_days` sits beside them: today every case with two archived days
 *  is one whose archive disagrees with the live verdict, so the agreeing bucket reads 0 and, alone,
 *  would say "no case has ever been measured twice". */
export interface ReplicationCounts {
  no_archived_prior_day: number;
  one_archived_prior_day: number;
  two_or_more_archived_days_agreeing: number;
  disagreeing: number;
}

export interface PipelineFamily {
  family: string;
  label: string;
  state: PipelineState;
  /** One sentence naming the numbers behind `state`, composed by the build so the page and the state
   *  machine cannot drift apart. */
  statement: string;
  schedulable: boolean;
  network_position_sensitive: boolean;
  /** Null exactly when the family is not schedulable or is calendar gated — the build refuses a
   *  schedulable family with no cadence (nothing could ever call it stale) and a non-schedulable one
   *  with a cadence (it would badge itself stale and its only remedy is a forbidden run). */
  cadence_days: number | null;
  why_cadence: string | null;
  first_observed_utc_day: string | null;
  last_observed_utc_day: string | null;
  days_since_last_observation: number | null;
  n_cases: number;
  n_with_verdict: number;
  n_with_no_observed_day: number;
  n_with_two_or_more_archived_days: number;
  cases_with_no_observed_day: string[];
  /** Has a verdict and nothing archived: a replication is owed. Kept apart from the list below because
   *  one list carrying both labels would report 53 unknown days as a replication backlog. */
  cases_owing_a_second_day: string[];
  cases_whose_observation_day_is_unknown: string[];
  cases_in_disagreement: string[];
  replication: ReplicationCounts;
  /** A vocabulary token for a component to key on, never a sentence to render. The sentences are the
   *  two fields below, and the build requires them where they are load bearing: a family that is not
   *  schedulable must state why, and a network-position-sensitive one must state what a replication of
   *  it has to hold fixed. */
  ui_state_when_old: string | null;
  why_not_schedulable: string | null;
  replication_requirement: string | null;
  /** Repo-relative file the three fields above were copied from. Present so the publish gate can find
   *  any replication sentence verbatim in its origin and thereby prove the build quoted rather than
   *  composed it; rendered as the provenance line under the family table. */
  source: string | null;
}

export interface PipelineCase {
  case: string;
  family: string;
  has_verdict: boolean;
  observation_days: string[];
  days_from_the_record: string[];
  days_from_the_archive: string[];
  n_distinct_days: number;
  /** Distinct UTC days among the ARCHIVED artifacts alone. Two timestamps inside one evidence file are
   *  one run that crossed midnight; only a separate archived file establishes a prior occasion. */
  n_archived_prior_days: number;
  observation_days_after_the_as_of_day: string[];
  replication: keyof ReplicationCounts;
  disagreements: { file: string; label: string; verdict: string; run_id?: string; sha256?: string }[];
}

export interface Pipeline {
  schema: string;
  /** The day the payload was built against, which is NOT necessarily today: `--stamp` is caller
   *  supplied and a back-dated build is legitimate. Every age on this page is measured from here. */
  as_of_utc_day: string;
  as_of_note: string;
  as_of_precedes_some_observations: string[];
  states: PipelineState[];
  families: Record<string, PipelineFamily>;
  cases: Record<string, PipelineCase>;
  totals: {
    n_cases: number;
    n_with_no_observed_day: number;
    n_no_archived_prior_day: number;
    n_one_archived_prior_day: number;
    n_two_or_more_archived_days_agreeing: number;
    n_with_two_or_more_archived_days: number;
    n_disagreeing: number;
    families_stale: string[];
    families_not_observed: string[];
    why_replication_is_counted_from_the_archive_only: string;
  };
  note: string;
}

// ---------------------------------------------------------------------------------------------
// controls.json — what an audit looks for, and which cases measured each control.
//
// `detect.paths` and `type_hint` are what the parser matches on, and they are rendered rather than
// summarised: a reader deciding whether to trust a DECLARED result needs to see the property path that
// produced it. `type_hint` is a string OR a list, because one control can live on more than one
// resource shape (`executionRoleArn` on a harness, `roleArn` on a gateway).

export type ControlStatus =
  | "measured_true"
  | "measured_false"
  | "not_established"
  | "not_measured"
  | "context_only";

export interface ControlCite {
  case: string;
  family: string;
  title: string;
  verdict: string | null;
  has_verdict: boolean;
  restrictions: string[];
  why?: string | null;
}

export interface ControlFinding {
  status: ControlStatus | string;
  /** The declared value this finding is conditioned on, as `{value: "LOG_ONLY"}` — always an object,
   *  empty when the finding holds whatever the template says. */
  when: Record<string, string>;
  says: string | null;
  consequence: string | null;
  scope_note: string | null;
  why_not_measured: string | null;
  cites: ControlCite[];
}

export interface Control {
  id: string;
  label: string;
  question: string;
  detect: {
    type_hint?: string | string[];
    paths?: string[];
    value_from?: string | null;
    values?: string[] | null;
    paths_source?: string | null;
  };
  measured: string | null;
  why_not_measured: string | null;
  measured_by: ControlCite[];
  findings: ControlFinding[];
  statuses: string[];
  n_cases: number;
}

export interface ControlsDoc {
  schema: string;
  field_paths: { derived_on?: string; instrument?: string; note?: string };
  vocabularies: { status: string[]; observation: string[] };
  unverifiable_paths: { path: string; why: string }[];
  controls: Control[];
  n_controls: number;
  controls_by_status: Record<string, number>;
  note: string;
}

// ---------------------------------------------------------------------------------------------
// audit.json — the worked example, derived at build time by running the two audit programs over the
// checked-in example submission. The shapes below are `grx-inventory/1` and `grx-audit-report/1`,
// which is also what a reader's own local run emits — the same types render both.

export interface InventorySite {
  resource: string;
  resource_type: string;
  file: string;
  line: number;
  path: string;
  matched_rule_path: string;
  source_kind: string;
  value?: string | null;
  unresolved_tag?: string | null;
}

/** A case as a report line cites it. `limits_stated_by_the_case` is separate from the text because a
 *  case that states no limit is the interesting case: false renders as a caveat, not as a blank. */
/** One IaC resource the parser recognised. `n_properties` rather than the properties themselves: the
 *  inventory records where a control was found, not the reader's whole template. */
export interface InventoryResource {
  logical_id: string;
  type: string;
  file: string;
  line: number;
  source_kind: string;
  n_properties: number;
}

export interface ReportCase {
  case: string;
  verdict: string;
  restrictions: string[];
  what_this_verdict_does_not_prove: string | null;
  limits_stated_by_the_case: boolean;
}

export interface ReportMeasurement {
  status: string;
  status_label: string;
  says: string | null;
  consequence: string | null;
  scope_note: string | null;
  why_not_measured: string | null;
  cases: ReportCase[];
}

/** What the PARSER saw, with no reference to the study. This is the whole of an `inventory.json`
 *  observation, and it is deliberately a separate type from the report line below: the reader's own
 *  local run produces this file without ever consulting a verdict, and a component handed one must not
 *  be able to reach for `measurements` and render `undefined` as "nothing measured". */
export interface InventoryObservation {
  control: string;
  label: string;
  observation: "DECLARED" | "NOT_DECLARED" | string;
  value: string | null;
  values_seen: string[];
  sites: InventorySite[];
  unresolved: InventorySite[];
}

/** The parser's observation joined to what the study measured about it. */
export interface ReportControlLine extends InventoryObservation {
  question: string;
  /** Present when one control is declared with two different values across the parsed files — a real
   *  state of a real submission (a staging template disagreeing with production), never an error. */
  disagreement: string[] | null;
  values_outside_the_declared_enum: string[] | null;
  why_this_status: string | null;
  statuses: string[];
  measurements: ReportMeasurement[];
}

export interface AuditReport {
  schema: string;
  as_of: string | null;
  evidence_through_at_least: string | null;
  study: {
    cases_registered: number;
    verdicts_published: number;
    verdict_mix: Record<string, number>;
    controls_this_study_can_speak_to: number;
  };
  headline: {
    statement: string;
    controls_the_study_covers: number;
    controls_you_declare: number;
    declared_with_a_measurement: number;
    declared_where_the_guidance_did_not_hold: number;
    declared_never_measured_by_this_study: number;
    declared_in_a_state_no_measurement_covers: number;
    not_seen_in_the_parsed_files: number;
    why_this_report_gives_no_ratio: string;
  };
  inventory: { submission: Record<string, unknown>; resources: InventoryResource[] };
  controls: ReportControlLine[];
  recommendations: {
    control: string;
    label: string;
    observation: string;
    because: string;
    recommendation: string;
    licensed_by: { case: string; verdict: string }[];
    scope_note: string | null;
    sites: string[];
  }[];
  recommendations_withheld: { control: string; status: string; why_withheld: string }[];
  caveats: string[];
}

export interface AuditPage {
  schema: string;
  example: {
    submission: string;
    files: { file: string; bytes: number; source: string }[];
    n_files: number;
    n_controls_declared: number;
    is_synthetic: boolean;
    why_synthetic: string;
  };
  inventory: {
    schema: string;
    submission: Record<string, number | boolean | string | unknown[]>;
    caveats: string[];
    observations: InventoryObservation[];
    resources: InventoryResource[];
  };
  report: AuditReport;
  markdown: string;
  tools: { parse: string; report: string; commands: string[] };
  boundaries: { claim: string; how: string }[];
  note: string;
}

// --------------------------------------------------------------------------- the two diagrams
//
// The split this type records is the point of the view: `platform/curation/architecture.yaml` authors
// WHICH boxes exist, which edges connect them, and which cases are ABOUT which component — judgments no
// artifact in the repository holds. Everything else below is derived at build time from the register,
// `results/phase1/` and the citation policy. So `status`, `verdict_mix`, `count` and every coordinate
// arrive as data, and no component may compute one: a status decided in TypeScript would be a second
// source of truth for the most quotable thing this platform publishes.

/** A case as it appears ON a box: enough to label a chip and to justify the colour, no more. The heavy
 *  per-case record stays in `cases/<CASE>.json`, reached by the chip's link. */
export interface ArchCase {
  case: string;
  family: string;
  title: string;
  verdict: Verdict | string | null;
  restrictions: string[];
}

export type ArchStatus =
  | "contested"
  | "validated_in_part"
  | "not_established"
  | "context_only"
  | "not_measured";

export interface ArchBox {
  id: string;
  label: string;
  detail: string;
  kind: string;
  /** The repo-relative script this step runs, for the boxes that are steps. Null for a component in
   *  somebody else's deployment, which is most of the second diagram. */
  program: string | null;
  venv: string;
  machine: string;
  cases: ArchCase[];
  n_cases: number;
  why_these_cases: string | null;
  /** `"none"` when the authored file states in writing that this box was never measured; null when it
   *  carries cases instead. Exactly one of the two is ever set — the gate refuses both and neither. */
  measured: string | null;
  why_not_measured: string | null;
  status: ArchStatus | string;
  status_label: string;
  why_this_status: string;
  verdict_mix: Record<string, number>;
  restrictions: string[];
  count_from: string | null;
  count: number | null;
  /** Layout, computed from the authored edges by `build_site_data._layout`. Rendered as given: a view
   *  that nudged a coordinate would invalidate the zero-crossing assertion that licenses the picture. */
  x: number;
  y: number;
  w: number;
  h: number;
  row: number;
  column: number;
}

/** `spine` is the request/step order, `property` hangs a facet off the box to its left, `gutter` is a
 *  row-skipping edge routed left of the spine. The three occupy disjoint bands, which is what makes the
 *  crossing count provably zero rather than merely small. */
export type ArchRoute = "spine" | "property" | "gutter";

export interface ArchEdge {
  from: string;
  to: string;
  kind: string;
  label: string;
  /** An axis-aligned polyline in the diagram's own coordinates. */
  points: [number, number][];
  route: ArchRoute | string;
  lane: number;
}

export interface ArchDiagram {
  id: string;
  label: string;
  subtitle: string;
  why_this_diagram: string;
  boxes: ArchBox[];
  edges: ArchEdge[];
  viewbox: { min_x: number; min_y: number; width: number; height: number };
  boxes_by_status: Record<string, number>;
  n_boxes: number;
  n_edges: number;
}

export interface Architecture {
  schema: string;
  vocabularies: Record<string, string[]>;
  diagrams: ArchDiagram[];
  metrics: Record<string, number>;
  unplaced_cases: (ArchCase & { why: string })[];
  coverage: {
    n_registered: number;
    n_placed: number;
    n_unplaced: number;
    placed_on: Record<string, string[]>;
    why: string;
  };
  status_labels: Record<string, string>;
  non_colouring_restrictions: string[];
  geometry: { box_w: number; box_h: number; col_pitch: number; row_pitch: number; why: string };
  mapped_by: string;
  mapped_on: string;
  note: string;
}
