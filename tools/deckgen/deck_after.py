"""The second half of the slide plan: §5 AFTER through the appendices.

Split out of :mod:`deckgen.deck` only to keep each file readable — the split follows
the document's own phase boundary. Same convention: every string is a ``t(en, zh)``
pair, every table is quoted from the source Markdown by index.
"""

from __future__ import annotations

from deckgen import diagrams
from deckgen.render import BLUE, GREEN


# --------------------------------------------------------------------------- #
# §5 AFTER
# --------------------------------------------------------------------------- #


def after_phase(d, t, src):
    d.divider("05", t("Phase 3: AFTER — Output Safety and Continuous Improvement",
                      "階段 3:AFTER —— 輸出安全與持續改善"),
              t("The output checkpoint, then the part most designs never build: the loop that feeds production "
                "behaviour back into the policy.",
                "輸出檢查點,接著是大多數設計從未建造的那一段:把生產環境的行為回饋到政策裡的閉環。"),
              items=[t("§5.1 Output evaluation (Hop #6)", "§5.1 輸出評估(Hop #6)"),
                     t("§5.2 Continuous evaluation", "§5.2 持續評估"),
                     t("§5.3 Optimization feedback loop", "§5.3 最佳化反饋閉環")])

    diagrams.streaming(d, t)

    d.bullets(
        t("Continuous evaluation: three modes, and which one is for production",
          "持續評估:三種模式,以及哪一種是給生產環境用的"),
        [
            (0, t("**On-demand** — analyses a chosen set of spans directly. This is the development and spot-check "
                  "mode; it answers \"what happened in this session?\"",
                  "**即時(on-demand)** —— 直接分析你挑選的一組 span。這是開發與抽查用的模式,"
                  "回答的是「這個 session 發生了什麼?」"), "head"),
            (0, t("**Batch** — runs evaluators against many agent sessions in one asynchronous job. This is the "
                  "regression mode: run it before a policy or prompt change ships.",
                  "**批次(batch)** —— 在一個非同步作業中對大量 agent session 執行評估器。"
                  "這是回歸測試模式:在政策或 prompt 變更上線前執行它。"), "head"),
            (0, t("**Online** — continuously samples LIVE production interactions (percentage-based, e.g. 10%) with "
                  "no manual trigger. This is the one that catches drift you did not predict.",
                  "**線上(online)** —— 持續對「線上生產」互動取樣(依比例,例如 10%),不需要手動觸發。"
                  "這一種才能抓到你沒預測到的漂移。"), "head"),
            (0, t("**Verify PrivateLink posture before you enable Evaluations in a private network.** AWS's live "
                  "page now documents Evaluations and Optimization as PrivateLink-Supported on both planes — a "
                  "change from v1.2, dated 2026-08-09/10 and replicated.",
                  "**在私有網路啟用 Evaluations 之前,先確認 PrivateLink 狀態。** AWS 目前的線上頁面把 "
                  "Evaluations 與 Optimization 記為兩個平面皆支援 PrivateLink —— 這是相對於 v1.2 的變更,"
                  "日期為 2026-08-09/10,並已重現。"), "warn"),
            (0, t("The capability inventory here — which modes exist and what each does — was confirmed as written.",
                  "這裡的能力清單 —— 有哪些模式、各自做什麼 —— 已確認與原文一致。"), "good"),
        ],
        kicker=t("§5.2", "§5.2"),
    )

    d.bullets(
        t("The optimization feedback loop — what closes the loop", "最佳化反饋閉環 —— 是什麼讓閉環閉合"),
        [
            (0, t("**Analyse** production traces and evaluation outputs.", "**分析**生產環境的 trace 與評估輸出。"), "head"),
            (0, t("**Generate** optimized system prompts or tool descriptions (Recommendations).",
                  "**產生**最佳化後的系統 prompt 或工具描述(Recommendations)。"), "head"),
            (0, t("**Validate** offline with batch evaluations before anything reaches traffic.",
                  "在任何東西碰到流量之前,先用批次評估**離線驗證**。"), "head"),
            (0, t("**Confirm** with A/B testing on live traffic, via Gateway traffic splitting.",
                  "以線上流量做 A/B 測試**確認**,透過 Gateway 的流量分流。"), "head"),
            (0, t("Then feed the result back into the thresholds, the Cedar policies and the prompts — which is the "
                  "dashed arrow on the architecture diagram, and the only reason this design is called a closed loop.",
                  "然後把結果回饋到門檻值、Cedar 政策與 prompt —— 這就是架構圖上那條虛線箭頭,"
                  "也是這個設計之所以被稱為閉環的唯一理由。")),
            (0, t("**Re-run your guardrail regression set periodically even if you change nothing.** AWS "
                  "auto-updates the underlying guardrail models with no action on your part, so \"we did not touch "
                  "it\" is not a reason to expect the same behaviour.",
                  "**即使你什麼都沒改,也要定期重跑 guardrail 回歸測試集。** AWS 會自行更新底層的 guardrail 模型,"
                  "不需要你做任何事,所以「我們沒動過它」不是可以預期行為不變的理由。"), "warn"),
            (0, t("Auto-update drift guidance itself is **left as v1.2 wrote it** — F3-11 is INCONCLUSIVE, with "
                  "dated re-comparisons still owed at +7 and +30 days.",
                  "自動更新造成漂移的指引本身**照 v1.2 原文保留** —— F3-11 是 INCONCLUSIVE,"
                  "+7 天與 +30 天的日期比對仍待補。"), "muted"),
        ],
        kicker=t("§5.3", "§5.3"),
    )


