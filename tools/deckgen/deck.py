"""The deck itself: one slide plan, two languages.

Every string is authored as a bilingual pair through ``t(en, zh)``, so the English and
Chinese decks are the same deck — same slide count, same order, same figures — and a
sentence cannot be updated in one language and forgotten in the other. Tables are not
retyped at all: they are pulled from the two Markdown files by index (see
:mod:`deckgen.mdsource`), which is also where the verdict citations get stripped and
over-long cells get abridged at a sentence boundary.

The plan continues in :mod:`deckgen.deck_after` — split only so each file stays
readable; the phase boundary (BEFORE/DURING here, AFTER onwards) is the document's own.
"""

from __future__ import annotations

from deckgen import diagrams
from deckgen.deck_after import after_phase, appendices, best_practices, checklist, latency
from deckgen.render import AMBER, BLUE, GREEN, GREEN_L, MUTED, RED, Deck

DOC_EN = "agentcore_guardrails_best_practices_v1.4.md"
DOC_ZH = "agentcore_guardrails_best_practices_v1.4.zh-TW.md"
REPO = "github.com/timwukp/agentcore-guardrails-design-validation"


def build(lang, src, out_path):
    t = (lambda en, zh: zh if lang == "zh" else en)
    d = Deck(lang, t("AgentCore Guardrails — Closed-Loop Design v1.4",
                     "AgentCore Guardrails —— 閉環設計 v1.4"))

    front_matter(d, t, src)
    executive(d, t, src)
    architecture(d, t, src)
    before_phase(d, t, src)
    during_phase(d, t, src)
    after_phase(d, t, src)
    latency(d, t, src)
    best_practices(d, t, src)
    checklist(d, t, src)
    appendices(d, t, src)
    closing(d, t, src)

    return d.save(out_path), d.warnings


# --------------------------------------------------------------------------- #
# front matter
# --------------------------------------------------------------------------- #


def front_matter(d, t, src):
    d.title_slide(
        t("Guardrails Closed-Loop Design on Amazon Bedrock AgentCore",
          "Amazon Bedrock AgentCore 的 Guardrails 閉環設計"),
        t("BEFORE → DURING → AFTER: six checkpoint hops, what each one costs, and which of "
          "the document's claims survived being measured.",
          "BEFORE → DURING → AFTER:六個檢查點 hop、每一個的成本,以及文件中的哪些主張在實測後仍然站得住。"),
        [
            (t("Version", "版本"), t("v1.4 — empirically amended from v1.2", "v1.4 —— 依實測結果自 v1.2 修訂")),
            (t("Evidence", "證據"), t("93 pre-registered cases · 90 published verdicts · us-east-1",
                                      "93 個預先登記的案例 · 90 個已發佈判定 · us-east-1")),
            (t("Method", "方法"), t("every decision rule sealed before any data arrived",
                                    "每一條判定規則都在資料抵達之前封存")),
            (t("Repository", "程式庫"), REPO),
        ],
        badge=t("VALIDATED DESIGN DOCUMENT", "已驗證的設計文件"),
    )

    d.kpi(
        t("Validation status", "驗證狀態"),
        [
            {"value": "93", "label": t("registered cases", "登記案例"),
             "sub": t("sealed before measurement", "在量測之前封存"), "color": MUTED},
            {"value": "90", "label": t("published verdicts", "已發佈判定"),
             "sub": t("one per case, on disk", "每案一份,存於磁碟"), "color": BLUE},
            {"value": "45", "label": t("TRUE — confirmed", "TRUE —— 已確認"),
             "sub": t("annotated in place", "就地標註"), "color": GREEN},
            {"value": "23", "label": t("FALSE — refuted", "FALSE —— 已駁回"),
             "sub": t("corrected in place", "就地修正"), "color": RED},
            {"value": "20", "label": t("INCONCLUSIVE", "INCONCLUSIVE"),
             "sub": t("claim left unchanged", "主張保持不變"), "color": AMBER},
        ],
        items=[
            (0, t("**92 verdict-eligible**, not 93: F9-1 is untestable by its own sealed oracle — AgentCore exposes "
                  "no fault-injection surface for policy evaluation, so the case can never run.",
                  "**可判定的是 92 個**,不是 93:F9-1 依它自己封存的 oracle 就是不可測的 —— AgentCore 沒有"
                  "任何針對政策評估的故障注入介面,所以這個案例永遠跑不了。")),
            (0, t("**2 RECORDED** verdicts (F5-4a, F5-4b) — a verdict value, not an exemption: each has a result "
                  "file like every other case.",
                  "**2 個 RECORDED** 判定(F5-4a、F5-4b)—— 這是一種判定值,不是豁免:它們和其他案例一樣有結果檔。")),
            (0, t("**1 outstanding: F10-1** (§3.2 billing asymmetry). Not a missing run — Cost Explorer's finest "
                  "granularity is daily and the oracle needs a per-request delta. Recorded as unmeasured rather "
                  "than left open.",
                  "**1 個未結案:F10-1**(§3.2 計費不對稱)。這不是漏跑 —— Cost Explorer 最細只到「日」,"
                  "而 oracle 需要逐請求的差值。它被記錄為「未量測」,而不是懸而未決。")),
            (0, t("**1 case with no publishable standing: F5-3b.** It returned TRUE, but its "
                  "`every_boundary_transition_was_observed_to_settle` guard failed, so it is not counted and is "
                  "not cited as confirming anything.",
                  "**1 個沒有可發佈地位的案例:F5-3b。** 它回傳 TRUE,但 "
                  "`every_boundary_transition_was_observed_to_settle` 這道守衛失敗,因此不計入,也不被引用為任何確認。")),
        ],
        lead=t("Counts are re-derived by `census.py` from the verdict files on disk, not maintained by hand.",
               "數字由 `census.py` 從磁碟上的判定檔重新推導,不是人工維護的。"),
    )

    d.bullets(
        t("How to read a verdict in this deck", "如何讀本簡報中的判定"),
        [
            (0, t("**Every case had its decision rule sealed before any data arrived.**", "**每個案例的判定規則都在任何資料抵達前就封存了。**"), "head"),
            (1, t("The rule — the *oracle* — is pinned by sha256 in `lib/oracle.py` together with the sample size, "
                  "the thresholds and the guards. A result cannot be re-argued after the fact, because the argument "
                  "was fixed first.",
                  "這條規則 —— 也就是 *oracle* —— 連同樣本數、門檻值與守衛條件,一起以 sha256 釘在 `lib/oracle.py`。"
                  "結果無法事後重新詮釋,因為詮釋方式在事前就已固定。")),
            (0, t("**TRUE** — the document's claim was confirmed. The prose stays; a dated citation is appended.",
                  "**TRUE** —— 文件的主張獲得確認。文字保留,附上一段有日期的引用。"), "good"),
            (0, t("**FALSE** — the claim was refuted. The prose is corrected in place, and the correction states "
                  "its own scope.",
                  "**FALSE** —— 主張被駁回。文字就地修正,而修正本身會說明它的適用範圍。"), "warn"),
            (0, t("**INCONCLUSIVE is not FALSE, and it licenses no amendment.** The instrument failed to put the "
                  "question, so the claim is left exactly as v1.2 wrote it. Twenty claims are in this state and "
                  "none of them was quietly softened.",
                  "**INCONCLUSIVE 不是 FALSE,而且它不授權任何修訂。** 是儀器沒能把問題問出來,"
                  "所以主張完全照 v1.2 原文保留。有二十項主張處於這個狀態,沒有一項被暗中軟化。"), "warn"),
            (0, t("**No claim is amended on a single calendar day's data.** `reproduction_before_amendment` requires "
                  "a second UTC day. This is why one confirmed finding (F5-8, route #3 credentials) is annotated but "
                  "does not yet replace its NDA citation.",
                  "**沒有任何主張是用單一日曆日的資料修訂的。** `reproduction_before_amendment` 要求第二個 UTC 日。"
                  "這就是為什麼一項已確認的發現(F5-8,路徑 #3 的憑證)只被標註,還沒取代它的 NDA 引用。"), "head"),
            (0, t("Numbers on these slides are measurements with their sample size, Region and date attached. Where "
                  "a number is absent, the measurement is absent — not rounded off.",
                  "本簡報上的數字都是實測值,並附上樣本數、Region 與日期。凡是沒有數字的地方,就是沒有量測 —— "
                  "而不是被省略。"), "muted"),
        ],
        kicker=t("Method", "方法"),
        note=t("Verdict files: `results/phase1/`. Pre-registration: `PREREGISTRATION.yaml`. Both are in the "
               "repository named on the title slide.",
               "判定檔:`results/phase1/`。預先登記:`PREREGISTRATION.yaml`。兩者都在標題頁所列的程式庫中。"),
    )


