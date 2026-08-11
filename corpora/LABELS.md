# LABELS — corpus provenance and the validity audit

Referenced by `PREREGISTRATION.yaml` → `corpora.labelling.provenance`. The protocol
that fixes label *semantics* is `corpora/labeling_protocol.md`; this file records
what was actually built and what the audit of it found.

- **Pre-registration:** `6eb1ba6e09d474e6310aff0010d77fc4d7dcfeed56905b37e4e895043923e8e4`
- **Total items:** 1917 across 49 files
- **Builder:** `corpora/build.py` — deterministic, no RNG. Rebuilding produces
  byte-identical files; `MANIFEST.json` carries a sha256 per file.
- **Cohen's κ:** **0.9593** against a gate of 0.8 → **PASS**
  (300 items rated, raw agreement 0.9633,
  0 `UNSURE` counted as disagreement)

---

## 1. What κ here is, and is not

Agreement between ONE rater and the constructive label — a validity measure. It is NOT the plan's two-independent-human reliability kappa; one rater exists in this project. It licenses 'the templates produce what they claim' and says nothing about how a different rater would label these items, because the same person wrote the definitions, the templates and the ratings. A second human rater remains an open item, and passing this gate is necessary for Phase 1 and NOT sufficient for publishing the corpus as human-validated.

**It is also conservative, for a structural reason.**
HARD_NEGATIVE is not disjoint from CLEAN. The protocol (§3) defines it as 'CLEAN, AND the text contains features characteristic of an attack class', so HARD_NEGATIVE is a SUBSET of CLEAN and a rater answering CLEAN has not made an error — the two labels differ in a judgement about resemblance, not in a claim about the text. Every CLEAN-for-HARD_NEGATIVE disagreement below is of that kind, so the reported kappa is a LOWER bound on validity rather than an unbiased estimate. The overlap is left in rather than collapsed: merging the labels would raise kappa without improving the corpus, and F3-3 needs the two cells kept apart because it computes a separate FPR over each.

---

## 2. Provenance by file

Every item carries `id` (a content hash), `label`, `text`, `template_id`, `slot`,
`surface` and `source`. `source` is `generated` or `reused:<path>`, so no item's
origin is a matter of recollection.

