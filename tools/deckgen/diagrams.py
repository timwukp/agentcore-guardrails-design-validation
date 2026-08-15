"""The document's eleven mermaid figures, rebuilt as native PowerPoint shapes.

Rasterising them was the other option and it was rejected: there is no `mmdc` and no
LibreOffice on this machine, and a PNG cannot be edited by whoever presents the deck.
Native shapes are editable, sharp at any zoom, and carry no render dependency.

Each function takes the open :class:`~deckgen.render.Deck` and ``t(en, zh)``, the
bilingual string selector, so one definition serves both decks and the two cannot
drift apart. Coordinates are inches **inside the body area** — ``x`` from 0 to
``CONTENT_W``, ``y`` from 0 downwards from the top of the body.

One sharp edge: edge *waypoints* are absolute slide coordinates (the renderer's edge
anchors already are), so they must go through :func:`at`. And because ``at`` assumes
the body starts at ``BODY_TOP``, a diagram that uses waypoints must not also pass a
``lead`` — a lead pushes the body down and the waypoint would not follow.
"""

from __future__ import annotations

from pptx.enum.shapes import MSO_SHAPE

from deckgen.render import (
    AMBER, AMBER_L, BAND, BLUE, BLUE_L, BODY_TOP, CONTENT_W, FAINT, GREEN, GREEN_L,
    INK, LINE, MARGIN, MUTED, NAVY, NAVY_L, ORANGE, RED, RED_L, WHITE,
)

# -- helpers --------------------------------------------------------------- #


def at(x, y):
    """Body-relative → absolute slide inches, for edge waypoints."""
    return (MARGIN + x, BODY_TOP + y)


def node(x, y, w, h, text, **kw):
    d = {"x": x, "y": y, "w": w, "h": h, "text": text}
    d.update(kw)
    return d


def row(n, w, gap, x0=0.0):
    """``n`` evenly spaced x positions of width ``w``."""
    return [x0 + i * (w + gap) for i in range(n)]


PHASE_FILL = {"before": BLUE_L, "during": BAND, "after": GREEN_L}


# -- §2 the closed loop ---------------------------------------------------- #


def closed_loop(d, t):
    gw = t("Gateway Guardrail\n+ Input Guardrail\nHop #1 · #2",
           "Gateway Guardrail\n+ 輸入 Guardrail\nHop #1 · #2")
    rt = t("Agent Runtime\n+ Tool Auth (Cedar)\n+ Observability\nHop #3 · #4 · #5",
           "Agent Runtime\n+ 工具授權 (Cedar)\n+ 可觀測性\nHop #3 · #4 · #5")
    out = t("Output Guardrail\n+ Evaluation\n+ Optimization\nHop #6",
            "輸出 Guardrail\n+ Evaluation\n+ Optimization\nHop #6")
    xs = [0.10, 4.17, 8.24]
    d.diagram(
        t("The closed loop: BEFORE → DURING → AFTER",
          "閉環:BEFORE → DURING → AFTER"),
        nodes={
            "gw": node(xs[0] + 0.25, 1.15, 3.25, 1.85, gw, fill=WHITE, line=BLUE, line_w=1.5),
            "rt": node(xs[1] + 0.25, 1.15, 3.25, 1.85, rt, fill=WHITE, line=NAVY_L, line_w=1.5),
            "out": node(xs[2] + 0.25, 1.15, 3.25, 1.85, out, fill=WHITE, line=GREEN, line_w=1.5),
        },
        groups=[
            {"x": xs[0], "y": 0.55, "w": 3.75, "h": 2.85, "label": t("BEFORE — Input Safety", "BEFORE —— 輸入安全"),
             "fill": BLUE_L, "line": BLUE, "fg": BLUE},
            {"x": xs[1], "y": 0.55, "w": 3.75, "h": 2.85, "label": t("DURING — Execution Control", "DURING —— 執行控制"),
             "fill": BAND, "line": NAVY_L, "fg": NAVY},
            {"x": xs[2], "y": 0.55, "w": 3.75, "h": 2.85, "label": t("AFTER — Output Safety + Improvement", "AFTER —— 輸出安全 + 持續改善"),
             "fill": GREEN_L, "line": GREEN, "fg": GREEN},
        ],
        edges=[
            {"a": "gw", "b": "rt", "w": 1.75},
            {"a": "rt", "b": "out", "w": 1.75},
            {"a": "out", "b": "gw", "side": "bb", "dash": "dash", "color": ORANGE, "w": 1.5,
             "waypoint": [at(10.11, 4.35), at(1.97, 4.35)],
             "label": t("FEEDBACK LOOP — updated prompts, policies, thresholds",
                        "FEEDBACK LOOP —— 更新後的 prompt、政策、門檻值"),
             "lcolor": AMBER, "loff": (0, 0.02)},
        ],
        note=t("Hop numbering is normative for this document (§2.1). Hop #3 is model inference — not a guardrail "
               "checkpoint, included because it dominates the latency budget.",
               "Hop 編號在本文件內為規範性定義(§2.1)。Hop #3 是模型推論——它不是 guardrail 檢查點,納入是因為它主導延遲預算。"),
    )