# --------------------------------------------------------------------------- #
# §1 executive summary
# --------------------------------------------------------------------------- #


def executive(d, t, src):
    d.divider("01", t("Executive Summary", "執行摘要"),
              t("Why a guardrails design needs a latency budget, and what two constraints decide the deployment "
                "before any tuning starts.",
                "為什麼 guardrails 設計需要一份延遲預算,以及在任何調校開始之前,哪兩個限制就決定了部署方式。"))

    d.bullets(
        t("The problem this design solves", "本設計要解決的問題"),
        [
            (0, t("Guardrails on AgentCore are not one check — they are **multiple checkpoint hops** in the "
                  "request/response lifecycle. Each hop is essential for safety and each adds measurable latency.",
                  "AgentCore 上的 guardrails 不是一道檢查 —— 而是請求/回應生命週期中的**多個檢查點 hop**。"
                  "每一個 hop 對安全都是必要的,而每一個都會增加可量測的延遲。"), "head"),
            (0, t("This document defines the complete **BEFORE → DURING → AFTER** closed loop and makes the cost of "
                  "each hop explicit, so the safety/latency trade-off is a decision rather than a surprise.",
                  "本文件定義完整的 **BEFORE → DURING → AFTER** 閉環,並把每個 hop 的成本寫明,"
                  "讓安全與延遲之間的取捨成為一項決策,而不是一個意外。")),
            (0, t("**Measured, not estimated.** Total end-to-end guardrail overhead and per-hop p50/p90/p99 come "
                  "from n = 1000 per hop in us-east-1. Five of six measured hops fell outside the illustrative "
                  "bands v1.2 published.",
                  "**是實測,不是估算。** 端到端的 guardrail 總開銷與每個 hop 的 p50/p90/p99 來自 us-east-1、"
                  "每 hop n = 1000。六個實測 hop 中有五個落在 v1.2 所發佈的示意區間之外。")),
            (0, t("**Two constraints decide your deployment before you tune anything:**", "**在你調校任何東西之前,有兩個限制就決定了你的部署:**"), "head"),
            (1, t("**Regional availability** — v1.2's five-Region list for Guardrails-in-policy is refuted. "
                  "`CreatePolicyEngine` also succeeded in us-west-2, eu-central-1, sa-east-1 and ap-south-1. But a "
                  "create acceptance is the control plane accepting a mutation, *not* the feature evaluating a "
                  "request — verify your own Region.",
                  "**Region 可用性** —— v1.2 為 Guardrails-in-policy 所列的五個 Region 已被駁回。"
                  "`CreatePolicyEngine` 在 us-west-2、eu-central-1、sa-east-1、ap-south-1 也成功。"
                  "但建立被接受只代表控制平面接受了一次變更,*不代表*該功能會評估請求 —— 請自行驗證你的 Region。")),
            (1, t("**Language support** — Classic-tier content filters cover English, French and Spanish only. On "
                  "zh-TW / zh-CN / ja / ko, Classic detection measured **0** at n = 240. Standard tier fixes it but "
                  "**requires cross-Region inference**, so it is a data-residency decision too.",
                  "**語言支援** —— Classic tier 的內容過濾只涵蓋英文、法文、西班牙文。在 zh-TW / zh-CN / ja / ko 上,"
                  "Classic 的偵測率實測為 **0**(n = 240)。Standard tier 能解決,但**強制要求跨 Region 推論**,"
                  "所以它同時是一個資料落地的決策。")),
            (0, t("Everything downstream — thresholds, alarms, tiers, network containment — assumes those two "
                  "questions are answered first.",
                  "後面所有的東西 —— 門檻值、告警、tier、網路圍堵 —— 都假設這兩個問題已經先有答案。"), "muted"),
        ],
        kicker=t("§1 Executive Summary", "§1 執行摘要"),
        note=t("\"Guardrails are ineffective with languages that aren't supported\" is AWS's own wording, and the "
               "measurement is literal agreement with it, not a cautious reading.",
               "「Guardrails are ineffective with languages that aren't supported」是 AWS 自己的用語,"
               "而實測結果與它字面一致,不是保守解讀。"),
    )