| file | items | labels | sha256 |
|:---|---:|:---|:---|
| `benign/benign.jsonl` | 110 | CLEAN | `0ce0aaa07dcd607e…` |
| `content_filter/hate.jsonl` | 120 | HATE | `a938eb78c9cb4c4d…` |
| `content_filter/insults.jsonl` | 120 | INSULTS | `ffeda3f4d5ac4718…` |
| `content_filter/misconduct.jsonl` | 120 | MISCONDUCT | `8d98240da49903fe…` |
| `content_filter/sexual.jsonl` | 120 | SEXUAL | `b2d3d71a3fc37f43…` |
| `content_filter/violence.jsonl` | 120 | VIOLENCE | `ee329a6a93dd5115…` |
| `hard_negatives/hard_negatives.jsonl` | 60 | HARD_NEGATIVE | `c09afb82bf758066…` |
| `multilingual/en.jsonl` | 60 | CLEAN, HATE, INSULTS, JAILBREAK, MISCONDUCT, PROMPT_INJECTION, PROMPT_LEAKAGE, VIOLENCE | `af0aa3864516bcaa…` |
| `multilingual/es.jsonl` | 60 | CLEAN, HATE, INSULTS, JAILBREAK, MISCONDUCT, PROMPT_INJECTION, PROMPT_LEAKAGE, VIOLENCE | `1073d77701e56567…` |
| `multilingual/fr.jsonl` | 60 | CLEAN, HATE, INSULTS, JAILBREAK, MISCONDUCT, PROMPT_INJECTION, PROMPT_LEAKAGE, VIOLENCE | `cc901dd39caae30b…` |
| `multilingual/ja.jsonl` | 60 | CLEAN, HATE, INSULTS, JAILBREAK, MISCONDUCT, PROMPT_INJECTION, PROMPT_LEAKAGE, VIOLENCE | `e5e8ea6a7f1df4f1…` |
| `multilingual/ko.jsonl` | 60 | CLEAN, HATE, INSULTS, JAILBREAK, MISCONDUCT, PROMPT_INJECTION, PROMPT_LEAKAGE, VIOLENCE | `0e1ead16f3d24be7…` |
| `multilingual/zh-CN.jsonl` | 60 | CLEAN, HATE, INSULTS, JAILBREAK, MISCONDUCT, PROMPT_INJECTION, PROMPT_LEAKAGE, VIOLENCE | `e1165af1b39a0a29…` |
| `multilingual/zh-TW.jsonl` | 60 | CLEAN, HATE, INSULTS, JAILBREAK, MISCONDUCT, PROMPT_INJECTION, PROMPT_LEAKAGE, VIOLENCE | `3abe61d684cfc54a…` |
| `pii/negative/clean.jsonl` | 26 | CLEAN | `ce48f9f0b2116a9f…` |
| `pii/positive/address.jsonl` | 11 | ADDRESS | `756c2bfbdb64150d…` |
| `pii/positive/age.jsonl` | 11 | AGE | `d11f0954a8545dae…` |
| `pii/positive/aws_access_key.jsonl` | 11 | AWS_ACCESS_KEY | `8a5f9dbd314e05de…` |
| `pii/positive/aws_secret_key.jsonl` | 11 | AWS_SECRET_KEY | `c70bd5c2090842d4…` |
| `pii/positive/ca_health_number.jsonl` | 11 | CA_HEALTH_NUMBER | `785e32c5d7b865e5…` |
| `pii/positive/ca_social_insurance_number.jsonl` | 11 | CA_SOCIAL_INSURANCE_NUMBER | `f0fa0bfb063e5f4e…` |
| `pii/positive/credit_debit_card_cvv.jsonl` | 11 | CREDIT_DEBIT_CARD_CVV | `06f94a08c87b0a7d…` |
| `pii/positive/credit_debit_card_expiry.jsonl` | 11 | CREDIT_DEBIT_CARD_EXPIRY | `f209d295ebe9b841…` |
| `pii/positive/credit_debit_card_number.jsonl` | 11 | CREDIT_DEBIT_CARD_NUMBER | `363160151bb570b1…` |
| `pii/positive/driver_id.jsonl` | 11 | DRIVER_ID | `96c54b12d60b8a14…` |
| `pii/positive/email.jsonl` | 11 | EMAIL | `28855de6c3b6b686…` |
| `pii/positive/international_bank_account_number.jsonl` | 11 | INTERNATIONAL_BANK_ACCOUNT_NUMBER | `bc48e28d67b0afe6…` |
| `pii/positive/ip_address.jsonl` | 11 | IP_ADDRESS | `636fcb62ee789526…` |
| `pii/positive/license_plate.jsonl` | 11 | LICENSE_PLATE | `eb09dcd22a1b8e53…` |
| `pii/positive/mac_address.jsonl` | 11 | MAC_ADDRESS | `64672b4f4e6a5c7c…` |
| `pii/positive/name.jsonl` | 11 | NAME | `3717e1fa9641f339…` |
| `pii/positive/password.jsonl` | 11 | PASSWORD | `a7a7359621871730…` |
| `pii/positive/phone.jsonl` | 11 | PHONE | `f2e285f00af3e5b7…` |
| `pii/positive/pin.jsonl` | 11 | PIN | `19ae2017bb9ffd23…` |
| `pii/positive/swift_code.jsonl` | 11 | SWIFT_CODE | `5293d316b6f50f95…` |
| `pii/positive/uk_national_health_service_number.jsonl` | 11 | UK_NATIONAL_HEALTH_SERVICE_NUMBER | `954caff2c93a94d1…` |
| `pii/positive/uk_national_insurance_number.jsonl` | 11 | UK_NATIONAL_INSURANCE_NUMBER | `01897c12ef349859…` |
| `pii/positive/uk_unique_taxpayer_reference_number.jsonl` | 11 | UK_UNIQUE_TAXPAYER_REFERENCE_NUMBER | `338e5f2b9e6ea35a…` |
| `pii/positive/url.jsonl` | 11 | URL | `778a6312368339fe…` |
| `pii/positive/us_bank_account_number.jsonl` | 11 | US_BANK_ACCOUNT_NUMBER | `ac5c5ecc6e2dfb22…` |
| `pii/positive/us_bank_routing_number.jsonl` | 11 | US_BANK_ROUTING_NUMBER | `fe9e73136e35bdf1…` |
| `pii/positive/us_individual_tax_identification_number.jsonl` | 11 | US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER | `eb36b9cf64c745c0…` |
| `pii/positive/us_passport_number.jsonl` | 11 | US_PASSPORT_NUMBER | `c989ef6ada357a6d…` |
| `pii/positive/us_social_security_number.jsonl` | 11 | US_SOCIAL_SECURITY_NUMBER | `ed0027a848bd9f9a…` |
| `pii/positive/username.jsonl` | 11 | USERNAME | `76287c231217455a…` |
| `pii/positive/vehicle_identification_number.jsonl` | 11 | VEHICLE_IDENTIFICATION_NUMBER | `895810fcaedb422b…` |
| `prompt_attack/jailbreak.jsonl` | 120 | JAILBREAK | `4f4653b555237215…` |
| `prompt_attack/prompt_injection.jsonl` | 120 | PROMPT_INJECTION | `a1621858a959f435…` |
| `prompt_attack/prompt_leakage.jsonl` | 120 | PROMPT_LEAKAGE | `dd00508780e0ca13…` |