# -- §2.1 hop lifecycle ---------------------------------------------------- #


def hop_lifecycle(d, t):
    xs = row(6, 1.75, 0.31, 0.02)
    labels = [
        (t("Hop #1\nGateway policy\nguardrail\n\np50 401 ms", "Hop #1\nGateway 政策\nguardrail\n\np50 401 ms"), "before"),
        (t("Hop #2\nBedrock input\nguardrail\n\np50 231 ms", "Hop #2\nBedrock 輸入\nguardrail\n\np50 231 ms"), "before"),
        (t("Hop #3\nModel\ninference\n\n500 ms – 30 s", "Hop #3\n模型\n推論\n\n500 ms – 30 s"), "during"),
        (t("Hop #4\nCedar tool\nauthorization\n\np50 55 ms", "Hop #4\nCedar 工具\n授權\n\np50 55 ms"), "during"),
        (t("Hop #5\nTool req/resp\nguardrail\n\np50 401 ms × N", "Hop #5\n工具請求/回應\nguardrail\n\np50 401 ms × N"), "during"),
        (t("Hop #6\nBedrock output\nguardrail\n\np50 234 ms", "Hop #6\nBedrock 輸出\nguardrail\n\np50 234 ms"), "after"),
    ]
    nodes = {}
    for i, ((text, phase), x) in enumerate(zip(labels, xs)):
        nodes[f"h{i}"] = node(x, 1.30, 1.75, 1.70, text, fill=WHITE,
                              line={"before": BLUE, "during": NAVY_L, "after": GREEN}[phase], line_w=1.4)
    d.diagram(
        t("Hop numbering (normative) — and where the milliseconds go",
          "Hop 編號(規範性)—— 以及毫秒花在哪裡"),
        nodes=nodes,
        groups=[
            {"x": 0.0, "y": 0.42, "w": 3.85, "h": 0.46, "label": t("BEFORE", "BEFORE"), "fill": BLUE_L, "line": BLUE, "fg": BLUE},
            {"x": 4.11, "y": 0.42, "w": 5.93, "h": 0.46, "label": t("DURING", "DURING"), "fill": BAND, "line": NAVY_L, "fg": NAVY},
            {"x": 10.27, "y": 0.42, "w": 1.80, "h": 0.46, "label": t("AFTER", "AFTER"), "fill": GREEN_L, "line": GREEN, "fg": GREEN},
        ],
        edges=[{"a": f"h{i}", "b": f"h{i+1}", "w": 1.4} for i in range(5)],
        lead=t("Measured p50 latency per hop, n = 1000 per hop, us-east-1. Five of the six hops fell outside v1.2's "
               "illustrative bands, so the bands were replaced by measurements.",
               "每個 hop 的實測 p50 延遲,每 hop n = 1000,us-east-1。六個 hop 中有五個落在 v1.2 的示意區間之外,"
               "因此區間已被實測值取代。"),
        note=t("Measured p50: Hop #1 401 ms · Hop #2 231 ms · Hop #4 55 ms · Hop #5 401 ms × N calls · Hop #6 "
               "234 ms. Hop #3 (model inference) was not re-measured and carries v1.2's 500 ms–30 s. Single-tool-call "
               "total: 1483 / 1722 / 2107 ms. p90/p99 and confidence intervals are in §6.1.",
               "實測 p50:Hop #1 401 ms · Hop #2 231 ms · Hop #4 55 ms · Hop #5 401 ms × N 次呼叫 · Hop #6 234 ms。"
               "Hop #3(模型推論)未重新量測,沿用 v1.2 的 500 ms–30 s。單次工具呼叫總計:1483 / 1722 / 2107 ms。"
               "p90/p99 與信賴區間見 §6.1。"),
    )


# -- §3.2 billing asymmetry ------------------------------------------------ #