# --------------------------------------------------------------------------- #
# §6 latency
# --------------------------------------------------------------------------- #


def latency(d, t, src):
    d.divider("06", t("Hop-by-Hop Latency Monitoring", "逐 Hop 的延遲監控"),
              t("The measured budget, the metrics that actually publish datapoints, the trace shape, and the alarms "
                "that can really fire.",
                "實測的預算、真正會發佈資料點的指標、trace 的形狀,以及真的能觸發的告警。"),
              items=[t("§6.1 Latency budget (measured)", "§6.1 延遲預算(實測)"),
                     t("§6.2 CloudWatch metrics per hop", "§6.2 每個 hop 的 CloudWatch 指標"),
                     t("§6.3 Distributed tracing", "§6.3 分散式追蹤"),
                     t("§6.4 Alerting strategy", "§6.4 告警策略")])

    h, r = src.table(d.lang, 7)
    d.table(
        t("The latency budget, measured — n = 1000 per hop, us-east-1",
          "延遲預算(實測)—— 每 hop n = 1000,us-east-1"),
        h, r, col_ratios=[1, 4, 3, 5, 4, 5], align=["c", "l", "l", "l", "l", "l"],
        kicker=t("§6.1", "§6.1"),
        lead=t("This is the table that v1.2 got wrong. Every bolded figure replaces an estimate, and the "
               "\"refuted\" markers are per-hop verdicts, not a general disclaimer.",
               "這就是 v1.2 寫錯的那張表。每一個粗體數字都取代了一個估算值,而「已推翻」標記是逐 hop 的判定,"
               "不是一般性的免責聲明。"),
        note=t("The end-to-end total was **confirmed** even though five of six components were refuted: v1.2's "
               "~800 ms–31 s band is wide enough to contain the measured 1483 ms p50. A correct total over wrong "
               "parts is worth stating plainly rather than presenting the table as uniformly wrong.",
               "端到端總計**已確認**,即使六個組成中有五個被推翻:v1.2 的 ~800 ms–31 s 區間寬到足以容納"
               "實測的 1483 ms p50。用錯的零件得出對的總和,這一點值得直說,而不是把整張表呈現為全錯。"),
    )

    for idx, (title, kicker, note) in {
        8: (t("AgentCore Gateway metrics", "AgentCore Gateway 指標"), "§6.2", None),
        9: (t("AgentCore Policy metrics — including the ones that publish nothing",
              "AgentCore Policy 指標 —— 包含那些什麼都不發佈的"), "§6.2",
            t("`ConfidenceScore`, `ConfidenceThreshold` and `TemporalLatency` were measured **absent** — no "
              "datapoint at any dimension combination. `LogOnlyEvalIncomplete` never published and lists 0 "
              "dimension combinations, so the alarm v1.2 prescribed on it cannot fire. If you keep it, treat "
              "missing data as breaching and add `LogOnlyMatches > 0` as the positive gate.",
              "`ConfidenceScore`、`ConfidenceThreshold` 與 `TemporalLatency` 實測**不存在** —— "
              "在任何維度組合下都沒有資料點。`LogOnlyEvalIncomplete` 從未發佈,維度組合數為 0,"
              "所以 v1.2 為它規定的告警無法觸發。若要保留它,請把「缺資料」視為違規,"
              "並加上 `LogOnlyMatches > 0` 作為正向把關。")),
        10: (t("Bedrock Guardrails metrics", "Bedrock Guardrails 指標"), "§6.2", None),
    }.items():
        h, r = src.table(d.lang, idx, budget=210)
        d.table(title, h, r, col_ratios=[3, 5, 5], kicker=kicker, note=note)

    h11, r11 = src.table(d.lang, 11, budget=210)
    h12, r12 = src.table(d.lang, 12, budget=210)
    d.table(
        t("Bedrock Runtime and AgentCore Runtime session metrics", "Bedrock Runtime 與 AgentCore Runtime session 指標"),
        h11, r11 + r12, col_ratios=[3, 5, 5], kicker="§6.2",
        lead=t("Two short tables from §6.2, shown together — Bedrock Runtime first, then Runtime session.",
               "§6.2 的兩張短表併在一起 —— 先是 Bedrock Runtime,再是 Runtime session。"),
    )

    diagrams.trace_tree(d, t)

    h, r = src.table(d.lang, 13, budget=200)
    d.table(
        t("Alerting strategy — and the period every alarm needs", "告警策略 —— 以及每個告警都需要的週期"),
        h, r, col_ratios=[4, 4, 5], kicker=t("§6.4", "§6.4"),
        lead=t("Six of these seven alarms stated no period at all in v1.2, which makes them unimplementable as "
               "written.",
               "這七個告警中有六個在 v1.2 裡完全沒有寫週期,照原文是無法實作的。"),
        note=t("**Set every period ≥ 60 s.** Measured metric publish lag is p90 = 11.5 s at n = 30, so a shorter "
               "period alarms on the gap rather than on the behaviour. Alarm on configuration change via the "
               "CloudTrail `UpdateGateway` call — not on a mode value, which is not reliably readable.",
               "**每個週期都設 ≥ 60 秒。** 實測指標發佈延遲 p90 = 11.5 秒(n = 30),"
               "週期更短的告警是在對「空隙」告警,而不是對行為告警。設定變更請透過 CloudTrail 的 "
               "`UpdateGateway` 呼叫來告警 —— 不要對模式值告警,它無法可靠讀取。"),
    )