**Authored vs reused.** All 1917 items are authored except: 26 PII
negatives and 33 hard negatives reused verbatim from
`claude-code-enterprise-bedrock/tests/pii-corpus/` (59 items, 3.1%). **Zero PII
positives are reused verbatim** — see `DEV-P0-7`: every one of the 31 entity types
is embedded in the *same* 11 carrier sentences, which is the control that makes a
per-entity detection difference attributable to the entity rather than to its
sentence, and a reused item brings its own sentence. Reuse survives at the *value*
level only (4 published test constants).

---

## 3. Audit result by rating class

Sampling is stratified by **rating class**, not by corpus cell, because the class is
the unit κ is computed over. `hard_negatives` is sampled entirely: it is the one
judgement-labeled class, so it is the only one where disagreement is possible for a
reason other than a defective template.

| class | n | agreed | agreement | Wilson 95% | rated instead |
|:---|---:|---:|---:|:---|:---|
| CLEAN | 24 | 24 | 1.0000 | [0.862, 1.000] | — |
| HARD_NEGATIVE | 60 | 49 | 0.8167 | [0.701, 0.894] | CLEAN, PII |
| HATE | 24 | 24 | 1.0000 | [0.862, 1.000] | — |
| INSULTS | 24 | 24 | 1.0000 | [0.862, 1.000] | — |
| JAILBREAK | 24 | 24 | 1.0000 | [0.862, 1.000] | — |
| MISCONDUCT | 24 | 24 | 1.0000 | [0.862, 1.000] | — |
| PII | 24 | 24 | 1.0000 | [0.862, 1.000] | — |
| PROMPT_INJECTION | 24 | 24 | 1.0000 | [0.862, 1.000] | — |
| PROMPT_LEAKAGE | 24 | 24 | 1.0000 | [0.862, 1.000] | — |
| SEXUAL | 24 | 24 | 1.0000 | [0.862, 1.000] | — |
| VIOLENCE | 24 | 24 | 1.0000 | [0.862, 1.000] | — |

---

## 4. The residual, read item by item

The disagreements were read individually after scoring, and this is recorded because it is where DEV-P0-8 came from: the pre-fix run passed at kappa 0.9530 and its residual contained an item rated PII against a label asserting no documented entity type was present, which was a real corpus defect (9 hard negatives and 1 PII negative carried documented entity types). A gate answers the question it was built to ask; the items it disagreed with are where the unasked questions are. The remaining PII-for-HARD_NEGATIVE disagreements are Singapore NRIC/FIN items, checked against the live SDK enumeration: no Singapore national ID is among the 31 GuardrailPiiEntityType values, so the label is correct and the rating reflected real-world PII rather than the SDK's documented vocabulary. That gap is the stimulus those items exist to provide.

The remaining `CLEAN`-for-`HARD_NEGATIVE` disagreements are the structural overlap
described in §1: the rater and the label differ over *resemblance*, not over the
text. No disagreement in this run indicates a defective template.

---

## 5. Limitations

1. Template-generated text is formulaic; a filter could respond to structure rather than content. F3 reports recall ON THIS CORPUS and claims no generalisation to natural attack text.
2. One rater (see what_this_kappa_is).
3. The rater wrote the template bank, so blinding removes recall of which item is which but not knowledge of the generator. This bounds the audit to template-level defects and leaves definition-level bias undetectable.
4. Multilingual items are translated by the same author, so a language-specific translation artefact is indistinguishable from a language-specific filter weakness.
5. Ratings for the 289 items that survived the DEV-P0-8 corpus change are carried over VERBATIM from the pre-fix rating pass; only the 11 items new to the sample were rated after the change. Re-rating the 289 would have meant revising ratings while knowing which items the previous run had disagreed with, which is the one thing the three-step design exists to prevent.

---

## 6. Reproducing this

```
python3 verify_prereg.py          # 156 assertions; the seal must match
python3 corpora/build.py          # rebuild; MANIFEST.json sha256s must be unchanged
python3 corpora/audit.py sample   # id + text only, ordered by content hash
python3 corpora/audit.py score    # -> corpora/irr_report.json
```

`sample` and `score` are separate invocations on purpose: there is no step in which
a rating can be revised in the light of the label it is being compared to.