def billing_asymmetry(d, t):
    d.diagram(
        t("Billing asymmetry: blocking early is cheaper than blocking late",
          "計費不對稱:提早阻擋比延後阻擋便宜"),
        nodes={
            "a1": node(0.10, 0.95, 1.95, 1.00, t("User prompt", "使用者 prompt"), fill=WHITE),
            "a2": node(2.45, 0.95, 2.45, 1.00, t("Hop #2 input\nguardrail — BLOCKS", "Hop #2 輸入\nguardrail —— 阻擋"),
                       fill=BLUE_L, line=BLUE),
            "a3": node(5.30, 0.95, 2.55, 1.00, t("Model inference\nNEVER RUNS", "模型推論\n完全沒有執行"),
                       fill=WHITE, line=LINE, fg=MUTED),
            "a4": node(8.25, 0.95, 3.80, 1.00, t("Charged: guardrail text units only", "計費:僅 guardrail text unit"),
                       fill=GREEN_L, line=GREEN, fg=GREEN, bold=True),
            "b1": node(0.10, 2.85, 1.95, 1.00, t("User prompt", "使用者 prompt"), fill=WHITE),
            "b2": node(2.45, 2.85, 2.45, 1.00, t("Hop #3 model\ninference RUNS", "Hop #3 模型\n推論執行了"),
                       fill=BAND, line=NAVY_L),
            "b3": node(5.30, 2.85, 2.55, 1.00, t("Hop #6 output\nguardrail — BLOCKS", "Hop #6 輸出\nguardrail —— 阻擋"),
                       fill=GREEN_L, line=GREEN),
            "b4": node(8.25, 2.85, 3.80, 1.00, t("Charged: inference already ran + units",
                                                 "計費:推論已經跑過 + text unit"),
                       fill=RED_L, line=RED, fg=RED, bold=True),
        },
        edges=[
            {"a": "a1", "b": "a2"}, {"a": "a2", "b": "a3", "dash": "dash", "color": FAINT}, {"a": "a3", "b": "a4"},
            {"a": "b1", "b": "b2"}, {"a": "b2", "b": "b3"}, {"a": "b3", "b": "b4"},
        ],
        note=t("UNMEASURED — F10-1 is the one outstanding case. Cost Explorer's finest granularity is daily and the "
               "oracle reads a per-request delta, so this claim stands exactly as v1.2 wrote it, unsupported by "
               "measurement in either direction (results/CENSUS-NOT-MEASURED.md).",
               "未實測 —— F10-1 是唯一未結案的案例。Cost Explorer 最細只到「日」,而 oracle 要讀的是逐請求的差值,"
               "因此這項主張完全照 v1.2 原文保留,兩個方向都沒有實測支持(results/CENSUS-NOT-MEASURED.md)。"),
    )


# -- §3.4 tier decision ---------------------------------------------------- #


def tier_decision(d, t):
    d.diagram(
        t("Tier selection is decided by traffic language, not by feature appetite",
          "Tier 的選擇由流量語言決定,不是由功能偏好決定"),
        nodes={
            "q": node(0.10, 1.85, 2.45, 1.30, t("What language is\nyour traffic?", "你的流量是\n什麼語言?"),
                      fill=NAVY, fg=WHITE, bold=True, shape=MSO_SHAPE.ROUNDED_RECTANGLE),
            "en": node(3.05, 0.60, 2.55, 1.15, t("EN / FR / ES only", "只有 EN / FR / ES"), fill=WHITE, line=BLUE),
            "cl": node(6.10, 0.60, 2.60, 1.15, t("Classic tier is sufficient", "Classic tier 就足夠"),
                       fill=BLUE_L, line=BLUE, fg=BLUE, bold=True),
            "cn": node(9.20, 0.60, 2.85, 1.15, t("Prompt leakage: weak, not absent — recall 0.41",
                                                 "Prompt leakage:弱,但不是沒有 —— recall 0.41"),
                       fill=WHITE, line=LINE, fg=MUTED),
            "zh": node(3.05, 3.35, 2.55, 1.15, t("Any zh / ja / ko / other", "任何 zh / ja / ko / 其他"),
                       fill=WHITE, line=RED),
            "st": node(6.10, 3.35, 2.60, 1.15, t("Standard tier REQUIRED", "必須用 Standard tier"),
                       fill=RED_L, line=RED, fg=RED, bold=True),
            "cr": node(9.20, 3.35, 2.85, 1.15, t("crossRegionConfig is mandatory — data leaves the Region",
                                                 "crossRegionConfig 是強制的 —— 資料會離開該 Region"),
                       fill=AMBER_L, line=AMBER, fg=AMBER),
        },
        edges=[
            {"a": "q", "b": "en", "label": t("EN/FR/ES", "EN/FR/ES")},
            {"a": "q", "b": "zh", "label": t("anything else", "其他任何語言"), "color": RED},
            {"a": "en", "b": "cl"}, {"a": "cl", "b": "cn", "dash": "dash", "color": FAINT},
            {"a": "zh", "b": "st", "color": RED}, {"a": "st", "b": "cr", "color": RED},
        ],
        note=t("Classic detection on zh-TW / zh-CN / ja / ko measured 0 [0, 0.0175] at n=240 — \"ineffective\" is "
               "literal, not cautious. Standard's paired improvement p ≈ 4.6×10⁻⁴⁶ at n=216. The documented "
               "1,000-char denied-topic limit was rejected with ValidationException.",
               "Classic 在 zh-TW / zh-CN / ja / ko 的偵測率實測為 0 [0, 0.0175](n=240)——「無效」是字面意思,"
               "不是保守說法。Standard 的成對改善 p ≈ 4.6×10⁻⁴⁶(n=216)。文件所寫的 1,000 字 denied-topic 上限"
               "被 ValidationException 拒絕。"),
    )