# --------------------------------------------------------------------------- #
# §2 architecture
# --------------------------------------------------------------------------- #


def architecture(d, t, src):
    d.divider("02", t("Architecture Overview: The Closed Loop", "架構總覽:閉環"),
              t("Three phases, six checkpoint hops, one feedback path — and a hop numbering that the rest of the "
                "document is normative about.",
                "三個階段、六個檢查點 hop、一條反饋路徑 —— 以及一套本文件其餘部分都以之為規範的 hop 編號。"))

    diagrams.closed_loop(d, t)

    h, r = src.table(d.lang, 1)
    d.table(
        t("Hop numbering (normative for this document)", "Hop 編號(本文件的規範性定義)"),
        h, r, col_ratios=[1, 7, 2], align=["c", "l", "c"], emphasis_col=0,
        kicker=t("§2.1", "§2.1"),
        lead=t("Quoted from §2.1. Every later section, diagram and metric refers to hops by these numbers.",
               "引自 §2.1。後續每一節、每張圖、每個指標都以這些編號指稱 hop。"),
    )

    diagrams.hop_lifecycle(d, t)


# --------------------------------------------------------------------------- #
# §3 BEFORE
# --------------------------------------------------------------------------- #


def before_phase(d, t, src):
    d.divider("03", t("Phase 1: BEFORE — Input Safety Checkpoints", "階段 1:BEFORE —— 輸入安全檢查點"),
              t("Hop #1 at the Gateway, Hop #2 at the model boundary, and the tier decision that decides whether "
                "either of them does anything at all.",
                "Gateway 上的 Hop #1、模型邊界上的 Hop #2,以及決定這兩者到底有沒有作用的 tier 選擇。"),
              items=[t("§3.1 Gateway policy guardrails", "§3.1 Gateway 政策 guardrails"),
                     t("§3.2 Bedrock Guardrails — input", "§3.2 Bedrock Guardrails —— 輸入"),
                     t("§3.3 ApplyGuardrail for non-Bedrock models", "§3.3 非 Bedrock 模型的 ApplyGuardrail"),
                     t("§3.4 Tiers and language support", "§3.4 Tier 與語言支援")])

    d.bullets(
        t("Hop #1 — AgentCore Gateway policy guardrails", "Hop #1 —— AgentCore Gateway 政策 guardrails"),
        [
            (0, t("Intercepts incoming requests **at the gateway, before the agent is invoked** — a blocked request "
                  "never reaches the model, so it costs no inference.",
                  "在 **gateway 上、agent 被呼叫之前**攔截進入的請求 —— 被阻擋的請求根本到不了模型,因此不花推論成本。"), "head"),
            (0, t("Content is evaluated against guardrail safeguards expressed as **Cedar policy conditions**: "
                  "content filters, denied topics, word filters, sensitive-information filters, and prompt-attack "
                  "detection (JAILBREAK, PROMPT_INJECTION, PROMPT_LEAKAGE).",
                  "內容會依表達為 **Cedar 政策條件**的 guardrail 防護進行評估:內容過濾、denied topic、字詞過濾、"
                  "敏感資訊過濾,以及 prompt 攻擊偵測(JAILBREAK、PROMPT_INJECTION、PROMPT_LEAKAGE)。")),
            (0, t("**Three traps that a reader following v1.2 verbatim would hit:**", "**照 v1.2 逐字照做會踩到的三個陷阱:**"), "head"),
            (1, t("**Pin `botocore`/`boto3` ≥ 1.43.32.** Versions 1.43.30–.31 expose `InvokeGuardrailChecks` "
                  "*without* `enforcementMode`, and the bundled AWS CLI v2 has no policy-engine subcommands at all.",
                  "**把 `botocore`/`boto3` 釘在 ≥ 1.43.32。** 1.43.30–.31 這兩版露出的 `InvokeGuardrailChecks` "
                  "*沒有* `enforcementMode`,而隨附的 AWS CLI v2 完全沒有 policy-engine 子命令。"), "warn"),
            (1, t("**Pass an explicit `validationMode`.** The baseline permit statement this document recommends is "
                  "rejected under the `FAIL_ON_ANY_FINDINGS` default — asynchronously, *after* a 202 response. Poll "
                  "the policy `status`; never treat the 202 as success.",
                  "**明確給定 `validationMode`。** 本文件建議的基線 permit 語句在預設的 `FAIL_ON_ANY_FINDINGS` 下"
                  "會被拒絕 —— 而且是在 202 回應*之後*非同步發生。請輪詢政策的 `status`;絕不要把 202 當成成功。"), "warn"),
            (1, t("**Write the baseline permit BEFORE enabling ENFORCE.** Cedar is default-deny, so an engine "
                  "switched to ENFORCE with no permit denies everything.",
                  "**在啟用 ENFORCE 之前先寫好基線 permit。** Cedar 是預設拒絕,所以沒有 permit 就切到 ENFORCE 的 "
                  "engine 會拒絕一切。"), "warn"),
            (0, t("A mode flip is fast and observable: an accepted `UpdateGateway` took 602.8 / 931.7 ms, and a "
                  "previously blocked request was served 13.2–14.2 s later. `iam:PassRole` is needed beside "
                  "`UpdateGateway`.",
                  "模式切換既快也可觀測:一次被接受的 `UpdateGateway` 花了 602.8 / 931.7 ms,而先前被阻擋的請求"
                  "在 13.2–14.2 秒後就被服務了。`UpdateGateway` 旁邊還需要 `iam:PassRole`。")),
        ],
        kicker=t("§3.1", "§3.1"),
        columns=1,
    )

    d.bullets(
        t("Hop #2 — Bedrock Guardrails on the input, and how well it actually detects",
          "Hop #2 —— Bedrock Guardrails 的輸入評估,以及它實際的偵測能力"),
        [
            (0, t("Evaluates the user prompt **before model inference** when `guardrailConfiguration` is attached to "
                  "the invocation. On a violation, inference is not executed and you pay only for the guardrail — "
                  "not for the model.",
                  "當 `guardrailConfiguration` 掛在呼叫上時,它會在**模型推論之前**評估使用者 prompt。"
                  "違規時推論不會執行,你只付 guardrail 的費用 —— 不付模型的。"), "head"),
            (0, t("Supports the full range of guardrail policies — more comprehensive than the Gateway level.",
                  "支援完整的 guardrail 政策範圍 —— 比 Gateway 層更全面。")),
            (0, t("**Measured detection efficacy** (us-east-1, 2026-08-10):", "**實測偵測效能**(us-east-1,2026-08-10):"), "head"),
            (1, t("Benign false-positive rate **0.9%** [0.16%, 5.0%] at n = 110 — the filters are not trigger-happy "
                  "on ordinary traffic.",
                  "良性內容誤報率 **0.9%** [0.16%, 5.0%](n = 110)—— 過濾器對一般流量不會亂擋。"), "good"),
            (1, t("**Sensitive-information filters: 9 of 31 documented PII entity types measured undetected** "
                  "(recall CI upper bound below 0.5, n = 341). Do not assume the published entity list is the "
                  "detected entity list — test the types you actually carry.",
                  "**敏感資訊過濾:31 種文件所列的 PII 實體類型中,有 9 種實測未被偵測**"
                  "(recall 信賴區間上界低於 0.5,n = 341)。不要假設文件列出的清單就是實際偵測到的清單 —— "
                  "請測試你真正會處理的類型。"), "warn"),
            (0, t("**Configure input tagging wherever prompt-attack filtering is expected at the model layer.** "
                  "Untagged `InvokeModel` prompt-attack recall measured **0** [0, 0.031] across 4 arms × 120. "
                  "Tagging is required, not optional — use a random `tagSuffix`.",
                  "**凡是預期在模型層做 prompt 攻擊過濾的地方,都要設定 input tagging。** 未加標記的 "
                  "`InvokeModel` prompt 攻擊 recall 實測為 **0** [0, 0.031](4 個 arm × 120)。"
                  "加標記是必要的,不是選項 —— 並使用隨機的 `tagSuffix`。"), "warn"),
            (0, t("Per-direction independence (BP#1) is **left as v1.2 wrote it** — F1-11 returned INCONCLUSIVE.",
                  "各方向獨立設定(BP#1)**照 v1.2 原文保留** —— F1-11 是 INCONCLUSIVE。"), "muted"),
        ],
        kicker=t("§3.2", "§3.2"),
    )

    diagrams.billing_asymmetry(d, t)

    d.bullets(
        t("Hop #2-ALT — ApplyGuardrail, for models that are not on Bedrock",
          "Hop #2-ALT —— ApplyGuardrail,給不在 Bedrock 上的模型"),
        [
            (0, t("The same guardrail evaluation as Hop #2, but as a **standalone API call** decoupled from any "
                  "foundation model.",
                  "與 Hop #2 相同的 guardrail 評估,但是一個**獨立的 API 呼叫**,與任何基礎模型解耦。"), "head"),
            (0, t("Use it for third-party models, self-hosted models, or a LiteLLM-style gateway. You control when "
                  "and how it is called — which also means nothing calls it for you.",
                  "用於第三方模型、自架模型,或 LiteLLM 這類 gateway。你控制何時、如何呼叫它 —— "
                  "這也意味著沒有人會替你呼叫。")),
            (0, t("**Cost: it adds a full round-trip API call to Bedrock Runtime.** In the latency budget it is a "
                  "hop like any other, and it is on the critical path of every request you choose to check.",
                  "**代價:它多一次到 Bedrock Runtime 的完整往返 API 呼叫。** 在延遲預算裡它和其他 hop 一樣,"
                  "而且它在你選擇檢查的每一個請求的關鍵路徑上。"), "warn"),
            (0, t("Batch content blocks where you can — but the documented 10-content-block cap is **left "
                  "unchanged**: F1-20 returned INCONCLUSIVE.",
                  "能批次處理內容區塊就批次處理 —— 但文件所寫的 10 個內容區塊上限**保持不變**:"
                  "F1-20 是 INCONCLUSIVE。"), "muted"),
        ],
        kicker=t("§3.3", "§3.3"),
    )

    h, r = src.table(d.lang, 2, budget=190)
    d.table(
        t("Guardrail tiers: what changed after measurement", "Guardrail tier:實測之後改了什麼"),
        h, r, col_ratios=[3, 4, 4], kicker=t("§3.4", "§3.4"),
        lead=t("Quoted from §3.4, cells abridged at sentence boundaries. Two of v1.2's tier claims did not survive.",
               "引自 §3.4,單元格在句子邊界處節錄。v1.2 的 tier 主張有兩項未能存活。"),
        note=t("Prompt-leakage detection is **not** Standard-exclusive: Classic measured recall 0.41 [0.32, 0.50] "
               "against FPR 0.036 at n = 460 — weak, but not the documented \"No\". And the Standard-tier "
               "1,000-char denied-topic limit was rejected with `ValidationException`, while Classic's 200-char "
               "boundary held exactly.",
               "Prompt leakage 偵測**並非** Standard 專屬:Classic 實測 recall 0.41 [0.32, 0.50],FPR 0.036"
               "(n = 460)—— 弱,但不是文件寫的「No」。而 Standard tier 的 1,000 字 denied-topic 上限被 "
               "`ValidationException` 拒絕,Classic 的 200 字邊界則完全成立。"),
    )

    diagrams.tier_decision(d, t)

    h, r = src.table(d.lang, 3, budget=150)
    d.table(
        t("If you come from a framework: where the hook you know lives here",
          "如果你來自某個框架:你熟悉的 hook 在這裡的位置"),
        h, r, col_ratios=[3, 4, 4], kicker=t("§3.1", "§3.1"),
        lead=t("Framework hook concepts mapped onto AgentCore primitives and the place enforcement actually happens.",
               "把框架的 hook 概念對應到 AgentCore 原生元件,以及強制執行真正發生的位置。"),
    )