# --------------------------------------------------------------------------- #
# §7 best practices
# --------------------------------------------------------------------------- #


def best_practices(d, t, src):
    d.divider("07", t("Best Practices: Latency Optimization with Guardrails", "最佳實務:在有 Guardrails 的前提下優化延遲"),
              t("Seven design principles, nine anti-patterns, and a per-hop policy distribution that stops you "
                "paying for the same check twice.",
                "七項設計原則、九項反模式,以及一份逐 hop 的政策分配,讓你不必為同一道檢查付兩次錢。"))

    h, r = src.table(d.lang, 15, budget=230)
    d.table(
        t("Design principles", "設計原則"),
        h, r, col_ratios=[1, 5, 8], align=["c", "l", "l"], emphasis_col=1, kicker=t("§7.1", "§7.1"),
        lead=t("Quoted from §7.1, abridged at sentence boundaries. Principle #3's premise was rescoped after "
               "measurement.",
               "引自 §7.1,在句子邊界處節錄。原則 #3 的前提在實測後已重新界定範圍。"),
        note=t("The \"guardrail evaluation is non-deterministic\" premise no longer carries recommendations: no "
               "run-to-run variation was observed on fixed inputs across three cases at n = 300 each. AWS's "
               "documented statement is retained — the document simply no longer *rests* advice on observed "
               "variation.",
               "「guardrail 評估是非確定性的」這個前提已不再承載建議:在三個案例、各 n = 300 的固定輸入下,"
               "都沒有觀察到跨次執行的變異。AWS 文件上的陳述保留 —— "
               "只是本文件不再把建議*建立*在已觀察到的變異上。"),
    )

    diagrams.threshold_tuning(d, t)

    for lo, hi in ((0, 5), (5, 9)):
        h, r = src.table(d.lang, 16, budget=170, keep_rows=list(range(lo, hi)))
        d.table(
            t("Anti-patterns to avoid", "應避免的反模式") + (" (1/2)" if lo == 0 else " (2/2)"),
            h, r, col_ratios=[5, 4, 5], emphasis_col=0, kicker=t("§7.2", "§7.2"),
            lead=t("Each row is a shape that looks responsible and costs latency, safety, or both.",
                   "每一列都是一種「看起來很負責」但代價是延遲、安全、或兩者兼具的做法。") if lo == 0 else None,
            note=t("The throttling anti-pattern is **unconfirmed**: F9-3 achieved 182.2 rps against a documented "
                   "100 rps ceiling and 0 of 480 responses were throttled, so the silent-pass question was never "
                   "put. The advice stands on reasoning, not on a measurement.",
                   "節流那條反模式**未被確認**:F9-3 在文件所載 100 rps 上限之下實際達到 182.2 rps,"
                   "480 個回應中有 0 個被節流,所以「靜默放行」的問題根本沒被問出來。"
                   "那條建議建立在推理上,不是建立在量測上。") if lo else None,
        )

    h, r = src.table(d.lang, 17, budget=200)
    d.table(
        t("Recommended guardrail distribution per hop", "各 hop 建議的 guardrail 分配"),
        h, r, col_ratios=[3, 5, 5], emphasis_col=0, kicker=t("§7.3", "§7.3"),
        lead=t("The point of the distribution is to check each risk at the cheapest hop that can see it — and not "
               "again afterwards.",
               "分配的重點是:在能看到該風險的最便宜 hop 上檢查它 —— 之後不要再檢查一次。"),
    )