# -- §4.1 LOG_ONLY precedence --------------------------------------------- #


def log_only_precedence(d, t):
    enforced = t("ENFORCED\nrequest is denied", "強制執行\n請求被拒絕")
    logged = t("LOGGED ONLY\nnothing is blocked", "只記錄\n什麼都不阻擋")
    d.diagram(
        t("LOG_ONLY has two levels, and the weaker one wins",
          "LOG_ONLY 有兩層,較弱的那一層勝出"),
        nodes={
            "ch1": node(3.30, 0.55, 4.30, 0.55, t("Policy enforcementMode = ACTIVE", "政策 enforcementMode = ACTIVE"),
                        fill=NAVY, fg=WHITE, bold=True, size=11),
            "ch2": node(7.75, 0.55, 4.30, 0.55, t("Policy enforcementMode = LOG_ONLY", "政策 enforcementMode = LOG_ONLY"),
                        fill=NAVY, fg=WHITE, bold=True, size=11),
            "rh1": node(0.10, 1.25, 3.05, 1.45, t("Engine mode\nENFORCE", "Engine 模式\nENFORCE"),
                        fill=NAVY_L, fg=WHITE, bold=True),
            "rh2": node(0.10, 2.85, 3.05, 1.45, t("Engine mode\nLOG_ONLY", "Engine 模式\nLOG_ONLY"),
                        fill=NAVY_L, fg=WHITE, bold=True),
            "c11": node(3.30, 1.25, 4.30, 1.45, enforced, fill=GREEN_L, line=GREEN, fg=GREEN, bold=True),
            "c12": node(7.75, 1.25, 4.30, 1.45, logged, fill=AMBER_L, line=AMBER, fg=AMBER, bold=True),
            "c21": node(3.30, 2.85, 4.30, 1.45, logged, fill=AMBER_L, line=AMBER, fg=AMBER, bold=True),
            "c22": node(7.75, 2.85, 4.30, 1.45, logged, fill=AMBER_L, line=AMBER, fg=AMBER, bold=True),
        },
        lead=t("Enforcement is the conjunction of both levels: only ENFORCE × ACTIVE denies anything. "
               "Three of the four cells look identical in production and block nothing.",
               "強制執行是兩層的交集:只有 ENFORCE × ACTIVE 會真的拒絕。四格中有三格在生產環境看起來一樣,"
               "而且什麼都不會擋。"),
        note=t("\"Nothing is blocked\" is not \"nothing is visible\": shadow evaluations still log DENY/FORBID at "
               "ERROR level, which reads like an outage in a log search. Gate any flip-count reading on "
               "LogOnlyMatches > 0 first — LogOnlyEvalIncomplete published no datapoint and lists 0 dimension "
               "combinations, so its prescribed alarm cannot fire.",
               "「什麼都不擋」不等於「什麼都看不到」:shadow 評估仍會以 ERROR 等級記錄 DENY/FORBID,"
               "在 log 搜尋裡看起來像是故障。任何 flip 次數的判讀都要先以 LogOnlyMatches > 0 把關 —— "
               "LogOnlyEvalIncomplete 沒有發佈任何資料點,維度組合數為 0,它規定的告警根本無法觸發。"),
    )


# -- §4.4 containment boundary -------------------------------------------- #