# --------------------------------------------------------------------------- #
# §4 DURING
# --------------------------------------------------------------------------- #


def during_phase(d, t, src):
    d.divider("04", t("Phase 2: DURING — Execution Control and Observability",
                      "階段 2:DURING —— 執行控制與可觀測性"),
              t("The deterministic layer. Cedar decides tool access on every hop, and it is the only part of this "
                "design that is immune to prompt injection.",
                "確定性的那一層。Cedar 在每一個 hop 決定工具存取,而它是本設計中唯一對 prompt injection 免疫的部分。"),
              items=[t("§4.1 Cedar tool authorization (Hop #4)", "§4.1 Cedar 工具授權(Hop #4)"),
                     t("§4.2 Tool request/response guardrails (Hop #5)", "§4.2 工具請求/回應 guardrails(Hop #5)"),
                     t("§4.3 Real-time observability", "§4.3 即時可觀測性"),
                     t("§4.4 Non-bypassable hooks · §4.5 Network containment",
                       "§4.4 不可繞過的 hook · §4.5 網路圍堵")])

    d.bullets(
        t("Hop #4 — Cedar tool authorization is the deterministic checkpoint",
          "Hop #4 —— Cedar 工具授權是確定性的檢查點"),
        [
            (0, t("Intercepts **every** agent-to-tool request through the Gateway and makes an allow/deny decision "
                  "from policy logic — not from the model's reasoning.",
                  "攔截**每一個**經由 Gateway 的 agent 對工具請求,並依政策邏輯做出允許/拒絕的決定 —— "
                  "而不是依模型的推理。"), "head"),
            (0, t("**Immune to prompt injection**, because it operates outside the model. Put anything that must "
                  "not be talked around into `permit`/`forbid`, not into a guardrail.",
                  "**對 prompt injection 免疫**,因為它在模型之外運作。任何不能被話術繞過的規則,"
                  "都要放進 `permit`/`forbid`,而不是放進 guardrail。"), "good"),
            (0, t("**Deterministic — and measured to be so.** 630/630 trials under one configuration produced "
                  "**0 flips**: amount 499.9 allowed 300/300, amount 500.0 denied 300/300, one-sided flip-rate "
                  "ceiling 0.00474. The boundary is exact.",
                  "**確定性 —— 而且是實測出來的。** 在同一組設定下 630/630 次試驗產生 **0 次翻轉**:"
                  "amount 499.9 允許 300/300,amount 500.0 拒絕 300/300,單邊翻轉率上界 0.00474。邊界是精確的。"), "good"),
            (0, t("**Cedar authoring facts that cost real time to learn:**", "**花了真實時間才學到的 Cedar 撰寫事實:**"), "head"),
            (1, t("`amount` must be sent as `100.0`, not `100` — the engine refuses to bind an integral JSON "
                  "literal to a Cedar `decimal`. Four fractional digits do bind.",
                  "`amount` 必須送 `100.0`,不能送 `100` —— engine 不接受把整數 JSON 字面值繫結到 Cedar 的 "
                  "`decimal`。四位小數是可以繫結的。")),
            (1, t("A guardrail statement needs `action ==` scoping **at runtime**: unscoped, it denies everything "
                  "with \"guardrail policy could not be evaluated — missing an attribute\", even though it created "
                  "successfully.",
                  "guardrail 語句在**執行期**需要 `action ==` 限定範圍:沒有限定時它會以「guardrail policy could "
                  "not be evaluated — missing an attribute」拒絕一切,即使它建立時是成功的。")),
            (1, t("Thresholds are **mandatory** in hand-written policies: a no-threshold guardrails condition "
                  "settles `CREATE_FAILED` with a type error, while the same statement with an explicit "
                  "`.greaterThan(decimal(\"0.2\"))` reaches ACTIVE.",
                  "在手寫政策裡門檻值是**必填**的:沒有門檻的 guardrails 條件會以型別錯誤停在 `CREATE_FAILED`,"
                  "而同一語句加上明確的 `.greaterThan(decimal(\"0.2\"))` 就能到 ACTIVE。")),
            (0, t("Two documented limitations were **refuted**: the validator accepted Cedar's `like` inside a "
                  "`when guardrails {…}` block, and accepted a policy mixing `when {…}` with `when guardrails {…}` "
                  "— four terminal-ACTIVE acceptances per arm, replicated on a second UTC day. Evaluation-time "
                  "behaviour is still unmeasured, so the split-into-two-statements advice stands.",
                  "兩項文件所載的限制被**駁回**:驗證器接受了 `when guardrails {…}` 區塊裡的 Cedar `like`,"
                  "也接受了混用 `when {…}` 與 `when guardrails {…}` 的政策 —— 每個 arm 四次終態 ACTIVE 接受,"
                  "並在第二個 UTC 日重現。執行期行為仍未量測,所以「拆成兩條語句」的建議依然成立。")),
        ],
        kicker=t("§4.1", "§4.1"),
    )

    diagrams.log_only_precedence(d, t)

    h, r = src.table(d.lang, 14, budget=230)
    d.table(
        t("A denial does not look the same on every surface", "拒絕在每個介面上看起來都不一樣"),
        # This table lives in §6.4 of the document but belongs to the DURING story, so
        # the kicker has to say where it came from or the section numbers look shuffled.
        h, r, col_ratios=[3, 9], kicker=t("§4.1 · table from §6.4", "§4.1 · 表格出自 §6.4"),
        lead=t("Detection keyed only on JSON-RPC -32002 — which is all v1.3 described — misses two of these three "
               "channels.",
               "只以 JSON-RPC -32002 為判斷依據的偵測 —— 那是 v1.3 唯一描述的 —— 會漏掉這三個通道中的兩個。"),
        note=t("Observed on one calendar day on one gateway, from a run whose sealed verdict is INCONCLUSIVE. These "
               "are wire observations, not oracle outputs, and no positive claim rests on them — they close a "
               "coverage gap in the *detection guidance* rather than correcting anything v1.2 asserted.",
               "在一個 gateway 上、一個日曆日觀察到,來自一次封存判定為 INCONCLUSIVE 的執行。"
               "這些是線路上的觀察,不是 oracle 的輸出,也沒有任何正面主張建立在它們之上 —— "
               "它們補上的是*偵測指引*的覆蓋缺口,而不是修正 v1.2 的任何斷言。"),
    )

    d.bullets(
        t("Hop #5 — guardrails on tool requests and responses", "Hop #5 —— 工具請求與回應上的 guardrails"),
        [
            (0, t("Evaluates content in **both directions**: agent → tool and tool → agent. Request authorization "
                  "uses the `permit`/`forbid` effects; response content uses the guardrail safeguards.",
                  "**雙向**評估內容:agent → 工具,以及工具 → agent。請求授權用 `permit`/`forbid` 效果;"
                  "回應內容用 guardrail 防護。"), "head"),
            (0, t("Same safeguards as Hop #1, applied to tool communication — this is what stops sensitive data "
                  "leaving through a tool response.",
                  "與 Hop #1 相同的防護,套用在工具通訊上 —— 這正是阻止敏感資料經由工具回應外流的機制。")),
            (0, t("**It is added for EACH tool invocation in the agent's loop.** That is the cost driver: each "
                  "additional tool call costs **≈850 ms** (CI [838.7, 862.7], n = 600 usable) — not the 165–750 ms "
                  "v1.2 published.",
                  "**agent 迴圈中的每一次工具呼叫都會加上它。** 這就是成本來源:每一次額外的工具呼叫成本"
                  "**約 850 ms**(CI [838.7, 862.7],n = 600 可用)—— 不是 v1.2 寫的 165–750 ms。"), "warn"),
            (0, t("Indirect prompt injection through a tool response (BP#1) is **left as written**: F5-5's probe "
                  "policy never became ACTIVE and no echo round trip was observed, so the suppression question was "
                  "never put.",
                  "經由工具回應的間接 prompt injection(BP#1)**照原文保留**:F5-5 的探測政策從未變成 ACTIVE,"
                  "也沒有觀察到 echo 往返,所以那個抑制問題根本沒被問出來。"), "muted"),
        ],
        kicker=t("§4.2", "§4.2"),
    )

    d.bullets(
        t("Real-time observability during execution", "執行期的即時可觀測性"),
        [
            (0, t("OpenTelemetry-compatible distributed tracing across all agent components, publishing metrics, "
                  "spans and traces to CloudWatch. LLM inference calls, tool invocations and memory operations are "
                  "captured automatically.",
                  "跨所有 agent 元件的 OpenTelemetry 相容分散式追蹤,把指標、span 與 trace 發佈到 CloudWatch。"
                  "LLM 推論呼叫、工具呼叫與記憶體操作都會自動被擷取。"), "head"),
            (0, t("**Enable CloudWatch Transaction Search first.** With tracing disabled, the same traffic produced "
                  "**0 spans**; with it enabled, spans appeared. Tracing is a genuine prerequisite, not a "
                  "nice-to-have.",
                  "**先啟用 CloudWatch Transaction Search。** 追蹤關閉時,同樣的流量產生 **0 個 span**;"
                  "啟用後 span 就出現了。追蹤是真正的前置條件,不是加分項。"), "warn"),
            (0, t("**Spans lag the request by ≈50 s.** Anything that reads spans to make a decision — an alarm, a "
                  "gate, a test — has to tolerate that lag or it will read an empty result and call it a clean one.",
                  "**Span 比請求晚約 50 秒。** 任何要讀 span 來做決定的東西 —— 告警、閘門、測試 —— "
                  "都必須容忍這個延遲,否則它會讀到空結果,並把它當成乾淨的結果。"), "warn"),
            (0, t("Instrument your own code with the ADOT SDK for custom spans; the platform spans alone will not "
                  "explain your agent's own decisions.",
                  "用 ADOT SDK 為自己的程式碼加上自訂 span;僅靠平台的 span 無法解釋你 agent 自己的決策。")),
        ],
        kicker=t("§4.3", "§4.3"),
    )

    for lo, hi, label in ((0, 3, t("routes ① – ③", "路徑 ① – ③")), (3, 5, t("routes ④ – ⑤", "路徑 ④ – ⑤"))):
        h, r = src.table(d.lang, 4, budget=250, keep_rows=list(range(lo, hi)))
        d.table(
            t(f"The five bypass routes and how each is closed — {label}",
              f"五條繞過路徑與各自的封閉方式 —— {label}"),
            h, r, col_ratios=[1, 5, 9], align=["c", "l", "l"], kicker=t("§4.4", "§4.4"),
            lead=t("A hook is only non-bypassable if every route around it is closed. Quoted from §4.4, abridged at "
                   "sentence boundaries.",
                   "只有當繞過它的每一條路徑都被封閉,一個 hook 才算不可繞過。引自 §4.4,在句子邊界處節錄。")
            if lo == 0 else None,
            note=t("Route ③ is confirmed: 3 of 3 tool sessions read the execution role's credentials over the "
                   "microVM metadata service. Route ⑤'s second half is yours — never leave a production engine in "
                   "LOG_ONLY, and alarm on the CloudTrail `UpdateGateway` event rather than on a mode value.",
                   "路徑 ③ 已確認:3 個工具 session 全部經由 microVM metadata service 讀到 execution role 的憑證。"
                   "路徑 ⑤ 的後半是你的責任 —— 生產環境的 engine 永遠不要停在 LOG_ONLY,"
                   "並對 CloudTrail 的 `UpdateGateway` 事件告警,而不是對某個模式值告警。") if lo else None,
        )

    diagrams.containment_boundary(d, t)

    h, r = src.table(d.lang, 5, budget=210)
    d.table(
        t("Code Interpreter: three network modes, three containment verdicts",
          "Code Interpreter:三種網路模式,三種圍堵結論"),
        h, r, col_ratios=[2, 4, 6], kicker=t("§4.5.2", "§4.5.2"),
        lead=t("Sandbox mode is not isolation: it still allows DNS, which is a limited but real exfiltration channel.",
               "Sandbox 模式不是隔離:它仍允許 DNS,那是一個受限但真實存在的外洩通道。"),
    )

    h, r = src.table(d.lang, 6)
    d.table(
        t("PrivateLink coverage, dated", "PrivateLink 覆蓋範圍(附日期)"),
        h, r, col_ratios=[5, 3, 3], align=["l", "c", "c"], kicker=t("§4.5.3", "§4.5.3"),
        lead=t("Check this before designing a private-network deployment — and check it again yourself, because it "
               "moves.",
               "在設計私有網路部署之前先查這張表 —— 而且要自己再查一次,因為它會變。"),
        note=t("This matrix changed under measurement. Five dated archive snapshots (2026-04-12 → 2026-07-14) agree "
               "with v1.2 that Evaluations was \"not yet supported\", but the live page on 2026-08-09 **and** "
               "2026-08-10 marks Evaluations and Optimization as Supported on both planes. The header was also "
               "corrected from \"Service\" to \"Primitive\": the rows name AgentCore primitives, while PrivateLink "
               "attaches to endpoint services.",
               "這張矩陣在量測下改變了。五份有日期的存檔快照(2026-04-12 → 2026-07-14)與 v1.2 一致,"
               "都說 Evaluations「尚未支援」,但 2026-08-09 **與** 2026-08-10 的線上頁面都把 Evaluations 與 "
               "Optimization 標為兩個平面皆支援。表頭也從「Service」修正為「Primitive」:"
               "列名指的是 AgentCore 原生元件,而 PrivateLink 是掛在 endpoint service 上的。"),
    )

    diagrams.network_containment(d, t)