# --------------------------------------------------------------------------- #
# §8 checklist
# --------------------------------------------------------------------------- #


def checklist(d, t, src):
    d.divider("08", t("Implementation Checklist", "實作檢查清單"),
              t("Four phases. The bolded items are the ones a reader following v1.2 verbatim would have got wrong.",
                "四個階段。粗體的項目,是照 v1.2 逐字照做會出錯的地方。"))

    d.bullets(
        t("Phase 1 — Foundation", "階段 1 —— 基礎建置"),
        [
            (0, t("**Pin `botocore`/`boto3` ≥ 1.43.32** before writing any policy code — 1.43.30–.31 expose "
                  "`InvokeGuardrailChecks` without `enforcementMode`, and the bundled AWS CLI v2 has no "
                  "policy-engine subcommands at all.",
                  "在寫任何政策程式之前**把 `botocore`/`boto3` 釘在 ≥ 1.43.32** —— 1.43.30–.31 露出的 "
                  "`InvokeGuardrailChecks` 沒有 `enforcementMode`,而隨附的 AWS CLI v2 完全沒有 policy-engine 子命令。"), "warn"),
            (0, t("Create Bedrock Guardrail resources with per-direction input/output settings.",
                  "建立 Bedrock Guardrail 資源,並設定各方向的輸入/輸出。")),
            (0, t("**Verify tier against traffic language** — non-EN/FR/ES traffic REQUIRES Standard, and confirm "
                  "data residency allows Standard's mandatory cross-Region inference. **Also test your own "
                  "denied-topic definition lengths:** the documented 1,000-char Standard limit was rejected with "
                  "`ValidationException`.",
                  "**依流量語言確認 tier** —— 非 EN/FR/ES 的流量必須用 Standard,並確認資料落地要求允許 Standard "
                  "強制的跨 Region 推論。**也要測試你自己的 denied-topic 定義長度:** 文件所載 Standard 的 "
                  "1,000 字上限被 `ValidationException` 拒絕。"), "warn"),
            (0, t("Set up the Gateway with a Policy Engine — and **confirm Guardrails-in-policy in YOUR Region.** "
                  "Do not plan from v1.2's five-Region list; it is refuted, but a create acceptance is control-plane "
                  "only and ap-southeast-1 was never probed.",
                  "建立帶 Policy Engine 的 Gateway —— 並**在你自己的 Region 確認 Guardrails-in-policy。** "
                  "不要照 v1.2 的五 Region 清單規劃;它已被駁回,但「建立被接受」只代表控制平面,"
                  "而且 ap-southeast-1 從未被探測。"), "warn"),
            (0, t("**Write an explicit baseline permit policy BEFORE enabling ENFORCE, and pass an explicit "
                  "`validationMode`.** Poll the policy `status`; a 202 is not success.",
                  "**在啟用 ENFORCE 之前寫好明確的基線 permit 政策,並明確給定 `validationMode`。** "
                  "請輪詢政策 `status`;202 不代表成功。"), "warn"),
            (0, t("Define Cedar policies for tool authorization, and configure guardrails in the Gateway policy — "
                  "thresholds are mandatory in hand-written policies.",
                  "定義工具授權的 Cedar 政策,並在 Gateway 政策中設定 guardrails —— 手寫政策中門檻值是必填的。")),
            (0, t("**Configure input tagging (random `tagSuffix`) wherever prompt-attack filtering is expected at "
                  "the model layer** — untagged recall measured 0 [0, 0.031].",
                  "**凡是預期在模型層做 prompt 攻擊過濾的地方都要設定 input tagging(隨機 `tagSuffix`)** —— "
                  "未加標記的 recall 實測為 0 [0, 0.031]。"), "warn"),
            (0, t("Apply network containment (§4.5): Runtime VPC mode with an egress allowlist, Code Interpreter "
                  "Sandbox/VPC + DNS Firewall, VPC condition keys on the deployment IAM role.",
                  "套用網路圍堵(§4.5):Runtime 用 VPC 模式加對外白名單、Code Interpreter 用 Sandbox/VPC 加 "
                  "DNS Firewall、在部署用的 IAM 角色上加 VPC 條件鍵。")),
            (0, t("Enable CloudWatch Transaction Search, then AgentCore Observability tracing, then instrument your "
                  "own code with ADOT for custom spans. Spans lag ≈50 s.",
                  "啟用 CloudWatch Transaction Search,再啟用 AgentCore Observability 追蹤,"
                  "然後用 ADOT 為自己的程式碼加上自訂 span。Span 約延遲 50 秒。")),
        ],
        kicker=t("§8 Phase 1", "§8 階段 1"),
    )

    d.bullets(
        t("Phase 2 — Monitoring", "階段 2 —— 監控"),
        [
            (0, t("Create a hop-by-hop latency dashboard (GuardrailLatency, InvocationLatency, "
                  "guardrailProcessingLatency). **Do not add `ConfidenceScore` or `ConfidenceThreshold` — neither "
                  "published a datapoint.** On any mismatch metric chart `SampleCount` at one pinned dimension "
                  "combination, not `Sum` across dimensions, which reads up to 6× the request count.",
                  "建立逐 hop 的延遲儀表板(GuardrailLatency、InvocationLatency、guardrailProcessingLatency)。"
                  "**不要加 `ConfidenceScore` 或 `ConfidenceThreshold` —— 兩者都沒有發佈任何資料點。** "
                  "任何 mismatch 指標請在單一固定維度組合下畫 `SampleCount`,不要跨維度用 `Sum`,"
                  "那會讀到請求數的 6 倍。"), "warn"),
            (0, t("Set alarms per checkpoint with **period ≥ 60 s** (measured publish lag p90 = 11.5 s), and alarm "
                  "on configuration change keyed on the CloudTrail `UpdateGateway` call rather than on a mode value.",
                  "為每個檢查點設定告警,**週期 ≥ 60 秒**(實測發佈延遲 p90 = 11.5 秒),"
                  "並以 CloudTrail 的 `UpdateGateway` 呼叫為鍵對設定變更告警,而不是對模式值告警。"), "warn"),
            (0, t("**Make policy-denial detection surface-aware:** match the MCP shape (HTTP 200 + JSON-RPC "
                  "`-32002`) **and** the inference shape (HTTP 403 + `permission_error`), **and** check advertised "
                  "tool count — under an active forbid, `tools/list` succeeds with an empty list and raises no error "
                  "to alarm on.",
                  "**讓政策拒絕的偵測具備介面意識:** 同時比對 MCP 的形狀(HTTP 200 + JSON-RPC `-32002`)"
                  "**與** inference 的形狀(HTTP 403 + `permission_error`),**並且**檢查對外宣告的工具數量 —— "
                  "在 forbid 生效時 `tools/list` 會成功並回傳空清單,不會產生任何可告警的錯誤。"), "warn"),
            (0, t("`LogOnlyEvalIncomplete` is **not usable as v1.2 prescribed** — it published nothing and lists 0 "
                  "dimension combinations. If you keep it, treat missing data as breaching and add "
                  "`LogOnlyMatches > 0` as the positive gate instead.",
                  "`LogOnlyEvalIncomplete` **無法照 v1.2 規定的方式使用** —— 它沒有發佈任何資料,"
                  "維度組合數為 0。若要保留它,請把缺資料視為違規,並改用 `LogOnlyMatches > 0` 作為正向把關。"), "warn"),
            (0, t("Configure guardrail-specific metrics (invocation count, latency, throttles, "
                  "InvocationsIntervened, TextUnitCount) and enable distributed tracing across all components.",
                  "設定 guardrail 專屬指標(呼叫次數、延遲、throttle、InvocationsIntervened、TextUnitCount),"
                  "並在所有元件上啟用分散式追蹤。")),
            (0, t("Write the runbook for a latency spike investigation before you need it.",
                  "在需要之前就先寫好延遲突增的調查 runbook。")),
        ],
        kicker=t("§8 Phase 2", "§8 階段 2"),
    )

    d.twocol(
        t("Phases 3 and 4 — Optimization and Maintenance", "階段 3 與 4 —— 最佳化與維運"),
        (t("Phase 3 — Optimization", "階段 3 —— 最佳化"), BLUE, [
            (0, t("Enable AgentCore Evaluations (online mode) for continuous quality assessment — verify PrivateLink "
                  "posture first if you are in a private network.",
                  "啟用 AgentCore Evaluations(線上模式)做持續品質評估 —— 若在私有網路,先確認 PrivateLink 狀態。")),
            (0, t("Establish baseline latency measurements per hop — you cannot detect a regression against an "
                  "estimate.",
                  "為每個 hop 建立延遲基線 —— 你無法用估算值去偵測回歸。")),
            (0, t("Run Optimization Recommendations when quality degrades, and validate with batch evaluations "
                  "before A/B testing.",
                  "品質下降時執行 Optimization Recommendations,並在 A/B 測試前用批次評估驗證。")),
            (0, t("Implement A/B testing via Gateway traffic splitting.", "透過 Gateway 流量分流實作 A/B 測試。")),
            (0, t("Document each optimization cycle and every threshold-tuning decision — including the ones you "
                  "reverted.",
                  "記錄每一輪最佳化與每一次門檻值調校的決策 —— 包含被你回退的那些。")),
        ]),
        (t("Phase 4 — Maintenance", "階段 4 —— 維運"), GREEN, [
            (0, t("Review guardrail policies quarterly and remove redundant checks — every duplicate check is "
                  "latency you pay for twice.",
                  "每季檢視 guardrail 政策並移除多餘的檢查 —— 每一道重複的檢查都是你付兩次的延遲。")),
            (0, t("Monitor latency trends as model and traffic patterns change.",
                  "隨模型與流量型態變化持續監控延遲趨勢。")),
            (0, t("Update Cedar policies as new tools are added — a new tool with no policy is default-denied, "
                  "which is safe but looks like an outage.",
                  "新增工具時同步更新 Cedar 政策 —— 沒有政策的新工具會被預設拒絕,"
                  "那是安全的,但看起來像故障。")),
            (0, t("Revisit thresholds against observed false-positive and false-negative rates.",
                  "依觀察到的誤報率與漏報率重新檢視門檻值。")),
            (0, t("**Re-run the guardrail regression set periodically — AWS auto-updates the underlying models with "
                  "no action on your part.**",
                  "**定期重跑 guardrail 回歸測試集 —— AWS 會在你什麼都沒做的情況下自行更新底層模型。**")),
        ]),
        kicker=t("§8 Phases 3–4", "§8 階段 3–4"),
    )