def containment_boundary(d, t):
    d.diagram(
        t("The containment pattern: the Gateway is the only path to a tool",
          "圍堵模式:Gateway 是通往工具的唯一路徑"),
        nodes={
            "rt": node(0.35, 1.15, 2.75, 1.55, t("Agent Runtime\nuntrusted model output\n+ customer code",
                                                 "Agent Runtime\n不可信的模型輸出\n+ 自己的程式碼"), fill=WHITE, line=NAVY_L),
            "gw": node(3.55, 1.15, 2.85, 1.55, t("AgentCore Gateway\nCedar permit / forbid\nHop #4 · #5",
                                                 "AgentCore Gateway\nCedar permit / forbid\nHop #4 · #5"),
                       fill=GREEN_L, line=GREEN, fg=GREEN, bold=True, line_w=1.75),
            "tg": node(6.85, 1.15, 2.35, 1.55, t("Tool targets\n(MCP · inference)", "工具 target\n(MCP · inference)"),
                       fill=WHITE, line=LINE),
            "tv": node(9.65, 1.15, 2.40, 1.55, t("Token Vault\ncredentials vended\nper call", "Token Vault\n憑證逐次呼叫發放"),
                       fill=BLUE_L, line=BLUE, fg=BLUE),
            "x1": node(0.35, 3.60, 3.55, 1.00, t("① Call the tool API directly", "① 直接呼叫工具 API"),
                       fill=RED_L, line=RED, fg=RED, size=10),
            "x2": node(4.20, 3.60, 3.55, 1.00, t("② Arbitrary egress / shadow tools", "② 任意對外連線 / 影子工具"),
                       fill=RED_L, line=RED, fg=RED, size=10),
            "x3": node(8.05, 3.60, 4.00, 1.00, t("③ Read execution-role creds, disable the engine",
                                                 "③ 讀取 execution-role 憑證,停用 engine"),
                       fill=RED_L, line=RED, fg=RED, size=10),
        },
        edges=[
            {"a": "rt", "b": "gw", "w": 1.75}, {"a": "gw", "b": "tg", "w": 1.75},
            {"a": "tg", "b": "tv", "dash": "dash", "color": BLUE},
            {"a": "x1", "b": "tg", "dash": "dash", "color": RED, "side": "tb"},
            {"a": "x2", "b": "tg", "dash": "dash", "color": RED, "side": "tb"},
            {"a": "x3", "b": "gw", "dash": "dash", "color": RED, "side": "tl"},
        ],
        legend=[(t("enforced path", "強制路徑"), GREEN), (t("bypass route to close", "須封閉的繞過路徑"), RED)],
        note=t("Route ③ is the critical one and it is confirmed: 3 of 3 distinct tool sessions read the runtime's own "
               "execution role over the microVM metadata service at 169.254.169.254. Measured on one calendar day, so "
               "the amendment is deferred, not the finding. Routes ④ (account-level SCP) and ⑤ (silent degradation) "
               "are in §4.4's table.",
               "路徑 ③ 是最關鍵的一條,而且已被確認:3 個不同的工具 session 全部經由 169.254.169.254 的 microVM "
               "metadata service 讀到 runtime 自己的 execution role。實測只有一個日曆日,所以延後的是修訂,不是發現。"
               "路徑 ④(帳戶層級 SCP)與 ⑤(靜默降級)見 §4.4 的表格。"),
    )


# -- §4.5.5 network containment ------------------------------------------- #


def network_containment(d, t):
    d.diagram(
        t("Network containment: VPC mode, an egress allowlist, and DNS as the leak nobody expects",
          "網路圍堵:VPC 模式、對外白名單,以及沒人預期的 DNS 洩漏通道"),
        nodes={
            "rt": node(0.45, 1.15, 2.55, 1.10, t("Runtime\nVPC mode", "Runtime\nVPC 模式"), fill=WHITE, line=NAVY_L),
            "ci": node(0.45, 2.50, 2.55, 1.10, t("Code Interpreter\nSandbox or VPC", "Code Interpreter\nSandbox 或 VPC"),
                       fill=WHITE, line=NAVY_L),
            "fw": node(3.30, 1.15, 2.55, 1.10, t("Route 53 Resolver\nDNS Firewall", "Route 53 Resolver\nDNS Firewall"),
                       fill=AMBER_L, line=AMBER, fg=AMBER),
            "s3": node(3.30, 2.50, 2.55, 1.10, t("S3 Gateway endpoint\n(session storage)", "S3 Gateway endpoint\n(session 儲存)"),
                       fill=WHITE, line=LINE),
            "al": node(6.55, 0.95, 2.30, 3.30, t("Egress\nallowlist", "對外\n白名單"), fill=NAVY, fg=WHITE, bold=True),
            "e1": node(9.20, 0.95, 2.85, 0.72, t("AgentCore Gateway endpoint", "AgentCore Gateway endpoint"),
                       fill=GREEN_L, line=GREEN, fg=GREEN, size=9.5),
            "e2": node(9.20, 1.79, 2.85, 0.72, t("Bedrock model endpoints", "Bedrock 模型 endpoint"), fill=WHITE, size=9.5),
            "e3": node(9.20, 2.63, 2.85, 0.72, t("STS", "STS"), fill=WHITE, size=9.5),
            "e4": node(9.20, 3.47, 2.85, 0.78, t("CloudWatch Logs · X-Ray", "CloudWatch Logs · X-Ray"), fill=WHITE, size=9.5),
        },
        groups=[{"x": 0.10, "y": 0.55, "w": 6.05, "h": 3.85,
                 "label": t("Customer VPC — private subnets, no internet gateway",
                            "客戶 VPC —— 私有子網,沒有 internet gateway"),
                 "fill": BAND, "line": NAVY_L, "fg": NAVY}],
        edges=[
            {"a": "rt", "b": "al"}, {"a": "ci", "b": "al"},
            {"a": "al", "b": "e1"}, {"a": "al", "b": "e2"}, {"a": "al", "b": "e3"}, {"a": "al", "b": "e4"},
        ],
        note=t("Sandbox mode still allows DNS, which is a limited exfiltration channel — hence the DNS Firewall. "
               "Enforcing VPC deployment is an IAM job (VPC condition keys on the deployment role), not a "
               "connectivity job. F5-7b tried to measure whether egress actually gates the image pull and returned "
               "INCONCLUSIVE: all three arms timed out client-side within a 9 ms spread, so nothing was read.",
               "Sandbox 模式仍允許 DNS,那是一個受限的外洩通道 —— 這就是要 DNS Firewall 的原因。"
               "強制走 VPC 部署是 IAM 的工作(在部署角色上加 VPC 條件鍵),不是連線設定的工作。"
               "F5-7b 想量測對外連線是否真的把關 image pull,結果是 INCONCLUSIVE:三個 arm 全部在客戶端逾時,"
               "彼此只差 9 ms,等於什麼都沒讀到。"),
    )


