/** Case ids are `F<family>-<n>` with optional suffixes, so lexicographic order puts F10-1 before
 *  F2-1 and F1-2 before F1-19. Both are wrong in a register a reader scans by family. This compares
 *  the numeric runs numerically and the rest as text, which orders F1-2 < F1-19 < F2-1 < F10-1. */
export function byCaseId(a: string, b: string): number {
  const pa = a.match(/\d+|\D+/g) ?? [];
  const pb = b.match(/\d+|\D+/g) ?? [];
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const x = pa[i];
    const y = pb[i];
    if (x === undefined) return -1;
    if (y === undefined) return 1;
    const nx = /^\d/.test(x);
    const ny = /^\d/.test(y);
    if (nx && ny) {
      const d = Number(x) - Number(y);
      if (d !== 0) return d;
    } else if (x !== y) {
      return x < y ? -1 : 1;
    }
  }
  return 0;
}

/** Distinct values of a field, in case-id order of first appearance made deterministic by sorting. */
export function distinct(values: string[]): string[] {
  return [...new Set(values)].sort((a, b) => byCaseId(a, b));
}