# --------------------------------------------------------------------------- #
# closing
# --------------------------------------------------------------------------- #


def closing(d, t, src):
    d.twocol(
        t("What to take away", "帶走什麼"),
        (t("Do this", "該做的"), GREEN, [
            (0, t("Pin `botocore` ≥ 1.43.32 and pass an explicit `validationMode` before writing any policy code.",
                  "在寫任何政策程式之前,把 `botocore` 釘在 ≥ 1.43.32,並明確給定 `validationMode`。")),
            (0, t("Write the baseline permit before enabling ENFORCE; Cedar is default-deny.",
                  "在啟用 ENFORCE 之前先寫基線 permit;Cedar 是預設拒絕。")),
            (0, t("Choose the tier from your traffic's language, then check data residency against Standard's "
                  "mandatory cross-Region inference.",
                  "依流量語言選 tier,再用 Standard 強制的跨 Region 推論去檢查資料落地要求。")),
            (0, t("Put anything that must not be talked around into Cedar `permit`/`forbid`, not into a guardrail.",
                  "任何不能被話術繞過的規則,放進 Cedar `permit`/`forbid`,不要放進 guardrail。")),
            (0, t("Budget ≈850 ms per additional tool call, and set alarm periods ≥ 60 s.",
                  "每一次額外工具呼叫預留約 850 ms,告警週期設 ≥ 60 秒。")),
            (0, t("Make denial detection surface-aware: -32002, HTTP 403, and an empty `tools/list`.",
                  "讓拒絕偵測具備介面意識:-32002、HTTP 403,以及空的 `tools/list`。")),
        ]),
        (t("Do not do this", "不該做的"), RED, [
            (0, t("Do not plan a Region from v1.2's five-Region list — it is refuted. Verify your own.",
                  "不要照 v1.2 的五 Region 清單規劃 —— 它已被駁回。請自行驗證。")),
            (0, t("Do not treat a 202 as success; the policy can settle `CREATE_FAILED` afterwards.",
                  "不要把 202 當成成功;政策事後可能停在 `CREATE_FAILED`。")),
            (0, t("Do not alarm on `ConfidenceScore`, `ConfidenceThreshold`, `TemporalLatency` or "
                  "`LogOnlyEvalIncomplete` — none published a datapoint here.",
                  "不要對 `ConfidenceScore`、`ConfidenceThreshold`、`TemporalLatency` 或 "
                  "`LogOnlyEvalIncomplete` 告警 —— 在這裡它們都沒有發佈任何資料點。")),
            (0, t("Do not read a mismatch metric with a cross-dimension `Sum`: it reads up to 6× the request count.",
                  "不要用跨維度的 `Sum` 讀 mismatch 指標:它會讀到請求數的 6 倍。")),
            (0, t("Do not calibrate thresholds from CloudWatch — the score is in the application logs, as a string.",
                  "不要用 CloudWatch 校準門檻值 —— 分數在應用程式 log 裡,而且是字串。")),
            (0, t("Do not write a runbook of the form \"revoke, confirm, proceed\": revocation is eventually "
                  "consistent in both directions.",
                  "不要寫「撤銷、確認、繼續」形式的 runbook:撤銷在兩個方向上都是最終一致的。")),
        ]),
        kicker=t("Summary", "總結"),
        note=t("Every claim on this slide is either a measured verdict or an explicit absence of one. The evidence "
               "is one file per case under `results/phase1/` in the repository on the title slide.",
               "本頁的每一項主張,要嘛是實測判定,要嘛是明確標示沒有判定。證據是標題頁所列程式庫中 "
               "`results/phase1/` 下每案一份的檔案。"),
    )

    d.divider(
        t("End", "結束"),
        t("The document is the deliverable; this deck is a reading of it.",
          "文件才是交付物,本簡報是它的一種讀法。"),
        t("v1.4, both languages, with every amendment traceable to a verdict file. Claims whose cases are "
          "outstanding, INCONCLUSIVE or untestable are unchanged — only markers were added.",
          "v1.4,兩種語言,每一項修訂都可追溯到一份判定檔。未結案、INCONCLUSIVE 或不可測的案例所對應的主張"
          "都未改動 —— 只增加了標記。"),
        items=[DOC_EN, DOC_ZH, REPO],
    )