# -- §5.1 streaming vs non-streaming -------------------------------------- #


def streaming(d, t):
    d.diagram(
        t("Output evaluation: the streaming case is the one that surprises people",
          "輸出評估:會讓人意外的是串流那一條"),
        nodes={
            "a1": node(0.10, 1.05, 2.35, 1.05, t("InvokeModel /\nConverse", "InvokeModel /\nConverse"), fill=WHITE),
            "a2": node(2.85, 1.05, 3.05, 1.05, t("Full response assembled", "完整回應組裝完成"), fill=BAND, line=NAVY_L),
            "a3": node(6.30, 1.05, 2.55, 1.05, t("Hop #6 evaluates\nthe whole text", "Hop #6 評估\n整段文字"),
                       fill=GREEN_L, line=GREEN, fg=GREEN),
            "a4": node(9.25, 1.05, 2.80, 1.05, t("User sees all or nothing", "使用者看到全部或什麼都看不到"),
                       fill=WHITE, line=LINE),
            "b1": node(0.10, 3.05, 2.35, 1.05, t("ConverseStream", "ConverseStream"), fill=WHITE),
            "b2": node(2.85, 3.05, 3.05, 1.05, t("Chunks arrive incrementally", "chunk 逐步抵達"), fill=BAND, line=NAVY_L),
            "b3": node(6.30, 3.05, 2.55, 1.05, t("Hop #6 evaluates\nper buffer", "Hop #6 逐 buffer\n評估"),
                       fill=AMBER_L, line=AMBER, fg=AMBER),
            "b4": node(9.25, 3.05, 2.80, 1.05, t("User may see text, then a block", "使用者可能先看到文字,然後被阻擋"),
                       fill=AMBER_L, line=AMBER, fg=AMBER),
        },
        edges=[
            {"a": "a1", "b": "a2"}, {"a": "a2", "b": "a3"}, {"a": "a3", "b": "a4"},
            {"a": "b1", "b": "b2"}, {"a": "b2", "b": "b3"}, {"a": "b3", "b": "b4"},
        ],
        note=t("v1.2's \"Automated Reasoning has no streaming support\" is withdrawn: ConverseStream accepts "
               "guardrailConfig and the SDK models 132 AR assessment paths. The streaming *modes* claim (BP#1) is "
               "left as written — F1-12 returned INCONCLUSIVE, and INCONCLUSIVE licenses no amendment. "
               "Reasoning/chain-of-thought blocks: both placement arms were refused with ValidationException, so "
               "whether they are evaluated is still unmeasured.",
               "v1.2 說「Automated Reasoning 不支援串流」已撤回:ConverseStream 接受 guardrailConfig,"
               "SDK 也定義了 132 條 AR assessment 路徑。串流「模式」那項主張(BP#1)照原文保留 —— "
               "F1-12 是 INCONCLUSIVE,而 INCONCLUSIVE 不授權任何修訂。推理 / chain-of-thought 區塊:"
               "兩種擺放方式都被 ValidationException 拒絕,所以它們是否被評估仍未實測。"),
    )


# -- §6.3 trace tree ------------------------------------------------------- #


