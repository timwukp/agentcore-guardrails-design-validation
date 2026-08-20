// The only place the app reads bytes. Everything else takes typed data as props.
//
// TWO FAILURE MODES THIS FILE EXISTS TO PREVENT
//
// 1. A 404 rendered as content. The app is served from S3 behind CloudFront with **no**
//    404 -> index.html rewrite, deliberately (that is also why routing is a HashRouter): with a
//    rewrite in place, a missing `data/cases/F9-9.json` returns HTTP 200 carrying `index.html`, and
//    `res.json()` then throws a JSON parse error that reads like a corrupt payload rather than a
//    missing file. Even so, this layer refuses to trust the status alone — it checks the
//    content-type and reports the two cases differently, because "the file is not there" and "the
//    file is not JSON" have different causes and different fixes.
//
// 2. A stale build's numbers rendered under a fresh build's stamp. Every fetch is against the SAME
//    origin-relative prefix, and `loadManifest()` is the one thing the shell fetches first, so a
//    reader can always see which build they are looking at. There is no cache-busting query string:
//    the payload is published to an immutable `v/<stamp>/` prefix and served with a long max-age,
//    so freshness is a property of the URL, not of a parameter.

export class PayloadError extends Error {
  constructor(
    readonly path: string,
    readonly kind: "missing" | "not-json" | "network",
    detail: string,
  ) {
    super(`${path}: ${detail}`);
    this.name = "PayloadError";
  }
}

/** Where the payload lives. Kept a single constant so nothing can build a path by concatenating
 *  user input and reach outside the prefix.
 *
 *  `import.meta.env.BASE_URL` is Vite's build-time `base`, and using it here is what makes one build
 *  work from TWO URLs at once. `publish_web.py` builds with `--base=/v/<stamp>/` and uploads the
 *  bundle there, then places a COPY of that `index.html` at the distribution root as the pointer to
 *  the current release. So the same document is fetched as `https://host/` and as
 *  `https://host/v/<stamp>/`, and only an absolute payload prefix resolves correctly from both: a
 *  relative `"data"` would resolve to `https://host/data/…` for the root copy, where nothing is
 *  published.
 *
 *  This is NOT an environment variable in the sense `vite.config.ts` forbids — `BASE_URL` is a URL
 *  path this build was compiled for, carries no account id, no host and no secret, and is inspectable
 *  in the served bundle. Locally `base` stays `"./"`, so `BASE_URL` is `"./"`, the prefix is
 *  `"./data"`, and `csp_preview.py` serving `site/dist` at the root is unaffected. */
const PREFIX = `${import.meta.env.BASE_URL}data`;

async function getJson<T>(rel: string): Promise<T> {
  const path = `${PREFIX}/${rel}`;
  let res: Response;
  try {
    res = await fetch(path, { credentials: "same-origin" });
  } catch (e) {
    throw new PayloadError(path, "network", e instanceof Error ? e.message : String(e));
  }
  if (res.status === 404) {
    throw new PayloadError(path, "missing", "HTTP 404 — this file is not in the published payload");
  }
  if (!res.ok) {
    throw new PayloadError(path, "network", `HTTP ${res.status}`);
  }
  const ct = res.headers.get("content-type") ?? "";
  if (!ct.includes("json")) {
    // The signature of a rewrite rule turning a missing file into a 200 HTML page.
    throw new PayloadError(
      path,
      "not-json",
      `served as ${ct || "an unknown type"} rather than JSON — a missing file may be being ` +
        `rewritten to index.html, which would make an absent case look like a corrupt one`,
    );
  }
  return (await res.json()) as T;
}

export const loadManifest = () => getJson<import("./types").Manifest>("MANIFEST.json");
export const loadCensus = () => getJson<import("./types").Census>("census.json");
export const loadDenominators = () => getJson<import("./types").Denominators>("denominators.json");
export const loadRegisters = () => getJson<import("./types").Registers>("registers.json");
export const loadFigures = () => getJson<import("./types").Figures>("figures.json");
export const loadFamilies = () => getJson<import("./types").Families>("families.json");
export const loadMethod = () => getJson<import("./types").Method>("method.json");
export const loadPipeline = () => getJson<import("./types").Pipeline>("pipeline.json");
export const loadControls = () => getJson<import("./types").ControlsDoc>("controls.json");
export const loadAudit = () => getJson<import("./types").AuditPage>("audit.json");
export const loadArchitecture = () =>
  getJson<import("./types").Architecture>("architecture.json");
export const loadClaims = () => getJson<import("./types").Claims>("claims.json");
export const loadCitationPolicy = () =>
  getJson<import("./types").CitationPolicy>("citation_policy.json");
export const loadFindings = () =>
  getJson<{ findings: import("./types").Finding[] }>("findings.json");

/** A case id is used to build a path, so it is validated against the shape the register uses rather
 *  than trusted. Any other value cannot produce a fetch at all. */
export function isCaseId(s: string): boolean {
  return /^F\d{1,2}-\d{1,2}[a-z]?(_[A-Za-z0-9]+)?$/.test(s);
}

export function loadCase(caseId: string) {
  if (!isCaseId(caseId)) {
    return Promise.reject(
      new PayloadError(`cases/${caseId}.json`, "missing", "not a well-formed case id"),
    );
  }
  return getJson<import("./types").CaseDetail>(`cases/${caseId}.json`);
}

export function loadSeries(caseId: string) {
  if (!isCaseId(caseId)) {
    return Promise.reject(
      new PayloadError(`series/${caseId}.json`, "missing", "not a well-formed case id"),
    );
  }
  return getJson<{ case: string; series: Record<string, unknown> }>(`series/${caseId}.json`);
}

/** Figure PNGs are copied into the payload beside the JSON by `publish_web.py`. */
export const figureUrl = (file: string) => `${PREFIX}/figures/${file}`;
