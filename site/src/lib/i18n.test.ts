// Run with: node --test site/src/lib/i18n.test.ts
//
// WHAT THIS FILE IS FOR: THE PROPERTIES THE TYPE CHECKER CANNOT SEE
//
// `strings.ts` is one dictionary whose every value is a `readonly [en, zhTW]` tuple, closed with
// `as const satisfies Record<string, Entry>`. That construction already makes the failure mode this
// project would otherwise have hit unrepresentable: there is no second locale object to drift from, so a
// key cannot exist in one language and be missing from the other, and a translation left out is a tuple
// of the wrong length — a compile error, not a blank on a page.
//
// What `tsc` cannot see is whether a value SAYS anything. `["Coverage", ""]` type-checks. So does
// `["Coverage", "Coverage"]`, which is the likelier accident: a key added in a hurry with the English
// pasted into both slots renders an English page to a Chinese reader while every mechanical check passes.
// So does a placeholder dropped from one side — `{n}` present in the English and absent from the Chinese
// silently deletes a number from one language only, which is the worst of the three because the sentence
// still reads as a complete sentence.
//
// These are exactly the properties a test can assert and a type cannot, and they are asserted here over
// the WHOLE dictionary rather than sampled, because the population is a few hundred entries and a
// sampling test would pass for the entry nobody looked at.
//
// The Python publish gate is the other half and not a substitute for this one: it reads the shipped
// bundle's bytes, so it can see that both locale tags shipped and that the pass-rate denial survived
// minification, but it cannot see that key `arc.h.coverage` in particular has a Chinese value.

import assert from "node:assert/strict";
import test from "node:test";
import { STRINGS } from "./strings.ts";

/** Han ideographs only. Deliberately NOT including CJK punctuation: a value consisting of `，` would
 *  satisfy a punctuation-inclusive range while saying nothing, and "nothing" is the state this file
 *  exists to catch. */
const HAN = /[㐀-䶿一-鿿豈-﫿]/;

/** Keys whose Chinese is legitimately identical to the English, each because the value is not prose but
 *  a token a reader greps for elsewhere. The list is asserted to be EXACT below, in both directions: a
 *  key that gets a real translation later must fall off this list rather than sit here excusing itself,
 *  and a new untranslated key cannot hide behind the existence of the concept of an exception. */
const UNTRANSLATED: Record<string, string> = {
  "cs.rep.th.sha": "the name of the hash function, as the archive table's other columns spell it",
};

const entries = Object.entries(STRINGS) as [string, readonly [string, string]][];

test("the dictionary is not empty and every entry is a pair of two non-blank strings", () => {
  // A floor, not a count: asserting the exact number of keys would turn every added string into a
  // failing test, and the property that matters is "the dictionary was not tree-shaken to nothing".
  assert.ok(entries.length > 300, `only ${entries.length} entries`);
  for (const [k, pair] of entries) {
    assert.equal(pair.length, 2, `${k} is not a pair`);
    for (const [i, v] of pair.entries()) {
      assert.equal(typeof v, "string", `${k}[${i}] is not a string`);
      assert.ok(v.trim().length > 0, `${k}[${i}] is blank`);
    }
  }
});

test("every Chinese value contains Han characters, or is a named exception", () => {
  const missing = entries.filter(([, [, zh]]) => !HAN.test(zh)).map(([k]) => k);
  assert.deepEqual(missing, Object.keys(UNTRANSLATED).sort());
});

test("no Chinese value is a copy of its English", () => {
  const copied = entries.filter(([, [en, zh]]) => en === zh).map(([k]) => k);
  assert.deepEqual(copied, Object.keys(UNTRANSLATED).sort());
});

test("every exception is really an exception", () => {
  // The two assertions above compare against this list; without this one the list could name a key that
  // no longer needs excusing, and a stale exemption is how the next untranslated string gets in.
  for (const k of Object.keys(UNTRANSLATED)) {
    const pair = STRINGS[k as keyof typeof STRINGS] as readonly [string, string] | undefined;
    assert.ok(pair, `${k} is exempted but does not exist`);
    assert.equal(pair[0], pair[1], `${k} is exempted but its two values now differ`);
  }
});

// --------------------------------------------------------------------------- substitution

const NAMES = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

test("both languages of a key take exactly the same placeholders", () => {
  for (const [k, [en, zh]] of entries) {
    assert.deepEqual(
      NAMES(zh),
      NAMES(en),
      `${k}: a placeholder present in one language and absent from the other deletes a value from ` +
        `that language only, and the sentence still reads as a whole sentence`,
    );
  }
});

test("no brace in any value is anything other than a placeholder", () => {
  // `useT` and `T` both substitute on `/\{(\w+)\}/g`. A typo like `{ n }` or `{case-id}` does not match,
  // so it survives into the rendered page as literal braces — visible, but only to whoever looks.
  for (const [k, pair] of entries) {
    for (const [i, v] of pair.entries()) {
      const rest = v.replace(/\{\w+\}/g, "");
      assert.ok(!rest.includes("{") && !rest.includes("}"), `${k}[${i}] has a malformed placeholder`);
    }
  }
});

// --------------------------------------------------------------------------- what may not be typed here

test("no value contains a case id", () => {
  // Case ids come from the payload, always. One typed into a sentence here is a fact with no artifact
  // behind it — and it would keep rendering after the case it names stopped being published.
  for (const [k, pair] of entries) {
    for (const [i, v] of pair.entries()) {
      const hit = /\bF\d+-\d+[a-z]?\b/.exec(v);
      assert.equal(hit, null, `${k}[${i}] names ${hit?.[0]}`);
    }
  }
});

test("the pass rate is denied in both languages and asserted in neither", () => {
  // The rule the whole platform rests on, checked at its source. `check_site_invariants.py` checks the
  // same property over the shipped bundle; this checks it over the dictionary, where a mistake is made.
  let en = 0;
  let zh = 0;
  for (const [k, pair] of entries) {
    for (const m of pair[0].matchAll(/pass rate/gi)) {
      en++;
      const before = pair[0].slice(0, m.index).toLowerCase();
      assert.match(before, /(there is no|is not a)\s*$/, `${k} (en) states a pass rate: ${m[0]}`);
    }
    for (const m of pair[1].matchAll(/通過率/g)) {
      zh++;
      assert.equal(
        pair[1].slice(Math.max(0, m.index - 2), m.index),
        "沒有",
        `${k} (zh) states a pass rate rather than denying one`,
      );
    }
  }
  // Counted, not just checked: a build that deleted the denial from one language would pass every
  // assertion above by having nothing left to check.
  assert.ok(en >= 3, `only ${en} English denial(s)`);
  assert.equal(zh, en, `${en} English denial(s) but ${zh} Chinese`);
});