def trace_tree(d, t):
    spans = [
        ("AgentCore.Gateway.Initialize", MUTED),
        ("AgentCore.Gateway.NotificationsInitialized", MUTED),
        ("AgentCore.Gateway.InvokeTool", INK),
        ("AgentCore.Gateway.InvokeTool.<toolName>", INK),
        ("AgentCore.Policy.AuthorizeAction", GREEN),
    ]
    nodes = {}
    for i, (name, fg) in enumerate(spans):
        indent = 0.55 if i >= 3 else 0.0
        nodes[f"s{i}"] = node(0.45 + indent, 0.95 + i * 0.72, 7.35 - indent, 0.60, name,
                              fill=WHITE, line=LINE, fg=fg, size=10.5)
    nodes["at"] = node(8.55, 0.95, 3.50, 1.55,
                       t("Present per span: aws.request.id · authorization_decision · determining_policies[] · "
                         "latency_ms / overhead_latency_ms",
                         "每個 span 都有:aws.request.id · authorization_decision · determining_policies[] · "
                         "latency_ms / overhead_latency_ms"),
                       fill=GREEN_L, line=GREEN, fg=GREEN, size=9)
    nodes["ab"] = node(8.55, 2.65, 3.50, 1.10,
                       t("Absent: any guardrail score, ConfidenceScore, ConfidenceThreshold",
                         "沒有:任何 guardrail 分數、ConfidenceScore、ConfidenceThreshold"),
                       fill=RED_L, line=RED, fg=RED, size=9)
    nodes["lg"] = node(8.55, 3.90, 3.50, 0.65, t("Spans lag the request by ≈50 s", "Span 比請求晚約 50 秒"),
                       fill=AMBER_L, line=AMBER, fg=AMBER, size=9)
    d.diagram(
        t("What the trace tree actually contains", "追蹤樹裡實際上有什麼"),
        nodes=nodes,
        groups=[{"x": 0.10, "y": 0.42, "w": 8.05, "h": 4.25,
                 "label": t("One session · 5 operations · InvokeTool pairs 1:1 with AuthorizeAction",
                            "一個 session · 5 種 operation · InvokeTool 與 AuthorizeAction 一對一配對"),
                 "fill": BAND, "line": NAVY_L, "fg": NAVY}],
        note=t("The request-id join is measured, not assumed: 242 of 250 span aws.request.id values (96.8%) match a "
               "client-observed x-amzn-requestid. The 8 that do not are the Initialize spans, whose request ids were "
               "never recorded as trials. Enable CloudWatch Transaction Search first — with tracing off, the same "
               "traffic produced 0 spans.",
               "request-id 的關聯是實測的,不是假設:250 個 span 的 aws.request.id 有 242 個(96.8%)對上客戶端"
               "觀察到的 x-amzn-requestid。對不上的 8 個是 Initialize span,它們的 request id 從未被當作 trial 記錄。"
               "要先啟用 CloudWatch Transaction Search —— 關閉追蹤時,同樣的流量產生 0 個 span。"),
    )


# -- §7.1 threshold tuning workflow --------------------------------------- #


def threshold_tuning(d, t):
    steps = [
        t("1 · Deploy in\nLOG_ONLY\n(shadow mode)", "1 · 以 LOG_ONLY\n部署\n(shadow 模式)"),
        t("2 · Read scores from the\napplication logs\n— not CloudWatch",
          "2 · 從應用程式 log\n讀取分數\n—— 不是 CloudWatch"),
        t("3 · Gate on\nLogOnlyMatches > 0\nbefore reading flips", "3 · 先用\nLogOnlyMatches > 0\n把關,再看 flip"),
        t("4 · Choose the\nthreshold from the\nobserved distribution", "4 · 依觀察到的分佈\n選定門檻值"),
        t("5 · Flip to ACTIVE\nwith an explicit\nvalidationMode", "5 · 切到 ACTIVE,\n並明確給定\nvalidationMode"),
    ]
    xs = row(5, 2.20, 0.26)
    nodes = {}
    for i, (s, x) in enumerate(zip(steps, xs)):
        nodes[f"n{i}"] = node(x, 1.30, 2.20, 1.85, s, fill=WHITE,
                              line=GREEN if i == 4 else NAVY_L, line_w=1.6 if i == 4 else 1.1)
    d.diagram(
        t("Threshold tuning, corrected: the score is in the application logs",
          "門檻值調校(已修正):分數在應用程式 log 裡"),
        nodes=nodes,
        edges=[{"a": f"n{i}", "b": f"n{i+1}"} for i in range(4)] + [
            {"a": "n4", "b": "n0", "side": "bb", "dash": "dash", "color": ORANGE,
             "waypoint": [at(11.29, 4.10), at(1.10, 4.10)],
             "label": t("re-tune as traffic and models change — AWS auto-updates the guardrail models",
                        "隨流量與模型變化重新調校 —— AWS 會自行更新 guardrail 模型"),
             "lcolor": AMBER},
        ],
        note=t("body.policy.guardrailFindings.<policy>.contentFilter[].score, and it is a JSON **string**. "
               "Sub-threshold findings are censored — you see what crossed, not the full distribution. Three "
               "rigorous probes reported the score absent before it was found, because all three surveyed the "
               "surfaces the document named.",
               "body.policy.guardrailFindings.<policy>.contentFilter[].score,而且它是 JSON **字串**。"
               "低於門檻的 finding 會被截除 —— 你看到的是越線的那些,不是完整分佈。在找到它之前有三次嚴謹的探測"
               "都報告「不存在」,因為三次都只調查了文件點名的介面。"),
    )