# --------------------------------------------------------------------------- #
# §9 · §10 · appendices
# --------------------------------------------------------------------------- #


def appendices(d, t, src):
    d.divider("09", t("Reference Architecture: The Complete Closed Loop", "參考架構:完整閉環"),
              t("Every hop, every metric surface, and the feedback path — on one page.",
                "所有 hop、所有指標介面,以及反饋路徑 —— 在一頁上。"))

    diagrams.reference_architecture(d, t)

    d.divider("10", t("References and Appendices", "參考資料與附錄"),
              t("24 AWS documentation references, the checkpoint decision matrix, the latency techniques, and the "
                "full change log from v1.2.",
                "24 份 AWS 文件參考、檢查點決策矩陣、延遲優化技巧,以及自 v1.2 起的完整變更記錄。"))

    for lo, hi, part in ((0, 12, "1/2"), (12, 24, "2/2")):
        h, r = src.table(d.lang, 18, keep_rows=list(range(lo, hi)))
        d.table(
            t(f"Key AWS documentation references ({part})", f"主要 AWS 文件參考({part})"),
            h, r, col_ratios=[4, 8], kicker=t("§10", "§10"),
            lead=t("All 24 links were checked live on 2026-08-09 and all 24 resolved. Link liveness is a property "
                   "that changes, so that observation is dated rather than asserted.",
                   "全部 24 條連結在 2026-08-09 實際檢查,24 條全部可連。連結有效性會隨時間改變,"
                   "所以這是一項有日期的觀察,不是一項斷言。") if lo == 0 else None,
        )

    h, r = src.table(d.lang, 19, budget=120)
    d.table(
        t("Checkpoint decision matrix: check each risk at the cheapest hop that can see it",
          "檢查點決策矩陣:在能看到該風險的最便宜 hop 上檢查它"),
        h, r, col_ratios=[4, 3, 4, 5, 3], emphasis_col=0, kicker=t("Appendix A", "附錄 A"),
        lead=t("✅ = apply here · ❌ = do not · Optional = only if the cheaper hop cannot see this risk.",
               "✅ = 在此套用 · ❌ = 不要 · Optional = 僅當較便宜的 hop 看不到這項風險時。"),
    )

    h, r = src.table(d.lang, 20, budget=200)
    d.table(
        t("Latency optimization techniques", "延遲優化技巧"),
        h, r, col_ratios=[4, 6, 4], emphasis_col=0, kicker=t("Appendix B", "附錄 B"),
    )

    d.bullets(
        t("What measurement changed, in one page", "量測改變了什麼,一頁看完"),
        [
            (0, t("**Corrections driven by FALSE verdicts — the document was wrong:**", "**由 FALSE 判定驅動的修正 —— 文件寫錯了:**"), "head"),
            (1, t("§6.1 latency table: illustrative ranges replaced by measured p50/p90/p99; five of six hops "
                  "outside v1.2's bands. Per-additional-tool-call cost 165–750 ms → **≈850 ms**.",
                  "§6.1 延遲表:示意區間被實測 p50/p90/p99 取代;六個 hop 中五個落在 v1.2 區間外。"
                  "每次額外工具呼叫成本 165–750 ms → **約 850 ms**。")),
            (1, t("§3.1/§2.1/§9: \"HTTP 403\" corrected — MCP denials are HTTP 200 + JSON-RPC -32002, 120/120.",
                  "§3.1/§2.1/§9:「HTTP 403」已修正 —— MCP 的拒絕是 HTTP 200 + JSON-RPC -32002,120/120。")),
            (1, t("§3.2/Appendix A: 9 of 31 documented PII entity types measured undetected.",
                  "§3.2/附錄 A:31 種文件所列 PII 實體類型中,9 種實測未被偵測。")),
            (1, t("§3.4 tier table: Classic prompt-leakage detection is weak-but-measurable (recall 0.41), not "
                  "\"No\"; the Standard 1,000-char denied-topic limit was rejected.",
                  "§3.4 tier 表:Classic 的 prompt leakage 偵測是「弱但可量測」(recall 0.41),不是「No」;"
                  "Standard 的 1,000 字 denied-topic 上限被拒絕。")),
            (1, t("§6.2/§6.4/§8: `ConfidenceScore`, `ConfidenceThreshold`, `TemporalLatency` absent; "
                  "`LogOnlyEvalIncomplete` unusable as an alarm.",
                  "§6.2/§6.4/§8:`ConfidenceScore`、`ConfidenceThreshold`、`TemporalLatency` 不存在;"
                  "`LogOnlyEvalIncomplete` 無法作為告警使用。")),
            (1, t("§7.1: calibration re-pointed from CloudWatch to the application logs; §5.1: \"Automated "
                  "Reasoning has no streaming support\" withdrawn.",
                  "§7.1:校準來源從 CloudWatch 改為應用程式 log;§5.1:「Automated Reasoning 不支援串流」已撤回。")),
            (0, t("**Additions driven by TRUE verdicts — new prerequisites the document did not state:**",
                  "**由 TRUE 判定驅動的新增 —— 文件原本沒寫的前置條件:**"), "head"),
            (1, t("The `botocore` ≥ 1.43.32 floor with its 1.43.30–.31 trap window; the explicit `validationMode` "
                  "requirement; the ≈50 s span lag and p90 = 11.5 s metric publish lag; actual span names; "
                  "revocation is eventually consistent in **both** directions, so \"revoke, confirm, proceed\" "
                  "runbooks are prohibited.",
                  "`botocore` ≥ 1.43.32 的下限與 1.43.30–.31 的陷阱區間;明確 `validationMode` 的要求;"
                  "約 50 秒的 span 延遲與 p90 = 11.5 秒的指標發佈延遲;實際的 span 名稱;"
                  "撤銷在**兩個**方向上都是最終一致的,因此「撤銷、確認、繼續」的 runbook 被禁止。")),
            (0, t("**Deliberately left unchanged:** every claim whose case returned INCONCLUSIVE, was untestable, "
                  "or is outstanding — per-direction independence, streaming modes, interceptors, `suppressOutput`, "
                  "the 10-content-block cap, auto-update drift, the three target types, reasoning-block exclusion, "
                  "network containment, the fail-secure timeout, and §3.2's billing asymmetry.",
                  "**刻意保持不變:** 所有判定為 INCONCLUSIVE、不可測、或未結案的主張 —— "
                  "各方向獨立設定、串流模式、interceptor、`suppressOutput`、10 個內容區塊上限、自動更新漂移、"
                  "三種 target 類型、推理區塊排除、網路圍堵、fail-secure 逾時,以及 §3.2 的計費不對稱。"), "head"),
            (0, t("Marker-only changes are the majority of the diff. That is the point: the document says less than "
                  "it could, and everything it does say now has a file behind it.",
                  "差異中大多數只是加標記。這正是重點:文件說得比它能說的更少,而它現在說的每一句背後都有一份檔案。"), "muted"),
        ],
        kicker=t("Appendix D", "附錄 D"),
        columns=2,
        note=t("Every change is traceable to a verdict file under `results/phase1/`. Counts re-derived by "
               "`census.py` on 2026-08-15.",
               "每一項變更都可追溯到 `results/phase1/` 下的判定檔。數字由 `census.py` 於 2026-08-15 重新推導。"),
    )