# -- §9 reference architecture -------------------------------------------- #


def reference_architecture(d, t):
    d.diagram(
        t("Reference architecture: the complete closed loop", "參考架構:完整閉環"),
        nodes={
            "u": node(0.20, 1.05, 1.60, 1.25, t("User", "使用者"), fill=WHITE, line=LINE),
            "g1": node(2.05, 1.05, 1.95, 1.25, t("Gateway\nguardrail\nHop #1", "Gateway\nguardrail\nHop #1"),
                       fill=WHITE, line=BLUE, size=9.5),
            "g2": node(4.25, 1.05, 1.95, 1.25, t("Input\nguardrail\nHop #2", "輸入\nguardrail\nHop #2"),
                       fill=WHITE, line=BLUE, size=9.5),
            "m": node(6.45, 1.05, 2.05, 1.25, t("Model\ninference\nHop #3", "模型\n推論\nHop #3"),
                      fill=BAND, line=NAVY_L, size=9.5),
            "c": node(8.75, 1.05, 1.55, 1.25, t("Cedar\nHop #4", "Cedar\nHop #4"), fill=WHITE, line=NAVY_L, size=9.5),
            "tl": node(10.50, 1.05, 1.55, 1.25, t("Tools\nHop #5", "工具\nHop #5"), fill=WHITE, line=NAVY_L, size=9.5),
            "o": node(0.35, 3.35, 2.40, 1.05, t("Output guardrail — Hop #6", "輸出 guardrail —— Hop #6"),
                      fill=GREEN_L, line=GREEN, fg=GREEN, size=9.5),
            "cw": node(3.05, 3.35, 2.85, 1.05, t("CloudWatch metrics · spans · alarms",
                                                 "CloudWatch 指標 · span · 告警"), fill=WHITE, line=LINE, size=9.5),
            "ev": node(6.20, 3.35, 2.65, 1.05, t("Evaluations\non-demand · batch · online",
                                                 "Evaluations\n即時 · 批次 · 線上"), fill=WHITE, line=LINE, size=9.5),
            "op": node(9.15, 3.35, 2.90, 1.05, t("Optimization recommendations → A/B",
                                                 "Optimization 建議 → A/B"), fill=WHITE, line=LINE, size=9.5),
        },
        groups=[
            {"x": 0.10, "y": 0.50, "w": 11.97, "h": 2.00, "label": t("REQUEST PATH", "請求路徑"),
             "fill": BAND, "line": NAVY_L, "fg": NAVY},
            {"x": 0.10, "y": 2.80, "w": 11.97, "h": 1.75, "label": t("RESPONSE PATH + FEEDBACK LOOP", "回應路徑 + 反饋閉環"),
             "fill": GREEN_L, "line": GREEN, "fg": GREEN},
        ],
        edges=[
            {"a": "u", "b": "g1"}, {"a": "g1", "b": "g2"}, {"a": "g2", "b": "m"},
            {"a": "m", "b": "c"}, {"a": "c", "b": "tl"},
            {"a": "o", "b": "cw"}, {"a": "cw", "b": "ev"}, {"a": "ev", "b": "op"},
            {"a": "op", "b": "o", "side": "bb", "dash": "dash", "color": ORANGE,
             "waypoint": [at(11.22, 4.95), at(1.55, 4.95)]},
        ],
        note=t("Denials do NOT arrive as HTTP 403 on the MCP surface: 120/120 were HTTP 200 with JSON-RPC -32002 "
               "naming the policy id. On the inference surface they are HTTP 403 with a permission_error envelope. "
               "Two surfaces, two shapes — and tools/list denies by returning an empty list with no error at all.",
               "在 MCP 介面上,拒絕不是以 HTTP 403 出現:120/120 都是 HTTP 200 加上點名 policy id 的 "
               "JSON-RPC -32002。在 inference 介面上則是 HTTP 403 加 permission_error 封裝。"
               "兩個介面、兩種形狀 —— 而 tools/list 的拒絕方式是回傳空清單,完全不報錯。"),
    )


ALL = {
    "closed_loop": closed_loop,
    "hop_lifecycle": hop_lifecycle,
    "billing_asymmetry": billing_asymmetry,
    "tier_decision": tier_decision,
    "log_only_precedence": log_only_precedence,
    "containment_boundary": containment_boundary,
    "network_containment": network_containment,
    "streaming": streaming,
    "trace_tree": trace_tree,
    "threshold_tuning": threshold_tuning,
    "reference_architecture": reference_architecture,
}
