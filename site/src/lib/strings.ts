// Every string this SPA authors, in both languages. See `i18n.tsx` for the rule about which strings
// are allowed in here at all — briefly: the chrome and the platform's explanation of itself, never a
// case title, a verdict, an oracle, a register item or any other artifact's own words.
//
// One entry per key, holding `[English, 繁體中文]`. There is no second object to fall out of sync with,
// so a missing translation is a tuple of length one and a type error. Numbers are NOT baked in
// anywhere: they arrive as `{placeholders}` from the payload, which is also why `no_hardcoded_totals`
// in the publish gate covers this file for free.
//
// The Chinese is Traditional (zh-TW), and it deliberately keeps in English the tokens that ARE the
// artifact: AgentCore, Guardrails, `oracle_text`, TRUE/FALSE/INCONCLUSIVE/RECORDED, case identifiers,
// file paths, and the four verdict words. A reader comparing this page against
// `results/phase1/F1-24.json` must be searching for the same string the file contains.

type Entry = readonly [en: string, zhTW: string];

export const STRINGS = {
  // ------------------------------------------------------------------ language and the verbatim rule
  "locale.switch": ["Language", "語言"],
  "payload.verbatim.note": [
    "Quoted artifact text on this page stays in English.",
    "本頁引用的產物原文一律保留英文：判定、oracle_text、案例標題與報告內容是被封印或被推導出來的原始措辭，" +
      "中文改寫會變成第二份說法，而它唯一的出處就只是這個網站。要比對 results/ 底下的檔案，讀者必須搜尋同一個字串。",
  ],

  // ------------------------------------------------------------------ shell
  "app.tagline": [
    "A standing validation of the AgentCore end-to-end security design guidance, derived from its own artifacts at every build.",
    "對 AgentCore 端到端安全設計指引的持續驗證；每一次建置都從它自己的產物重新推導，沒有任何數字是手寫的。",
  ],
  "nav.group.results": ["Results", "結果"],
  "nav.group.method": ["Method", "方法"],
  "nav.group.pipeline": ["Pipeline", "測試管線"],
  "nav.group.audit": ["Audit your design", "審計你的設計"],
  "nav.group.governance": ["Governance", "治理"],
  "nav.census": ["Census", "案例總表"],
  "nav.findings": ["Findings", "發現"],
  "nav.figures": ["Figures", "圖表"],
  "nav.architecture": ["Design diagrams", "設計圖"],
  "nav.method": ["How a verdict is made", "判定是怎麼做出來的"],
  "nav.claims": ["Claim triage", "主張分類"],
  "nav.citations": ["Citation policy", "引用政策"],
  "nav.pipeline": ["Pipeline state", "管線狀態"],
  "nav.audit": ["Submit a design", "送交設計"],
  "nav.report": ["Report and example", "報告與範例"],
  "nav.register": ["Deficiency register", "缺陷登記簿"],
  "nav.provenance": ["Build provenance", "建置來源"],
  "app.build.label": ["build", "建置"],
  "app.build.files": ["{n_inputs} inputs → {n_outputs} files", "{n_inputs} 個輸入 → {n_outputs} 個檔案"],
  "app.build.unavailable": ["build stamp unavailable", "無法取得建置戳記"],
  "app.404.title": ["No such view", "沒有這個頁面"],
  "app.404.body": [
    "Nothing is published at this route. Use the navigation on the left.",
    "這個路徑上沒有發佈任何東西。請使用左側的導覽。",
  ],

  // ------------------------------------------------------------------ census overview
  "ovw.lede": [
    "Every registered case, its verdict, and the claim it was derived from. The counts below are recomputed from the artifacts on every build and are not stored anywhere as a number.",
    "每一個已登記的案例、它的判定，以及它所推導自的那項主張。下面的數字在每一次建置時都會從產物重新計算，" +
      "並沒有以「一個數字」的形式被存放在任何地方。",
  ],
  "ovw.h.denominators": ["Denominators, each with what it counts", "各個分母，以及各自算的是什麼"],
  "ovw.loading.denominators": ["denominators", "分母"],
  "ovw.loading.census": ["the census", "案例總表"],
  "ovw.excl.unmapped": ["not mapped to a claim:", "沒有對應到主張："],
  "ovw.excl.untestable": ["untestable as written:", "照原文無法測試："],
  "ovw.excl.outstanding": ["outstanding:", "尚未完成："],
  "ovw.h.mix": ["Verdict mix", "判定組成"],
  "ovw.publishedVerdicts": ["published verdicts", "已發佈判定"],
  "ovw.unknownVerdict.head": [
    "The payload contains a verdict value this UI does not know about:",
    "這份資料裡有一個本介面不認識的判定值：",
  ],
  "ovw.unknownVerdict": [
    "{head} {values}. It is counted in the total above but has no colour and no column, which means the census is wider than the vocabulary this build was written against.",
    "{head} {values}。它有被算進上面的總數，但沒有顏色也沒有欄位 —— 也就是說，案例總表比這次建置當初據以撰寫的詞彙更寬。",
  ],
  // Named `noRatio`, not `noPassRate`, and the name is load-bearing. `check_site_invariants.py`'s
  // `no_pass_rate` arm reads the SHIPPED BUNDLE, where a key is a string literal like any other — a key
  // spelling the phrase it watches for is an occurrence the arm cannot classify as a denial, so the
  // build fails on a name rather than on a claim. `rep.noRatio` already set this convention.
  "ovw.noRatio.head": [
    "There is no pass rate on this platform.",
    "這個平台上沒有通過率。",
  ],
  "ovw.noRatio.body": [
    "INCONCLUSIVE is a result, not a missing one: it records that the measurement did not establish the claim either way, and it licenses no amendment to the design document. FALSE is not a defect in the study — it is where the guidance did not hold, which is what the work was for. Dividing any of these counts by any of the four denominators above would produce a number none of the definitions support.",
    "INCONCLUSIVE 是一種結果，不是「缺了一個結果」：它記下的是這次測量在任何方向上都沒有建立起那項主張，" +
      "而且它不授權對設計文件做任何修改。FALSE 也不是本研究的缺陷 —— 它標出的正是指引沒有成立的地方，" +
      "而那就是這些工作的目的。把這些數字中的任何一個，除以上面四個分母中的任何一個，" +
      "都會得到一個沒有任何一條定義支撐的數字。",
  ],
  "ovw.h.cases": ["Cases", "案例"],
  "ovw.facet.verdict": ["verdict", "判定"],
  "ovw.facet.searchHint": ["case, title or claim id", "案例、標題或主張編號"],
  "ovw.facet.restrictedOnly": ["citation-restricted only", "只看有引用限制的"],
  "ovw.facet.reset": ["reset", "重設"],
  "ovw.th.case": ["case", "案例"],
  "ovw.th.claims": ["claims", "主張數"],
  "ovw.th.archived": ["archived", "封存數"],
  "ovw.th.citation": ["citation", "引用"],
  "ovw.restricted": ["restricted", "有限制"],
  "ovw.noMatch": [
    "No case matches this filter combination. That is a statement about the filters, not about the register — clear them to see every registered case.",
    "沒有案例符合這組篩選條件。這是關於篩選條件的陳述，不是關於登記簿的陳述 —— 清除它們就能看到每一個已登記的案例。",
  ],
  "ovw.seal.head": ["Oracle registry seal:", "Oracle 註冊表封印："],
  "ovw.seal.ok": ["declared hash matches recomputed", "宣告的雜湊值與重新計算的相符"],
  "ovw.seal.mismatch": ["MISMATCH", "不相符"],
  "ovw.seal.declared": ["declared", "宣告"],
  "ovw.seal.recomputed": ["recomputed", "重算"],
  "ovw.seal.body": [
    "Recomputed over the {n} declared oracle texts, {method}. Each case's oracle was fixed before its measurement ran; a mismatch here would mean an oracle changed after the fact, which is why the build recomputes it rather than trusting the recorded value.",
    "這是對那 {n} 段宣告的 oracle_text 重新計算出來的，方法為 {method}。每個案例的 oracle 都在它的測量開始之前就固定住了；" +
      "這裡出現不相符，會代表某個 oracle 在事後被改過 —— 這就是為什麼建置程序會自己重算，而不是相信記錄下來的那個值。",
  ],

  // ------------------------------------------------------------------ shared components
  "ui.loading": ["Loading {what}…", "正在載入{what}…"],
  "ui.err.missing": [
    "A file this view needs is not in the published payload",
    "這個頁面需要的檔案不在已發佈的資料裡",
  ],
  "ui.err.notJson": [
    "A file this view needs was not served as JSON",
    "這個頁面需要的檔案不是以 JSON 形式提供的",
  ],
  "ui.err.other": ["Could not read a file this view needs", "無法讀取這個頁面需要的檔案"],
  "ui.err.generic": ["This view could not be rendered", "這個頁面無法算繪"],
  "ui.err.note": [
    "This is a defect in the published build, not a state you can navigate out of. The repository markdown and JSON remain the citable form of every number this dashboard shows.",
    "這是已發佈建置的缺陷，不是你能靠切換頁面離開的狀態。此儀表板顯示的每個數字，可引用的形式仍然是版本庫裡的 markdown 與 JSON。",
  ],
  "ui.verdict.none": ["no verdict", "無判定"],
  "ui.verdict.unknown": [
    "not one of the four verdict values — a state recorded by the file itself",
    "不屬於四種判定值之一 —— 這是檔案本身記下的狀態",
  ],
  "ui.restrict.citableAs": ["May be cited as:", "可以被引用為：" ],
  "ui.restrict.notCitableAs": ["May not be cited as:", "不可以被引用為："],
  "ui.restrict.onDisk": ["Verdict recorded on disk:", "檔案裡記錄的判定："],
  "ui.restrict.source": ["source:", "出處："],

  // ------------------------------------------------------------------ citation policy
  "cit.loading": ["the citation policy", "引用政策"],
  "cit.lede": [
    "What these {n} restrictions do is govern what a verdict may be quoted as saying. A verdict is not automatically a citable fact: a TRUE can rest on a measurement too narrow for the sentence it would be quoted in, a RECORDED is an observation whose oracle could not adjudicate it, and an INCONCLUSIVE licenses no amendment in either direction. Each entry below names the artifact that establishes it, and every case page renders its own restrictions from this same file.",
    "這 {n} 條限制管的是：一個判定可以被引用成什麼話。判定不會自動變成可引用的事實 —— 一個 TRUE 可能建立在" +
      "太窄的測量上，撐不起它會被引用的那句話；RECORDED 是一項觀察，它的 oracle 無法對它做裁決；而 INCONCLUSIVE" +
      "在任何方向上都不授權修改文件。下面每一條都指名了建立它的產物，而每個案例頁面也都從這同一個檔案算繪它自己的限制。",
  ],
  "cit.auth.yes": ["This file is authoritative for tooling.", "這個檔案對工具而言具有權威性。"],
  "cit.auth.no": [
    "This file is NOT marked authoritative for tooling.",
    "這個檔案並未被標記為對工具具有權威性。",
  ],
  "cit.schema": [
    "Schema {schema}. Every restriction below is rendered on the case pages it names, from this same file, so the rule and its display cannot drift apart.",
    "結構描述 {schema}。下面每一條限制，都會由這同一個檔案算繪到它指名的案例頁面上，所以規則和它的顯示不可能各自漂移。",
  ],
  "cit.h.cases": ["Restrictions that name specific cases ({n})", "指名了特定案例的限制（{n} 條）"],
  "cit.h.nonCase": [
    "Restrictions that are not about a single case ({n})",
    "不是針對單一案例的限制（{n} 條）",
  ],
  "cit.casesCarrying": ["Cases carrying a restriction:", "帶有限制的案例："],
  "cit.h.asWritten": ["The policy as written", "政策原文"],
  "cit.fileNote": ["The file's own note on this prose:", "檔案自己對這段文字的註記："],

  // ------------------------------------------------------------------ findings
  "fnd.loading": ["findings", "發現"],
  "fnd.lede": [
    "{n} findings, each rendered from the markdown file it is stored as, with the hash of those bytes. A finding is where a verdict's meaning is bounded; the summary is not the finding.",
    "共 {n} 項發現，每一項都直接從它所存放的 markdown 檔案算繪出來，並附上那些位元組的雜湊值。" +
      "一項發現正是判定的意義被劃出邊界的地方；摘要不等於發現本身。",
  ],
  "fnd.noStatus": ["no status recorded", "沒有記錄狀態"],
  "fnd.th.file": ["file", "檔案"],
  "fnd.th.status": ["status", "狀態"],
  "fnd.th.title": ["title", "標題"],
  "fnd.read": ["read the finding", "閱讀這項發現"],
  "fnd.provenance": ["provenance", "來源記錄"],

  // ------------------------------------------------------------------ figures
  "fig.loading": ["figures", "圖表"],
  "fig.lede": [
    "The figures the whitepaper cites, served as the exact PNGs it was written against, each beside the numeric specification it was drawn from.",
    "白皮書引用的那些圖，以白皮書當初據以撰寫的同一批 PNG 原檔提供，每一張旁邊都附上它據以繪製的數值規格。",
  ],
  "fig.fresh.unknown": [
    "NOT VERIFIED — the check did not run",
    "未經驗證 —— 這次建置沒有執行檢查",
  ],
  "fig.fresh.ok": ["numbers verified (rc 0)", "數字已驗證（回傳碼 0）"],
  "fig.fresh.drift": ["numbers drifted (rc {rc})", "數字已漂移（回傳碼 {rc}）"],
  "fig.drift.head": ["What a drift means, concretely:", "漂移具體代表什麼："],
  "fig.drift.body": [
    "a figure on this page shows a number that re-deriving from today's artifacts does not reproduce. The figures are NOT redrawn to make this badge go green — the PNGs are what the whitepaper was written against, and silently re-rendering them would change a published figure to match a later measurement while the paper's sentences still describe the earlier one. The drift is the finding; closing it is a document decision, not a build step.",
    "本頁上有一張圖顯示的數字，用今天的產物重新推導已經無法重現。這些圖不會為了讓這個徽章變綠而重繪 ——" +
      "白皮書當初就是對著這些 PNG 寫的，悄悄重新繪製會讓一張已發佈的圖去符合後來的測量，而論文裡的句子" +
      "描述的仍是先前那次。漂移本身就是發現；要結束它是一個文件層面的決定，不是一個建置步驟。",
  ],
  "fig.redaction.head": [
    "What no gate on this platform can check about these images:",
    "關於這些圖片，本平台上沒有任何閘門能檢查的事：",
  ],
  "fig.absent.badge": ["not present in this build", "這次建置裡沒有這張圖"],
  "fig.alt": [
    "{key} — see the numeric specification below",
    "{key} —— 數值規格見下方",
  ],
  "fig.absent.head": ["This figure was not produced.", "這張圖沒有被產生出來。"],
  "fig.absent.body": [
    "It is listed in the figure manifest, so it is planned rather than forgotten, and its absence is rendered here rather than omitted — a gallery that simply skipped it would show seven figures and imply seven were intended.",
    "它列在圖表清單裡，所以它是被規劃過的、不是被忘記的；而它的缺席在這裡被算繪出來、而不是被省略 ——" +
      "一個直接跳過它的圖庫會顯示七張圖，並暗示本來就只打算做七張。",
  ],
  "fig.absent.register": ["The deficiency register discusses it:", "缺陷登記簿有討論到它："],
  "fig.spec": [
    "numeric specification this figure must reproduce",
    "這張圖必須重現的數值規格",
  ],
  "fig.missing": [
    "The build reports {n} figure(s) missing: {files}.",
    "建置報告有 {n} 張圖缺失：{files}。",
  ],

  // ------------------------------------------------------------------ facets, shared by three views
  "facet.any": ["— any —", "—— 全部 ——"],
  "facet.empty": ["(empty)", "（空白）"],
  "facet.shown": ["{n} shown", "顯示 {n} 筆"],

  // ------------------------------------------------------------------ claim triage
  "clm.loading": ["the claim triage", "主張分類"],
  "clm.lede": [
    "Every unit of the design document the study extracted, its classification, and the case (if any) that measures it. Rendered exactly as the sealed CSV holds it.",
    "本研究從設計文件中抽取出來的每一個單元、它的分類，以及測量它的案例（如果有的話）。完全按照被封印的 CSV 所存放的樣子算繪。",
  ],
  "clm.card.rows": ["triaged rows", "已分類的列數"],
  "clm.card.rows.def": [
    "Every row of the sealed triage CSV, including the excluded ones.",
    "被封印的分類 CSV 的每一列，包含被排除的那些。",
  ],
  "clm.card.named": ["rows naming at least one case", "指名了至少一個案例的列數"],
  "clm.card.named.def": [
    "The `cases` cell is non-empty. Counted from the cell as text, so a row naming two cases counts once here — the census counts the other direction.",
    "`cases` 欄位不是空的。這是把該欄位當作文字來計數，所以一列指名兩個案例在這裡只算一次 —— 案例總表是從另一個方向計數的。",
  ],
  "clm.card.cases": ["cases with at least one claim", "至少對應到一項主張的案例數"],
  "clm.card.cases.def": [
    "Derived by the build from these same rows, and the basis of the claim-mapped denominator on the census page.",
    "由建置程序從這同一批列推導出來，也是案例總表頁面上「已對應主張」那個分母的依據。",
  ],
  "clm.facet.class": ["class", "分類"],
  "clm.facet.rule": ["rule", "規則"],
  "clm.facet.mapping": ["case mapping", "案例對應"],
  "clm.facet.mapped": ["mapped to a case", "已對應到案例"],
  "clm.facet.unmapped": ["no case named", "沒有指名案例"],
  "clm.facet.search": ["search", "搜尋"],
  "clm.facet.searchHint": ["claim id, text, anchor", "主張編號、內文、錨點"],
  "clm.splitNote": [
    "The `cases` column is linked by splitting the raw cell on whitespace for navigation only; the cell itself is shown unmodified in every other respect, and the value the study joins on is the string, not this split.",
    "`cases` 這一欄是把原始欄位以空白切開來做成連結，純粹為了導覽用；除此之外欄位本身未經任何修改，" +
      "而本研究實際據以做關聯的值是那整個字串，不是這個切分結果。",
  ],

  // ------------------------------------------------------------------ build provenance
  "prv.loading": ["the build manifest", "建置清單"],
  "prv.lede": [
    "This payload was produced by one program from one tree, and both are named here by hash. Nothing on this site was typed; every number was derived, and this is the record of what it was derived from.",
    "這份資料是由一支程式、從一份原始碼樹產生出來的，兩者在這裡都以雜湊值指名。這個網站上沒有任何東西是手打的；" +
      "每一個數字都是推導出來的，而這一頁就是「從什麼推導出來」的記錄。",
  ],
  "prv.filter": ["filter {what}", "篩選{what}"],
  "prv.pathHint": ["path fragment", "路徑片段"],
  "prv.shownOf": ["{n} of {total} shown", "顯示 {n} / {total} 筆"],
  "prv.th.path": ["path", "路徑"],
  "prv.th.derivedFrom": ["derived from", "推導來源"],
  "prv.what.inputs": ["inputs", "輸入"],
  "prv.what.outputs": ["outputs", "輸出"],
  "prv.nInputs": ["{n} input(s)", "{n} 個輸入"],
  "prv.disagrees": ["The manifest does not agree with itself.", "這份清單和它自己不一致。"],
  "prv.agrees": ["The manifest agrees with itself.", "這份清單和它自己一致。"],
  "prv.agrees.detail": [
    "{outputs} hashed outputs plus MANIFEST.json equals the declared {nOutputs}; {inputs} hashed inputs equals the declared {nInputs}; every hashed output has a provenance entry and every provenance entry a hash; no output claims to have been derived from nothing. Checked in the browser, from the file, on load.",
    "{outputs} 個有雜湊的輸出加上 MANIFEST.json，等於它宣告的 {nOutputs}；{inputs} 個有雜湊的輸入，" +
      "等於它宣告的 {nInputs}；每個有雜湊的輸出都有一筆來源記錄，每筆來源記錄也都有雜湊；" +
      "沒有任何輸出聲稱自己不是從任何東西推導出來的。這些是在瀏覽器裡、載入時、直接對著檔案檢查的。",
  ],
  "prv.bad.outputCount": [
    "The manifest declares {declared} outputs but hashes {hashed}; those differ by {diff}, and only MANIFEST.json is expected to be unhashed.",
    "清單宣告有 {declared} 個輸出，但只雜湊了 {hashed} 個；相差 {diff} 個，而預期沒有雜湊的只有 MANIFEST.json 一個。",
  ],
  "prv.bad.inputCount": [
    "The manifest declares {declared} inputs but hashes {hashed}.",
    "清單宣告有 {declared} 個輸入，但只雜湊了 {hashed} 個。",
  ],
  "prv.bad.noProvenance": [
    "{n} hashed output(s) have no provenance entry: {files}.",
    "有 {n} 個有雜湊的輸出沒有來源記錄：{files}。",
  ],
  "prv.bad.noHash": [
    "{n} provenance entr(ies) name a file that was not hashed: {files}.",
    "有 {n} 筆來源記錄指名了沒有被雜湊的檔案：{files}。",
  ],
  "prv.bad.noInputs": [
    "{n} output(s) declare no inputs at all: {files}. An output derived from nothing is either a constant the build invented or a read it did not record.",
    "有 {n} 個輸出完全沒有宣告任何輸入：{files}。一個不是從任何東西推導出來的輸出，" +
      "要嘛是建置程序自己憑空生出來的常數，要嘛是它讀了卻沒記下來的一次讀取。",
  ],
  "prv.kv.stamp": ["build stamp", "建置戳記"],
  "prv.kv.producedBy": ["produced by", "產生者"],
  "prv.kv.inputsRead": ["inputs read", "讀取的輸入數"],
  "prv.kv.outputsWritten": ["outputs written", "寫出的輸出數"],
  "prv.kv.howToVerify": ["how to verify one", "怎麼自己驗一個"],
  "prv.kv.howToVerify.body": [
    "{cmd} — for an input, against the repo tree at that stamp; for an output, against the JSON this site fetched. Both hashes are below.",
    "{cmd} —— 輸入就對著那個戳記當時的版本庫樹來驗；輸出就對著這個網站抓下來的 JSON 來驗。兩種雜湊值都在下面。",
  ],
  "prv.h.inputs": ["Inputs — the bytes the build read ({n})", "輸入 —— 建置程序讀進去的位元組（{n} 個）"],
  "prv.inputs.note": [
    "These are repository paths. A hash here proves which revision of a sealed artifact this payload was built from, which is the only way to tell a re-derivation from a re-authoring.",
    "這些是版本庫裡的路徑。這裡的雜湊值證明了這份資料是從被封印產物的哪一個版本建置出來的 ——" +
      "那也是唯一能分辨「重新推導」和「重新撰寫」的辦法。",
  ],
  "prv.unusedInputs": [
    "{n} input(s) were hashed but are not named by any output's provenance: {files}. That is expected for files read to be verified rather than to be rendered — a seal is read to check it, not to publish it — and it is listed rather than filtered so the distinction stays visible.",
    "有 {n} 個輸入被雜湊了，但沒有被任何輸出的來源記錄指名：{files}。對於「讀進來是為了驗證、不是為了算繪」" +
      "的檔案而言，這是預期的 —— 封印是被讀來檢查的，不是被讀來發佈的 —— 這裡把它列出來而不是過濾掉，" +
      "是為了讓這個區別保持看得見。",
  ],
  "prv.h.outputs": [
    "Outputs — the bytes this site serves ({n})",
    "輸出 —— 這個網站實際提供的位元組（{n} 個）",
  ],
  "prv.outputs.note": [
    "Each output's provenance is the set of inputs whose bytes it was derived from. MANIFEST.json is the one output with no hash of its own, because a file cannot contain its own digest.",
    "每個輸出的來源記錄，就是它的位元組據以推導出來的那組輸入。MANIFEST.json 是唯一沒有自己雜湊值的輸出，" +
      "因為一個檔案不可能裝得下自己的摘要值。",
  ],

  // ------------------------------------------------------------------ audit your own design
  //
  // The refusal sentences are the ones `lib/audit.ts` names by key. They are instructions about what to
  // type next, not diagnostics, which is why they are in here at all.
  "aud.refuse.space": [
    "Not composed: a space is not something a repository URL or path contains, and pasting it into a shell command would change what that command does. The template is shown unmodified.",
    "沒有組出命令：空白不是版本庫網址或路徑裡會出現的東西，把它貼進 shell 命令會改變那個命令做的事。下面顯示的是未經修改的樣板。",
  ],
  "aud.refuse.char": [
    "Not composed: the character {ch} is not something a repository URL or path contains, and pasting it into a shell command would change what that command does. The template is shown unmodified.",
    "沒有組出命令：{ch} 這個字元不是版本庫網址或路徑裡會出現的東西，把它貼進 shell 命令會改變那個命令做的事。下面顯示的是未經修改的樣板。",
  ],
  "aud.refuse.hyphen": [
    "Not composed: a value beginning with a hyphen would be read by the tool as an option rather than as your repository. The template is shown unmodified.",
    "沒有組出命令：以連字號開頭的值，會被工具讀成一個選項、而不是你的版本庫。下面顯示的是未經修改的樣板。",
  ],
  "aud.refuse.date": [
    "Not composed: the report date must be an ISO day, `YYYY-MM-DD`. It is optional — leave it empty and the flag is dropped entirely, which is the deterministic form.",
    "沒有組出命令：報告日期必須是 ISO 格式的日期 `YYYY-MM-DD`。這個欄位是選填的 —— 留空的話這個參數會整個被拿掉，那才是可決定性的形式。",
  ],
  "aud.rep.notJson": ["Not JSON: {why}", "不是 JSON：{why}"],
  "aud.rep.notObject": [
    "The file parsed, but its top level is not a JSON object.",
    "這個檔案解析成功了，但它的最上層不是一個 JSON 物件。",
  ],
  "aud.rep.wrongSchema": [
    "This file declares schema {got}, not {want}. It may be an inventory.json — the parser's output — rather than a report.json, or a report from a different version of the tool. Nothing is rendered from it, because a report shape this page does not understand would show empty sections, and empty sections read as \"nothing found\".",
    "這個檔案宣告的結構描述是 {got}，不是 {want}。它可能是 inventory.json（剖析器的輸出）而不是 report.json，" +
      "或者是另一個版本的工具產生的報告。這個頁面不會從它算繪任何東西 —— 因為一個本頁不理解的報告結構" +
      "會顯示成一堆空白區段，而空白區段會被讀成「什麼都沒找到」。",
  ],
  "aud.rep.noArrays": [
    "The file declares the right schema but carries no `controls` or `recommendations` array, so there is nothing in it this page could render.",
    "這個檔案宣告了正確的結構描述，但裡面沒有 `controls` 或 `recommendations` 陣列，所以本頁沒有任何東西可以算繪。",
  ],
  "aud.loading": ["the audit tooling", "審計工具"],
  "aud.copy": ["Copy the {n} commands", "複製這 {n} 行命令"],
  "aud.copy.done": ["copied", "已複製"],
  "aud.copy.refused": [
    "the browser refused clipboard access — select the text below instead",
    "瀏覽器拒絕了剪貼簿存取 —— 請改用選取下面的文字",
  ],
  "aud.copy.orSelect": ["or select it below", "或者直接選取下面的文字"],
  "aud.title": ["Audit a design of your own", "審計你自己的設計"],
  "aud.lede": [
    "This study measured {n} controls of an AgentCore deployment. Two programs in the repository read a repository's infrastructure-as-code, report which of those {n} it declares, and state — per control, citing the case — what was measured about the value it declares. Everything runs on your machine.",
    "本研究測量了一套 AgentCore 部署裡的 {n} 項控制。版本庫裡有兩支程式會去讀一個版本庫的基礎設施即程式碼，" +
      "報告這 {n} 項裡它宣告了哪些，並且逐項指名案例，說明對它所宣告的那個值曾經測量到什麼。全部都在你自己的機器上跑。",
  ],
  "aud.h.willNotDo": ["What this page will not do", "這個頁面不會做的事"],
  "aud.h.point": ["Point the tools at your repository", "把工具指向你的版本庫"],
  "aud.point.body": [
    "Fill either field and the commands below change. They are the commands as {parse} and {report} define them, read from the payload rather than typed into this page. Nothing you enter is sent anywhere: there is no endpoint on this site that accepts a request body.",
    "填任一個欄位，下面的命令就會跟著變。這些命令是 {parse} 和 {report} 自己定義的，從資料裡讀進來的、" +
      "不是打在這個頁面裡的。你輸入的任何東西都不會被送到任何地方：這個網站上沒有任何一個端點會接受請求主體。",
  ],
  "aud.field.repo": [
    "Your repository — a git URL or a local path",
    "你的版本庫 —— 一個 git 網址或一個本機路徑",
  ],
  "aud.field.date": ["Report date (optional)", "報告日期（選填）"],
  "aud.field.datePlaceholder": [
    "YYYY-MM-DD — leave empty for a byte-identical report",
    "YYYY-MM-DD —— 留空可以得到位元組完全相同的報告",
  ],
  "aud.noCase": ["no case measured this", "沒有案例測量過這一項"],
  "aud.typeHint": [
    "on a resource whose type contains: {hints}",
    "在型別包含以下字樣的資源上：{hints}",
  ],
  "aud.model": ["model: {model}", "服務模型：{model}"],
  "aud.afterCommands": [
    "The second command writes {inventory} — what the parser saw, with a file and line for every site, and no reference to this study. The third joins it to the study and writes the report as both JSON and Markdown. {example}, which is that output for a synthetic submission in this repository, produced by the same two programs at build time. The report view will also render a {report} you produce yourself, without uploading it.",
    "第二行命令會寫出 {inventory} —— 剖析器看到的東西，每一處都附上檔案與行號，而且完全沒有提到本研究。" +
      "第三行會把它跟本研究關聯起來，並且同時輸出 JSON 與 Markdown 兩種格式的報告。{example}：" +
      "那是本版本庫裡一份合成的送交案例的輸出，由同樣這兩支程式在建置時產生。報告頁面也可以算繪你自己產生的 {report}，" +
      "而且不需要上傳。",
  ],
  "aud.afterCommands.exampleLink": ["See the worked example", "看一份做好的範例"],
  "aud.h.canLookFor": ["What this study can look for", "本研究能夠找的東西"],
  "aud.canLookFor.body": [
    "The property paths are shown because they are the whole of what a DECLARED result rests on: a control is found when a template carries that path, and reported NOT_DECLARED when the parsed files do not — which is never evidence that the control is absent from a system. Paths are lower-cased and dot-joined, because a template may spell them in camelCase or PascalCase.",
    "這裡把屬性路徑列出來，是因為一個 DECLARED 的結果全部就只建立在它們之上：樣板裡帶有那個路徑，就算找到這項控制；" +
      "被剖析的檔案裡沒有，就報告 NOT_DECLARED —— 而那永遠不能當作「這個系統裡沒有這項控制」的證據。" +
      "路徑都轉成小寫並以點連接，因為樣板可能用 camelCase 或 PascalCase 來拼它們。",
  ],
  "aud.th.control": ["Control", "控制項"],
  "aud.th.whatItIs": ["What it is", "它是什麼"],
  "aud.th.established": ["What this study established", "本研究建立了什麼"],
  "aud.th.cases": ["Cases", "案例"],
  "aud.th.detectedBy": ["Detected by", "偵測依據"],
  "aud.h.coverage": [
    "Coverage of the {n} controls, by what was established",
    "這 {n} 項控制的涵蓋情況，依「建立了什麼」分類",
  ],
  "aud.noDenominator": [
    "These counts do not sum to {n} and no denominator over them means anything: a single control can carry a {t} finding for one declared value and a {f} finding for another, and it is counted under both. For the same reason there is no pass rate on this page, or on any other here.",
    "這些數字加起來不等於 {n}，而且在它們之上算任何分母都沒有意義：同一項控制可以對某個宣告的值有一筆 {t} 的發現，" +
      "又對另一個值有一筆 {f} 的發現，於是它在兩邊都被算了一次。基於同樣的道理，這一頁沒有通過率，其他任何一頁也沒有。",
  ],
  "aud.h.unverifiable": [
    "Paths this study names but cannot verify against the service model",
    "本研究指名了、但無法對照服務模型驗證的路徑",
  ],
  "aud.unverifiable.body": [
    "Detection paths were checked against the pinned instrument — {instrument}, derived {derived}. The paths below are matched anyway, and they are listed here because the reason they cannot be checked is itself worth knowing before you trust a result that rests on one.",
    "偵測路徑是對照那個被釘住的測量儀器檢查的 —— {instrument}，推導日期 {derived}。下面這些路徑照樣會被比對，" +
      "把它們列在這裡，是因為「為什麼它們沒辦法被檢查」這件事本身，就值得在你相信一個建立在它之上的結果之前先知道。",
  ],
  "aud.th.path": ["Path", "路徑"],
  "aud.th.whyUnverifiable": [
    "Why it cannot be verified against an API model",
    "為什麼它無法對照 API 模型驗證",
  ],

  // ------------------------------------------------------------------ the audit report
  "rep.loading": ["the audit report", "審計報告"],
  "rep.title": ["Audit report", "審計報告"],
  "rep.unresolved": ["unresolved", "無法解析"],
  "rep.scope": ["Scope:", "適用範圍："],
  "rep.neverExamined": [
    "Why this study never examined it:",
    "為什麼本研究從未檢查過這一項：",
  ],
  "rep.doesNotProve": ["What it does not prove:", "它沒有證明的是："],
  "rep.noLimitStated": [
    "This case file states no limit on its own verdict, so treat the verdict as narrower than it reads.",
    "這個案例檔案沒有對自己的判定說出任何限制，所以請把這個判定當作比它字面上看起來更窄來理解。",
  ],
  "rep.th.declaredValue": ["Declared value", "宣告的值"],
  "rep.noValueRead": [
    "no value read — this control is detected by the presence of its properties, not by a value",
    "沒有讀到值 —— 這項控制是靠它的屬性存在來偵測的，不是靠某個值",
  ],
  "rep.disagreement.head": [
    "Two different values are declared across your files:",
    "你的檔案之間宣告了兩個不同的值：",
  ],
  "rep.disagreement": [
    "{head} {values}. Every measurement below is stated per value, because a staging template that disagrees with production is a real state and not a parse error.",
    "{head} {values}。下面每一項測量都是逐個值分別陳述的 —— 因為一份與生產環境不一致的預備環境樣板，" +
      "是一個真實存在的狀態，不是一個剖析錯誤。",
  ],
  "rep.outsideEnum": [
    "Value(s) outside the vocabulary this control knows: {values}. No measurement covers them.",
    "有值落在這項控制所認識的詞彙之外：{values}。沒有任何測量涵蓋它們。",
  ],
  "rep.th.whereFound": ["Where it was found", "在哪裡找到的"],
  "rep.th.whyReads": ["Why this reads {o}", "為什麼這裡顯示 {o}"],
  "rep.noMeasurement": [
    "This study has no measurement that applies to what your files declare here. That is a statement about this study's coverage, not about your deployment.",
    "對於你的檔案在這裡所宣告的東西，本研究沒有任何適用的測量。這是關於本研究涵蓋範圍的陳述，不是關於你的部署的陳述。",
  ],
  "rep.h.headline": ["Headline", "總覽數字"],
  "rep.card.covers": ["controls this study can speak to", "本研究說得上話的控制項"],
  "rep.card.youDeclare": ["of them your files declare", "其中你的檔案宣告了"],
  "rep.card.measured": ["declared, and measured by this study", "已宣告，而且本研究測量過"],
  "rep.card.measured.def": [
    "The only bucket where a finding rests on a measurement of the value you declare.",
    "只有這一格裡的發現，是建立在對你所宣告的那個值的測量之上。",
  ],
  "rep.card.didNotHold": [
    "declared, and the guidance did NOT hold",
    "已宣告，而且指引並未成立",
  ],
  "rep.card.didNotHold.def": [
    "Measured, and the documented behaviour was not observed. These are the findings.",
    "測量過了，而文件所記載的行為並未被觀察到。這些就是「發現」。",
  ],
  "rep.card.neverExamined": ["declared, never examined here", "已宣告，但這裡從未檢查過"],
  "rep.card.neverExamined.def": [
    "Not a clean result. Nothing was tested, so nothing is claimed.",
    "這不是一個「乾淨」的結果。什麼都沒測，所以什麼都沒主張。",
  ],
  "rep.card.noCoverage": [
    "declared in a state no measurement covers",
    "宣告在一個沒有任何測量涵蓋的狀態上",
  ],
  "rep.card.noCoverage.def": [
    "The control was measured, but not at the value your files declare.",
    "這項控制被測量過，但不是在你的檔案所宣告的那個值上。",
  ],
  "rep.card.notSeen": ["not seen in the parsed files", "在被剖析的檔案裡沒看到"],
  "rep.card.notSeen.def": [
    "NOT_DECLARED means the parser did not find it. It is not evidence the control is absent.",
    "NOT_DECLARED 的意思是剖析器沒有找到它。它不是「這項控制不存在」的證據。",
  ],
  "rep.noRatio": ["Why there is no pass rate here:", "為什麼這裡沒有通過率："],
  "rep.h.writtenAgainst": [
    "What the report was written against",
    "這份報告是對著什麼寫出來的",
  ],
  "rep.th.reportDate": ["Report date", "報告日期"],
  "rep.noClock": [
    "none — the tool reads no clock, so the report is byte-identical on re-run",
    "無 —— 這個工具不讀任何時鐘，所以重跑一次會得到位元組完全相同的報告",
  ],
  "rep.th.evidenceThrough": ["Evidence through at least", "證據至少涵蓋到"],
  "rep.notDerivable": ["not derivable", "無法推導"],
  "rep.th.registeredPublished": [
    "Cases registered / verdicts published",
    "已登記案例 / 已發佈判定",
  ],
  "rep.th.verdictMix": [
    "Verdict mix behind every line below",
    "下面每一行背後的判定組成",
  ],
  "rep.th.resourcesParsed": ["Resources parsed", "已剖析的資源數"],
  "rep.h.recommendations": ["Recommendations", "建議"],
  "rep.recommendations.lede": [
    "{n} recommendation(s), each licensed by a citable verdict named beside it. A recommendation with no case is not written at all.",
    "共 {n} 項建議，每一項都由旁邊指名的、可引用的判定所授權。沒有案例支撐的建議，根本不會被寫出來。",
  ],
  "rep.th.whatToDo": ["What to do, and why", "該做什麼，以及為什麼"],
  "rep.th.licensedBy": ["Licensed by", "授權來源"],
  "rep.th.where": ["Where", "位置"],
  "rep.h.withheld": [
    "Recommendations deliberately withheld",
    "刻意不給的建議",
  ],
  "rep.withheld.lede": [
    "{n} control(s) where something was declared and this study declines to advise. Listed rather than omitted: an absent row would read as a control with nothing to say about it.",
    "有 {n} 項控制，你宣告了東西、但本研究拒絕給建議。這裡是列出來、而不是省略：" +
      "一列不存在，會被讀成「這項控制沒什麼可說的」。",
  ],
  "rep.th.whyWithheld": ["Why nothing is recommended", "為什麼不給任何建議"],
  "rep.h.controlByControl": ["Control by control", "逐項控制"],
  "rep.h.caveats": [
    "Caveats that apply to every line above",
    "適用於上面每一行的保留條件",
  ],
  "rep.lede.own": [
    "Rendering {name}, decoded in this browser. It was not uploaded: selecting it produced no network request, which you can confirm in your browser's network panel.",
    "正在算繪 {name}，它是在這個瀏覽器裡解碼的。它沒有被上傳：選取它並沒有產生任何網路請求，" +
      "你可以在瀏覽器的網路面板裡自己確認。",
  ],
  "rep.lede.example": [
    "The worked example, produced at build time by running {parse} and {report} over {submission} — the same two programs the {intake} composes commands for, run over {n} checked-in files. Nothing here was written by hand.",
    "這是一份做好的範例，在建置時以 {parse} 和 {report} 對 {submission} 執行而產生 —— " +
      "就是 {intake} 幫你組出命令的同樣那兩支程式，跑在 {n} 個簽入版本庫的檔案上。這裡沒有任何東西是手寫的。",
  ],
  "rep.intakeLink": ["intake page", "送交頁面"],
  "rep.synthetic": ["This submission is synthetic.", "這份送交案例是合成的。"],
  "rep.h.ownReport": ["Render a report of your own", "算繪你自己的報告"],
  "rep.ownReport.body": [
    "Run the three commands from the {intake} and select the {report} they wrote. The file is decoded with {reader} in this tab; this site has no endpoint that accepts a request body, so there is nowhere for it to be sent even if a future version tried.",
    "執行 {intake} 上的那三行命令，然後選取它們寫出來的 {report}。這個檔案是在這個分頁裡用 {reader} 解碼的；" +
      "這個網站沒有任何端點會接受請求主體，所以就算未來某個版本想送，也沒有地方可以送。",
  ],
  "rep.field.file": ["Your report.json", "你的 report.json"],
  "rep.readFailed": ["Could not read the file: {why}", "無法讀取這個檔案：{why}"],
  "rep.backToExample": ["Back to the worked example", "回到做好的範例"],
  "rep.dl.md": ["Download this report as Markdown", "以 Markdown 下載這份報告"],
  "rep.dl.json": ["Download it as JSON", "以 JSON 下載"],
  "rep.dl.inventory": [
    "Download the inventory the parser wrote",
    "下載剖析器寫出來的 inventory",
  ],
  "rep.h.markdown": [
    "The Markdown the tool wrote, verbatim",
    "工具寫出來的 Markdown 原文",
  ],
  "rep.markdown.body": [
    "Rendered as text rather than as formatted Markdown on purpose: this is the deliverable a reader hands to a colleague, and the point of showing it here is that it is the same bytes, not a prettier version of them.",
    "刻意以純文字、而不是排版後的 Markdown 呈現：這是讀者會交給同事的那份交付物，" +
      "把它放在這裡的意義就在於它是同樣的位元組，不是一個比較漂亮的版本。",
  ],
  "rep.markdown.lines": ["{n} lines of Markdown", "{n} 行 Markdown"],

  // ------------------------------------------------------------------ pipeline state
  "pip.loading": ["the pipeline state", "管線狀態"],
  "pip.never": ["never", "從未"],
  "pip.lede": [
    "Derived at build time, as of {day}.",
    "在建置時推導出來，時點為 {day}。",
  ],
  "pip.asOfWarn": [
    "{n} case(s) carry an observation day AFTER the day this payload was stamped, which means this build was stamped for an earlier day than the evidence it read. Ages below are measured from the stamp and are floors, not exact figures: {cases}",
    "有 {n} 個案例帶有的觀察日期，晚於這份資料被戳記的那一天，也就是說這次建置被戳記的日期，早於它所讀到的證據。" +
      "下面的天數都是從戳記算起的，是下限、不是精確值：{cases}",
  ],
  "pip.notSchedulable": [
    "Not schedulable, so it carries no cadence and can never be reported stale — nothing on this page should be read as pressure to re-run it.",
    "不可排程，所以它沒有週期，也永遠不會被報告為過期 —— 本頁上任何東西都不該被讀成「該重跑它了」的壓力。",
  ],
  "pip.replReq": [
    "What a replication of this family must hold fixed:",
    "要複現這個家族，必須固定住的東西：",
  ],
  "pip.whyCadence": ["Why this cadence:", "為什麼是這個週期："],
  "pip.th.disagreement": ["In disagreement with an archive", "與封存記錄不一致"],
  "pip.th.owesSecond": [
    "Owes a second occasion (has a verdict, nothing archived)",
    "還欠第二次觀察（已有判定，但沒有任何封存）",
  ],
  "pip.th.dayUnknown": [
    "Observation day not derivable from the record",
    "無法從記錄推導出觀察日期",
  ],
  "pip.th.noDay": ["No observed day at all", "完全沒有觀察日期"],
  "pip.h.disagree": [
    "Where the live verdict and an archived one disagree",
    "現行判定與封存判定不一致的地方",
  ],
  "pip.disagree.body": [
    "{n} of {total} registered case(s). A disagreement is a finding: it means the platform re-measured something and got a different answer, which is the outcome a replication exists to be able to report.",
    "{total} 個已登記案例中的 {n} 個。不一致本身就是一項發現：它代表這個平台重新測量了某件事、得到不一樣的答案，" +
      "而那正是「複現」這件事存在的目的 —— 為了能夠報告它。",
  ],
  "pip.th.case": ["Case", "案例"],
  "pip.th.archivedDays": ["Archived days", "封存的日期"],
  "pip.th.archivedVerdicts": ["Archived verdict(s) that differ", "不同的封存判定"],
  "pip.h.byFamily": ["By family", "依家族"],
  "pip.byFamily.note": [
    "A row is a set of cases, not a job: there is no percentage and no completion figure here. Click a row for the cases behind its numbers. The cadences and the sentences inside a row are authored, in {file} — read from the payload rather than written into this page, so a page that quoted a file it could not name would say so here; every number is derived.",
    "一列代表一組案例，不是一個工作項目：這裡沒有百分比，也沒有任何完成度數字。點一列可以看到它的數字背後是哪些案例。" +
      "週期和列內的那些句子是人寫的，寫在 {file} 裡 —— 是從資料讀進來的、不是寫死在這個頁面裡的，" +
      "所以一個引用了自己叫不出名字的檔案的頁面，會在這裡說出來；而每一個數字都是推導出來的。",
  ],
  "pip.byFamily.unstated": ["an unstated file", "一個沒有指名的檔案"],
  "pip.th.family": ["Family", "家族"],
  "pip.th.measures": ["What it measures", "它測量什麼"],
  "pip.th.state": ["State", "狀態"],
  "pip.th.cadence": ["Cadence (days)", "週期（天）"],
  "pip.th.lastObserved": ["Last observed", "最後一次觀察"],
  "pip.th.age": ["Age (days)", "距今（天）"],
  "pip.th.cases": ["Cases", "案例數"],
  "pip.th.withVerdict": ["With a verdict", "有判定"],
  "pip.th.noObservedDay": ["No observed day", "沒有觀察日期"],
  "pip.th.twoArchived": ["≥2 archived days", "封存日期 ≥2 天"],
  "pip.th.disagreeing": ["Disagreeing", "不一致"],
  "pip.h.replCounts": ["What the replication counts mean", "這些複現數字的意思"],
  "pip.card.twoArchived": [
    "case(s) with two or more archived days",
    "有兩個以上封存日期的案例",
  ],
  "pip.card.twoArchived.def": [
    "Counted from the archive alone, and non-exclusively: today every one of these is also a disagreement, so the agreeing bucket below reads 0.",
    "只從封存記錄計數，而且各類別並不互斥：到今天為止，這裡每一個同時也是一筆不一致，所以下面「一致」那一格是 0。",
  ],
  "pip.card.oneArchived": [
    "case(s) with exactly one archived prior day",
    "只有一個先前封存日期的案例",
  ],
  "pip.card.noArchived": ["case(s) with nothing archived", "完全沒有封存記錄的案例"],
  "pip.card.noArchived.def": [
    "No prior occasion is established for these, whatever their verdict.",
    "不管它們的判定是什麼，這些案例都沒有建立起「先前曾有一次觀察」這件事。",
  ],
  "pip.card.noObservedDay": [
    "case(s) whose observation day is not derivable",
    "無法推導出觀察日期的案例",
  ],
  "pip.card.noObservedDay.def": [
    "The verdict files carry no machine-readable day stamp in a fixed place, so for these the family reads NOT OBSERVED rather than \"within cadence\". Under-claiming freshness is recoverable by reading the case; over-claiming it is what tells somebody a control was checked last week.",
    "判定檔案沒有在固定位置放一個機器可讀的日期戳記，所以對這些案例來說，家族狀態顯示的是 NOT OBSERVED，" +
      "而不是「在週期內」。把新鮮度說得比實際低，讀者去讀案例就能補回來；把它說得比實際高，" +
      "才是會讓人以為某個控制上週剛檢查過的那種錯。",
  ],

  // ------------------------------------------------------------------ one case, whole chain
  //
  // The strictest boundary on the platform runs through this page. Everything the CASE says about itself
  // is quoted: the title, the sealed `oracle_text`, the `instrument`, the caveat, `verdict_reading` and
  // `verdict_rule`, each guard's `test` and `why`, `blockers_are_not_exhaustive`, and the record's own
  // field names. What is translated is only the frame — the section headings, the column headings, and
  // this platform's own statements about what an absence means.

  "cs.loading": ["case {id}", "案例 {id}"],
  "cs.none": ["none", "無"],
  "cs.any.items": ["{n} item(s)", "{n} 個項目"],
  "cs.any.object": ["object", "物件"],
  "cs.recordLabel": ["record", "記錄"],
  "cs.back": ["← back to the census", "← 回到案例總表"],

  "cs.chip.family": ["family", "族群"],
  "cs.chip.tier": ["tier", "層級"],
  "cs.chip.kind": ["kind", "判準種類"],
  "cs.chip.sealed": ["oracle sealed", "判準已封存"],
  "cs.netPos": [
    "This case is network-position sensitive.",
    "這個案例對網路位置敏感。",
  ],

  "cs.h.oracle": [
    "Sealed oracle — the exact text this verdict answers",
    "封存的判準 —— 這個判定所回答的那一段原文",
  ],
  "cs.oracle.note": [
    "Quoted verbatim from the sealed oracle registry, whose hash is recomputed at every build. Not paraphrased and not shortened: the wording is the claim, and the verdict is an answer to this wording rather than to a summary of it. It is shown in English in both languages for the same reason it is not shortened.",
    "這段文字是從封存的判準登記表逐字引用的，那份登記表的雜湊值在每一次建置時都會重新計算。" +
      "沒有改寫，也沒有縮短：字句本身就是那條主張，而判定回答的是這些字句，不是它的摘要。" +
      "它在兩種語言下都以英文顯示，理由和它沒有被縮短是同一個。",
  ],
  "cs.h.instrument": [
    "Instrument — how the claim was put to a measurement",
    "儀器 —— 這條主張是怎麼被拿去測量的",
  ],
  "cs.h.adjudication": ["Adjudication", "裁決"],
  "cs.h.howRead": ["How the verdict was read", "這個判定是怎麼被讀出來的"],
  "cs.h.doesNotProve": ["What this verdict does not prove", "這個判定不能證明什麼"],
  "cs.h.guards": [
    "Guards — the conditions that had to hold for the measurement to count",
    "防護條件 —— 這次測量要算數，就必須成立的那些條件",
  ],
  "cs.h.blockers": ["Blockers", "阻礙"],
  "cs.h.spanJoin": [
    "Span join — one tick per recovered request",
    "Span 對接 —— 每一個被取回的請求畫一條刻度",
  ],
  "cs.h.replication": ["Replication", "重現"],
  "cs.h.resources": ["Resources and run identity", "資源與執行身分"],
  "cs.h.everythingElse": ["Everything else the record carries", "記錄裡剩下的所有東西"],
  "cs.h.heavySeries": ["Heavy series", "大型序列"],
  "cs.h.verdictFile": ["The verdict file as published", "已發佈的判定檔案原文"],

  "cs.dnp.inconclusive.head": [
    "{v} establishes nothing in either direction.",
    "{v} 在兩個方向上都沒有確立任何事。",
  ],
  "cs.dnp.inconclusive.body": [
    "It is not a weak {t} and not a soft {f}: the measurement ran and did not decide the claim. It licenses no amendment to the design document and may not be cited as evidence for or against the claim.",
    "它不是一個弱一點的 {t}，也不是一個軟一點的 {f}：測量跑過了，但沒有把這條主張判出來。" +
      "它不授權對設計文件做任何修訂，也不可以被引用來支持或反對這條主張。",
  ],
  "cs.dnp.absent.head": [
    "This verdict record carries no such statement.",
    "這份判定記錄裡沒有這樣的陳述。",
  ],
  "cs.dnp.absent.body": [
    "The artifact has no {field} field, so nothing bounds how far this {verdict} may be read. That is a gap in the record, not an assertion that the verdict generalises — this section is rendered for every case precisely so an unwritten caveat cannot look like an absent need for one.",
    "這份產物沒有 {field} 這個欄位，所以沒有任何東西界定這個 {verdict} 可以被讀到多遠。" +
      "這是記錄裡的一個缺口，不是在主張這個判定可以推廣 —— " +
      "這一段之所以在每一個案例上都會渲染出來，正是為了讓一條沒寫下來的但書，不會看起來像是根本不需要但書。",
  ],
  "cs.dnp.verdictWord": ["verdict", "判定"],
  "cs.dnp.opposite": [
    "the record also carries the caveat for the opposite outcome",
    "這份記錄同時帶著相反結果的那一條但書",
  ],

  // RECORDED is not a weaker verdict — it is a case whose oracle was pre-registered with NO expected
  // direction ("OUTCOME UNKNOWN — that is the experiment"), so either outcome was a finding before the
  // measurement ran. There is therefore no direction to over-read, and the absent-caveat warning that
  // used to fire here was answering a question the case never asked.
  "cs.dnp.recorded.head": [
    "{v} was pre-registered with no expected direction.",
    "{v} 在預先登記時就沒有設定預期方向。",
  ],
  "cs.dnp.recorded.body": [
    "The oracle for this case states that the outcome is unknown and that either result is a finding, so there is no direction here for a reader to over-read and no caveat is owed for one. What the observation does and does not reach is bounded by the oracle text and the guards above.",
    "這個案例的判準明確寫著結果未知、兩種結果都算發現，所以這裡沒有一個方向會讓讀者讀得太遠，也就不欠任何一條方向性的但書。" +
      "這次觀察到得了哪裡、到不了哪裡，由上面的判準原文和防護條件界定。",
  ],

  // A verdict with no direction — INCONCLUSIVE, RECORDED — is owed no caveat of its own, so the absent
  // box must not fire for it and must not name a field that belongs to another direction. But the
  // record may still carry a sentence bounding a reading the verdict never reached, and 9 cases do.
  // Showing it labelled for what it is beats both dropping it and mislabelling it as this verdict's.
  "cs.dnp.otherDirection": [
    "the record bounds a {v} reading of this measurement, which this verdict did not reach",
    "這份記錄界定了這次測量在 {v} 方向上可以讀到多遠，而這個判定並沒有走到那裡",
  ],

  // Authored caveats. Rendered visibly apart from a record sentence because the difference in who
  // wrote it is the whole point: the record's sentence is evidence, this one is a later reader's
  // reasoning about that evidence, and a reader who cannot tell them apart has been given the weaker
  // one at the strength of the stronger.
  "cs.dnp.authored.head": [
    "The record states no limits. This bound was written by a later reader of it, not by the run.",
    "記錄本身沒有寫下限制。下面這條界線是後來的讀者從記錄裡讀出來寫的，不是那次執行寫的。",
  ],
  "cs.dnp.authored.provenance": [
    "Authored by {by} on {on}, from {from}. Review status: {status}. It is counted separately from the record's own caveats and is never merged into them.",
    "由 {by} 在 {on} 依據 {from} 撰寫。審閱狀態：{status}。它與記錄自帶的但書分開計數，永遠不會被併進去。",
  ],
  "cs.dnp.authored.unreviewed": [
    "not yet reviewed by a human",
    "尚未經過人工審閱",
  ],

  "cs.g.th.guard": ["guard", "防護條件"],
  "cs.g.th.held": ["held", "是否成立"],
  "cs.g.th.testWhy": ["what it tested, and why", "它測了什麼、為什麼要測"],
  "cs.g.held": ["held", "成立"],
  "cs.g.noTestWhy": [
    "no test/why recorded for this guard",
    "這個防護條件沒有記錄 test 或 why",
  ],
  "cs.g.detail": ["guard detail", "防護條件細節"],

  "cs.bl.count": ["{n} blocker(s)", "{n} 個阻礙"],
  "cs.bl.none": ["No blocker was recorded for this case.", "這個案例沒有記錄任何阻礙。"],

  "cs.sj.th.arm": ["arm", "實驗臂"],
  "cs.sj.th.wanted": ["wanted", "想要的"],
  "cs.sj.th.found": ["found", "找到的"],
  "cs.sj.th.timed": ["timed", "有計時的"],
  "cs.sj.th.queries": ["queries", "查詢次數"],
  "cs.sj.th.missing": ["missing", "缺少的"],
  "cs.sj.th.truncated": ["truncated", "是否被截斷"],
  "cs.sj.truncated": ["TRUNCATED", "已截斷"],
  "cs.sj.notTruncated": ["no", "否"],
  "cs.sj.kv.requestId": ["request id", "請求識別碼"],
  "cs.sj.kv.spanTime": ["span time", "span 時間"],
  "cs.sj.kv.spanTime.value": [
    "{t} ({into} s into the window)",
    "{t}（進入這個時間窗 {into} 秒）",
  ],
  "cs.sj.note": [
    "Each tick is the timestamp at which one request's span was recovered from telemetry, not a latency. The two arms are separate sets of calls, so a tick in one has no partner in the other — this is a coverage view, and the paired estimator lives in the verdict record.",
    "每一條刻度是某一個請求的 span 從遙測資料裡被取回的時間戳，不是一個延遲值。兩條實驗臂是兩組不同的呼叫，" +
      "所以其中一條上的刻度在另一條上沒有對應的夥伴 —— 這是一個涵蓋率的視圖，" +
      "而成對比較的估計量放在判定記錄裡。",
  ],
  "cs.sj.nothingToPlot": [
    "The arms carry counts but no per-request timestamps, so there is nothing to plot.",
    "這些實驗臂帶著計數，但沒有逐一請求的時間戳，所以沒有東西可以畫。",
  ],
  "cs.sj.stubbed.head1": [
    "One arm's per-request timestamps are not on this page yet",
    "有一條實驗臂的逐一請求時間戳還沒有出現在這一頁上",
  ],
  "cs.sj.stubbed.head": [
    "{n} arms' per-request timestamps are not on this page yet",
    "有 {n} 條實驗臂的逐一請求時間戳還沒有出現在這一頁上",
  ],
  "cs.sj.stubbed.body": [
    "({arms}). They were large enough to be published as a separate series; load them from {section} below and this plot fills in. The counts in the table above are the record's own and are complete either way.",
    "（{arms}）。它們大到被單獨發佈成一份序列檔；到下面的{section}把它們載進來，這張圖就會補齊。" +
      "上面表格裡的計數是記錄自己的數字，不管有沒有載入都是完整的。",
  ],

  "cs.rep.none": [
    "No archived copy of this verdict exists, so this case has been measured on one occasion only. It is not replicated. The dashboard will not call a single measurement a replication however many times the case is rendered.",
    "這個判定沒有任何存檔副本，所以這個案例只在一個時機上被測量過。它沒有被重現。" +
      "不管這個案例被渲染幾次，這個看板都不會把一次測量叫做一次重現。",
  ],
  "cs.rep.disagree.head1": [
    "1 archived copy of this verdict disagrees with the live file.",
    "這個判定有 1 份存檔副本和現行檔案不一致。",
  ],
  "cs.rep.disagree.head": [
    "{n} archived copies of this verdict disagree with the live file.",
    "這個判定有 {n} 份存檔副本和現行檔案不一致。",
  ],
  "cs.rep.disagree.body": [
    "A disagreement between two measurement occasions is a finding about the stability of the claim, not an error to be resolved by preferring the newer run. Both verdicts are shown.",
    "兩個測量時機之間的不一致，是一個關於這條主張穩不穩定的發現，" +
      "不是一個靠偏向比較新的那一次執行就能解決掉的錯誤。兩個判定都會顯示出來。",
  ],
  "cs.rep.th.label": ["label", "標籤"],
  "cs.rep.th.verdict": ["verdict in that file", "那個檔案裡的判定"],
  "cs.rep.th.runId": ["run id", "執行識別碼"],
  "cs.rep.th.sha": ["sha256", "sha256"],
  "cs.rep.live": ["live", "現行"],
  "cs.rep.days": [
    "Distinct calendar days named by the archive labels: {days}. A replication requires two distinct UTC days; one day repeated is a re-run.",
    "存檔標籤所指名的不同日曆日：{days}。一次重現需要兩個不同的 UTC 日；同一天重複一次只是重跑。",
  ],

  "cs.resources.note": [
    "Account identifiers and bucket names are masked by the same redaction pass that guards the repository, so an identifier here reads as a placeholder rather than a real one.",
    "帳號識別碼和儲存桶名稱，是由守著這個倉庫的同一道遮蔽程序遮掉的，" +
      "所以這裡的識別碼看起來是一個佔位符，不是一個真的值。",
  ],

  "cs.hs.body": [
    "This case's large arrays were split out of the case file to keep the page small and are published separately at {file}. Each one left a stub in the record naming its own path, its element count and its size, so this page can tell you what it is not showing you before it fetches anything.",
    "這個案例的大型陣列被從案例檔案裡切出來，好讓這一頁保持輕巧，並且單獨發佈在 {file}。" +
      "每一個陣列都在記錄裡留下一個殘根，寫著它自己的路徑、元素數量和大小，" +
      "所以這一頁在還沒抓取任何東西之前，就能告訴你它沒有顯示什麼給你。",
  ],
  "cs.hs.th.path": ["path in the record", "在記錄裡的路徑"],
  "cs.hs.th.elements": ["elements", "元素數"],
  "cs.hs.th.size": ["size", "大小"],
  "cs.hs.th.loaded": ["loaded", "已載入"],
  "cs.hs.loaded.yes": ["yes ({n})", "是（{n}）"],
  "cs.hs.loaded.missing": ["MISSING", "缺失"],
  "cs.hs.loaded.no": ["no", "否"],
  "cs.hs.load": ["Load the series into this page", "把序列載入這一頁"],
  "cs.hs.loading": ["loading…", "載入中…"],
  "cs.hs.disagree.head": [
    "The series file and this page disagree.",
    "序列檔案和這一頁對不上。",
  ],
  "cs.hs.disagree.body": [
    "These paths were published as series but this record carries no matching stub for them: {paths}. Every panel above is therefore showing the record WITHOUT them. This should be impossible — {gate} asserts at publish time that the stubs, the series file and {field} agree — so treat it as a payload defect rather than as a case whose series happened to be small.",
    "這些路徑被當成序列發佈了，但這份記錄裡沒有對應的殘根：{paths}。" +
      "因此上面每一塊面板顯示的都是「不含」它們的那份記錄。這件事本來不可能發生 —— " +
      "{gate} 會在發佈時斷言殘根、序列檔案和 {field} 三者一致 —— " +
      "所以請把它當成資料本身的一個缺陷，而不是一個序列剛好很小的案例。",
  ],
  "cs.hs.done": [
    "Loaded. The panels above — the span join in particular — now render the full arrays, not the stubs.",
    "已載入。上面那些面板 —— 特別是 span 對接那一塊 —— 現在渲染的是完整的陣列，不是殘根。",
  ],

  // ------------------------------------------------------------------ how a verdict is made
  //
  // The step titles and every card definition here are this platform's own account of its own procedure,
  // so they are translated. `method.json`'s `note` and `why_this_is_counted`, and `families.yaml`'s `why`,
  // `replication_requirement` and `ui_state_note`, are quoted instead — they are the artifacts this page
  // reports on. The four verdict words and the oracle-kind, guard, cost, runner and mutates vocabularies
  // stay in the words the payload uses, because a reader greps the payload for them.

  "mth.loading": ["the method census", "方法普查"],
  "mth.lede": [
    "The chain every case travels, from a sentence in the design document to a verdict that may be cited — with the count, at each step, of how many cases actually satisfy the step as described.",
    "每一個案例都要走過的那條鏈：從設計文件裡的一句話，一直到一個可以被引用的判定 —— " +
      "而且每一步都附上一個數字：實際上有多少個案例真的做到了這一步所描述的事。",
  ],
  "mth.note": [
    "Nothing on this page is authored prose about the data; the prose describes the procedure, and every number beside it is counted from the verdict files at build time.",
    "這一頁上沒有任何一句是人工寫下來描述資料的話；這裡的文字描述的是程序，而旁邊的每一個數字，" +
      "都是在建置時從判定檔案裡數出來的。",
  ],
  "mth.sealed": ["sealed", "封存的"],

  "mth.s1.title": ["A claim is extracted and sealed", "一條主張被抽出來，然後封存"],
  "mth.s1.body": [
    "Each unit of the design document becomes a row in {file} with its classification, its anchor, and the document line it came from. That file is {sealed}: it was fixed before any measurement ran, so a claim cannot be quietly reworded to match what was later found. The {claims} view renders it exactly as stored.",
    "設計文件裡的每一個單元，都會變成 {file} 裡的一列，帶著它的分類、它的錨點，以及它來自文件的哪一行。" +
      "那個檔案是{sealed}：它在任何測量開始之前就被固定住了，所以一條主張不可能被悄悄改寫成後來所發現的樣子。" +
      "{claims}那一頁就照著存下來的樣子把它呈現出來。",
  ],

  "mth.s2.title": [
    "An oracle is written before the measurement, and hashed",
    "判準在測量之前就寫好，並且被雜湊",
  ],
  "mth.s2.body": [
    "For each case an oracle states, in advance, the condition under which the claim counts as held — a threshold, an enumeration, an interval relation. The oracle text is registered in {pre} and hashed; the build re-verifies those hashes on every run, so a drifted seal fails the publish rather than reaching this page. Case pages quote {oracle} verbatim and never paraphrase it, because a paraphrase of a sealed oracle is a new oracle.",
    "每一個案例都有一個判準，事先說清楚在什麼條件下這條主張才算成立 —— 一個門檻、一份列舉、" +
      "或是一個區間關係。判準的文字登記在 {pre} 裡並且被雜湊；建置程序每一次執行都會重新驗證那些雜湊值，" +
      "所以一個漂掉的封印會讓發佈失敗，而不是走到這一頁上來。案例頁面是逐字引用 {oracle} 的，" +
      "從來不改寫它 —— 因為把一個封存的判準改寫一遍，那就是一個新的判準了。",
  ],
  "mth.s2.kinds": [
    "The {n} oracle shapes in use, and how many cases use each:",
    "目前用到的 {n} 種判準形狀，以及各有多少個案例在用：",
  ],
  "mth.kind.th.kind": ["oracle kind", "判準種類"],
  "mth.kind.th.cases": ["cases", "案例數"],

  "mth.s3.title": [
    "An instrument runs, and guards decide whether its output counts",
    "儀器跑起來，然後由防護條件決定它的輸出算不算",
  ],
  "mth.g.body": [
    "A guard is a condition the measurement had to satisfy before its result was allowed to count — that the two arms were disjoint, that the blocking policy was load-bearing before the mutation, that the restore was verified afterwards. Guards are named per case, and the case page prints each one's {test} and {why} beside whether it held.",
    "一個防護條件，就是一個測量必須先滿足、它的結果才被允許算數的條件 —— 例如兩組實驗臂彼此不重疊、" +
      "例如在動手改動之前那條封鎖政策確實在承重、例如事後還原有被驗證過。防護條件是按案例逐一命名的，" +
      "案例頁面會把每一個條件的 {test} 和 {why} 印在「它有沒有成立」旁邊。",
  ],
  "mth.g.card.distinct": ["distinct named guards", "不同的具名防護條件"],
  "mth.g.card.distinct.def": [
    "Across every published verdict. Guards are written per case rather than drawn from a fixed list, which is why there are this many.",
    "橫跨每一個已發佈的判定。防護條件是按案例逐一寫的，不是從一份固定清單裡挑的，所以數量才會這麼多。",
  ],
  "mth.g.card.once": ["named by exactly one case", "只被一個案例指名"],
  "mth.g.card.once.def": [
    "A guard used once is not a weaker guard; it means the condition that could have invalidated that one measurement was specific to it.",
    "只用過一次的防護條件並不比較弱；它的意思是：那個可能會讓那一次測量失效的條件，是那一次測量特有的。",
  ],
  "mth.g.unnamed.head": [
    "{n} guard(s) are recorded without a name.",
    "有 {n} 個防護條件被記錄下來時沒有名字。",
  ],
  "mth.g.unnamed.body": [
    "Their records carry a test and a result but no identifier, so they cannot be counted as any of the {named} named guards above and cannot be searched for here. The build files them under an explicit bucket rather than coercing the record into a name — a guard census that silently invented one would disagree with the case pages, which show these guards exactly as stored. Recording a guard without a name is a defect in the producer, and this is the number.",
    "它們的記錄裡有一個測試和一個結果，但沒有識別名，所以它們不能被算進上面那 {named} 個具名條件裡，" +
      "在這裡也搜不到。建置程序把它們歸到一個明講出來的桶子裡，而不是硬把記錄湊出一個名字 —— " +
      "一份會悄悄自己編出名字的防護條件普查，會和案例頁面對不上，因為案例頁面是照著存下來的樣子顯示這些條件的。" +
      "記錄一個防護條件卻不給它名字，這是產生端的一個缺陷，而這就是它的數量。",
  ],
  "mth.g.search": ["search guards", "搜尋防護條件"],
  "mth.g.placeholder": ["e.g. restore, arms, seal", "例如 restore、arms、seal"],
  "mth.g.shown": ["{n} shown", "顯示 {n} 個"],
  "mth.g.th.guard": ["guard", "防護條件"],
  "mth.g.th.cases": ["cases naming it", "指名它的案例數"],

  "mth.s4.title": [
    "A verdict is read off the oracle — one of four values",
    "判定是從判準上讀出來的 —— 四個值裡的一個",
  ],
  "mth.s4.body": [
    "{t} and {f} are readings of the sealed condition. {i} is a first-class outcome, not a weak TRUE and not a soft FALSE: it says the measurement did not establish the condition either way, and it licenses no amendment in either direction. {r} is a written observation that was never adjudicated against an oracle at all, and may not be cited as a verdict. There is no pass rate anywhere in this platform, because a ratio over four values that do not share an axis would not mean anything — and the FALSE verdicts, which locate where published guidance did not hold, are the most valuable output the study has.",
    "{t} 和 {f} 是對那個封存條件的讀數。{i} 是一個完整的結果，不是一個弱一點的 TRUE，也不是一個軟一點的 " +
      "FALSE：它說的是這次測量兩個方向都沒有確立，因此它不授權任何一個方向上的修訂。{r} 是一筆寫下來的觀察，" +
      "從頭到尾沒有對著任何判準裁決過，所以不可以被當成判定來引用。這個平台上任何地方都沒有通過率，" +
      "因為在四個不共用同一條軸的值上面算出來的比率不會有任何意義 —— " +
      "而那些 FALSE 判定，也就是指出已發佈的指引在哪裡沒有成立的那些判定，是這份研究最有價值的產出。",
  ],

  "mth.s5.title": [
    "What the verdict does not prove is stated — or its absence is counted",
    "這個判定不能證明什麼，要說出來 —— 沒說的話就會被數出來",
  ],
  "mth.cav.body": [
    "A verdict answers exactly one question. What it does NOT answer is the part a reader will get wrong, and the record has a field for it: {t} and {f}. Every case page renders that section whether or not the record fills it in, so an absent caveat is visible on the case rather than only in this total.",
    "一個判定只回答一個問題。它「沒有」回答的那一部分，才是讀者會弄錯的地方，而記錄裡有專門的欄位放它：" +
      "{t} 和 {f}。不管記錄有沒有填，每一個案例頁面都會把那一段渲染出來，" +
      "所以一個缺席的但書會出現在案例上，而不是只反映在這個總數裡。",
  ],
  "mth.cav.card.false": [
    "{v} verdicts stating what they do not prove",
    "有說出自己不能證明什麼的 {v} 判定",
  ],
  "mth.cav.card.false.def": [
    "A FALSE verdict says published guidance did not hold under this measurement. It does not say the control is useless, nor that the failure generalises past the configuration measured.",
    "一個 FALSE 判定說的是：在這次測量之下，已發佈的指引沒有成立。它並沒有說那個控制措施沒有用，" +
      "也沒有說這次的失敗可以推廣到所測量的那個設定之外。",
  ],
  "mth.cav.card.true": [
    "{v} verdicts stating what they do not prove",
    "有說出自己不能證明什麼的 {v} 判定",
  ],
  "mth.cav.card.true.def": [
    "A TRUE verdict says the stated condition held in the configuration measured, on the days measured. Anything wider than that is an inference the reader is making, not one recorded.",
    "一個 TRUE 判定說的是：在所測量的那個設定裡、在所測量的那幾天裡，被陳述的條件成立。" +
      "任何比這個更寬的說法，都是讀者自己在推論，不是記錄下來的東西。",
  ],
  "mth.cav.gap.head": [
    "This is a gap in the corpus, not a rendering choice.",
    "這是語料本身的缺口，不是呈現方式的選擇。",
  ],
  "mth.cav.without": [
    "{v} without the caveat ({n}):",
    "沒有附上但書的 {v}（{n} 個）：",
  ],

  "mth.s6.title": [
    "Replication is two distinct days, or it is not replication",
    "重現就是兩個不同的日子，否則就不是重現",
  ],
  "mth.rep.body": [
    "A measurement made once is a measurement, not a replication. The study keeps day-1 verdict files under {dir}, and a case counts as replicated only when two {days} exist — one day repeated is a re-run, and it cannot distinguish a stable property from a property of that day.",
    "只做過一次的測量就是一次測量，不是一次重現。本研究把第一天的判定檔案保存在 {dir} 底下，" +
      "而一個案例只有在存在兩個{days}的時候才算被重現過 —— 同一天重跑一次只是重跑，" +
      "它分不出「一個穩定的性質」和「那一天的性質」。",
  ],
  "mth.rep.distinctDays": ["distinct UTC calendar days", "不同的 UTC 日曆日"],
  "mth.rep.card.archive": ["cases with at least one archived run", "至少有一次執行被歸檔的案例"],
  "mth.rep.card.archive.def": [
    "An archive exists for the case. This number alone establishes nothing about replication.",
    "這個案例有存檔存在。單看這個數字，關於重現什麼都確立不了。",
  ],
  "mth.rep.card.twoDays": [
    "cases with archives from two distinct UTC days",
    "存檔來自兩個不同 UTC 日的案例",
  ],
  "mth.rep.card.twoDays.def": [
    "The only cases where the archive itself can support the word \"replicated\". Counted from the dates in the archive filenames, not from any status field.",
    "只有這些案例，光靠存檔本身就撐得起「已重現」這個詞。這是從存檔檔名裡的日期數出來的，" +
      "不是從任何狀態欄位讀出來的。",
  ],
  "mth.rep.card.disagree": [
    "archives whose verdict differs from the live one",
    "判定和現行判定不一樣的存檔",
  ],
  "mth.rep.card.disagree.def": [
    "A disagreement is a finding. It is not resolved by preferring the newer run, and nothing here silently prefers one.",
    "不一致是一個發現。它不會因為偏向比較新的那一次執行就被解決掉，而這裡也沒有任何東西在悄悄偏向哪一次。",
  ],
  "mth.rep.th.case": ["case", "案例"],
  "mth.rep.th.archived": ["archived verdict", "存檔裡的判定"],
  "mth.rep.th.live": ["live verdict", "現行判定"],
  "mth.rep.th.label": ["archive label", "存檔標籤"],
  "mth.rep.kv.twoDays": ["two distinct UTC days", "兩個不同的 UTC 日"],
  "mth.rep.kv.oneDay": ["archive on one day only", "只有一天有存檔"],
  "mth.rep.none": ["none", "無"],

  "mth.s7.title": [
    "Re-running is classified before it is permitted",
    "重跑在被允許之前，先要被分類",
  ],
  "mth.fam.loading": ["the family classification", "族群分類"],
  "mth.fam.body": [
    "Re-running a measurement is not uniformly safe or uniformly free, so each family carries an authored classification in {file}: what a re-run costs, where it must run, what it mutates, and whether it may be scheduled at all. The build refuses to emit this file if a registered family is missing from it OR if it classifies a family that does not exist — a family added later must be classified before it can be scheduled, rather than becoming schedulable by omission. A family marked not schedulable must state why, in the file.",
    "重跑一次測量，並不是每一次都一樣安全、也不是每一次都一樣免費，所以每一個族群在 {file} 裡" +
      "都帶著一份人工寫的分類：重跑一次要花什麼、它必須在哪裡跑、它會改動什麼、以及它到底可不可以被排程。" +
      "如果有一個已登記的族群沒出現在這個檔案裡，「或者」這個檔案分類了一個不存在的族群，" +
      "建置程序就拒絕產出這個檔案 —— 一個之後才加進來的族群，必須先被分類才能被排程，" +
      "而不是因為漏掉而變成可排程。一個被標成不可排程的族群，必須在這個檔案裡說明為什麼。",
  ],
  "mth.fam.th.family": ["family", "族群"],
  "mth.fam.th.cases": ["cases", "案例數"],
  "mth.fam.th.cost": ["cost class", "成本級別"],
  "mth.fam.th.runner": ["runner", "執行機"],
  "mth.fam.th.mutates": ["mutates", "改動什麼"],
  "mth.fam.th.schedulable": ["schedulable", "可排程"],
  "mth.fam.th.whyNot": ["why not / note", "為什麼不行／備註"],
  "mth.fam.yes": ["yes", "可以"],
  "mth.fam.no": ["no", "不行"],
  "mth.fam.costNote": [
    "{cost} here is a class, never a dollar figure — money has exactly one source in this project, and it is not this file.",
    "這裡的 {cost} 是一個級別，絕對不是一個金額 —— 在這個專案裡，錢只有一個來源，而那個來源不是這個檔案。",
  ],
  "mth.fam.vocabularies": ["Vocabularies:", "詞彙集：",],
  "mth.fam.netPos": [
    "{id} is network-position sensitive.",
    "{id} 對網路位置敏感。",
  ],
  "mth.fam.uiState": ["UI state when old:", "過期時的介面狀態："],

  "mth.s8.title": [
    "Only then may a document change be proposed",
    "到這一步之後，才可以提議修改文件",
  ],
  "mth.s8.body": [
    "An amendment to the design document must rest on a verdict that survived replication, and the gate between \"measured\" and \"proposed\" is a script, not a judgment call. An {i} verdict produces zero proposed lines. What may and may not be cited from a given verdict is data, in {citations}, rendered on each case page from the same file — so the rule and its display cannot drift apart. Where the study falls short of all of this, it is written down in {register} rather than fixed silently.",
    "對設計文件的一次修訂，必須建立在一個經得起重現的判定上面，而「已測量」和「已提議」之間那道關卡是一支程式，" +
      "不是一個人的判斷。一個 {i} 判定產生出零行提議。一個判定裡哪些可以引用、哪些不可以，本身就是資料，" +
      "放在{citations}裡，每一個案例頁面也是從同一個檔案渲染出來的 —— 所以規則和它的顯示不可能漂開。" +
      "本研究在上面這些事情上做不到的地方，會被寫進{register}，而不是被悄悄修掉。",
  ],

  // ------------------------------------------------------------------ design diagrams
  //
  // The authored topology file's own sentences — a box's `detail`, `why_this_status`, `status_label`,
  // `why_not_measured`, `why_these_cases`, a diagram's `label`/`subtitle`/`why_this_diagram`, a case's
  // `title`, and the coverage justifications — are NOT in here. They are the material this page reports
  // on, so they are quoted in English in both languages. What is in here is the frame around them.

  "arc.loading": ["the design diagrams", "設計圖"],
  "arc.lede": [
    "Two pictures, and one rule that governs both: the boxes and arrows are authored in {file} — which component a case is ABOUT is a judgment, and no artifact in this repository records it — while every colour, count, badge and coordinate on this page is recomputed at build time from the sealed register, the published verdicts and the citation policy. Nothing here is typed twice.",
    "兩張圖，一條同時管住兩張圖的規則：方塊和箭頭是人工寫在 {file} 裡的 —— " +
      "一個案例究竟是在講哪一個元件，這是一個判斷，這個倉庫裡沒有任何產物記錄了它 —— " +
      "而這一頁上每一個顏色、數字、標記和座標，都是在建置時從封存的登記簿、已發佈的判定和引用政策重新算出來的。" +
      "這裡沒有任何一個東西被輸入兩次。",
  ],
  "arc.notMeasured": ["not measured", "未測量"],
  "arc.whyColour": ["Why this colour:", "為什麼是這個顏色："],
  "arc.colourMeans": ["What the colour means:", "這個顏色的意思："],
  "arc.kv.kind": ["Kind", "種類"],
  "arc.kv.program": ["Program", "程式"],
  "arc.kv.venv": ["Virtual environment", "虛擬環境"],
  "arc.kv.machine": ["Runs on", "執行於"],
  "arc.kv.count": ["The number on the box", "方塊上的數字"],
  "arc.kv.count.value": ["{n} — derived as {from}", "{n} —— 由 {from} 推導而來"],
  "arc.neverExamined": [
    "This study never examined this component.",
    "本研究從來沒有檢驗過這個元件。",
  ],
  "arc.whyTheseCases": ["Why these cases:", "為什麼是這些案例："],
  "arc.th.verdict": ["Verdict", "判定"],
  "arc.th.decided": ["What it decided", "它決定了什麼"],
  "arc.th.whyUnplaced": ["Why it is on no diagram", "為什麼它不在任何一張圖上"],
  "arc.restrict.blocked": [
    "This restriction means the case colours nothing on this diagram.",
    "這項限制的意思是：這個案例在這張圖上不為任何東西上色。",
  ],
  "arc.restrict.scope": [
    "A scope restriction on how the case may be cited.",
    "這是一項範圍限制，管的是這個案例可以怎麼被引用。",
  ],
  "arc.aria": ["{boxes} components, {edges} relations", "{boxes} 個元件，{edges} 條關係"],
  "arc.hint": [
    "{boxes} components, {edges} relations. Click a component for the cases behind its colour. The arrows are authored; the positions are computed from them, and {test} asserts zero crossings and zero arrows through a box as equalities — so an arrow you see meeting another is a defect, not a shortcut.",
    "{boxes} 個元件，{edges} 條關係。點一個元件，可以看到它的顏色背後是哪些案例。箭頭是人工寫的；" +
      "位置則是從箭頭算出來的，而 {test} 是用等式來斷言「零交叉」和「零箭頭穿過方塊」的 —— " +
      "所以你要是看到一條箭頭和另一條碰在一起，那是一個缺陷，不是為了省事。",
  ],
  "arc.noSelection": [
    "No component selected. Every colour on the diagram is derived from the register at build time; the panel here shows which cases produced it and which of them the citation policy says may colour nothing.",
    "還沒有選任何元件。圖上每一個顏色都是在建置時從登記簿推導出來的；" +
      "這一塊面板會告訴你是哪些案例產生了那個顏色，以及其中哪些案例被引用政策判定為不得為任何東西上色。",
  ],
  "arc.whyDiagram": ["Why this diagram exists", "這張圖為什麼存在"],
  "arc.h.coverage": ["Coverage", "涵蓋範圍"],
  "arc.coverage": [
    "{placed} of {registered} registered case(s) appear on a diagram, and {unplaced} are excluded in writing.",
    "已登記的 {registered} 個案例裡，有 {placed} 個出現在某張圖上，另外 {unplaced} 個以書面方式被排除。",
  ],
  "arc.h.metrics": ["The numbers on the boxes", "方塊上的那些數字"],
  "arc.metrics.body": [
    "A box may display one derived count, named by the authored file and computed by the build. The closed set is below, so a number on a box can always be traced to the thing that produced it — and a metric this file could not compute fails the build rather than rendering blank.",
    "一個方塊最多顯示一個推導出來的計數：由人工寫的檔案指名要哪一個，再由建置程序算出來。" +
      "底下是這組封閉的清單，所以方塊上的一個數字永遠可以追回到產生它的那個東西 —— " +
      "而一個這個檔案算不出來的指標會讓建置失敗，而不是讓它渲染成空白。",
  ],
  "arc.mappedBy": ["Topology mapped by {who} on {when}.", "拓樸由 {who} 在 {when} 對應完成。"],

  // ------------------------------------------------------------------ deficiency register
  "reg.item": ["item {n}", "第 {n} 項"],
  "reg.loading": ["the register", "登記簿"],
  "reg.lede": [
    "{n} items the study records against itself, tiered by what each one invalidates. This is the register the platform is measured against, not a backlog: an item stays until an artifact closes it.",
    "本研究對自己記下的 {n} 項缺陷，按照每一項會使什麼失效來分級。這是這個平台被衡量的依據，不是待辦清單：" +
      "一項缺陷會一直留著，直到有產物把它關掉。",
  ],
  "reg.h.dates": ["Dates the register commits to", "登記簿承諾的日期"],
  "reg.th.date": ["date", "日期"],
  "reg.th.days": ["days from today", "距今天數"],
  "reg.th.item": ["item", "項目"],
  "reg.passed": ["{n} PASSED", "已逾期 {n} 天"],
  "reg.expired.head": [
    "{n} date(s) in this table have passed since this payload was built.",
    "這張表裡有 {n} 個日期，在這份資料被建置之後已經過去了。",
  ],
  "reg.expired.body": [
    "They are still listed on purpose. A countdown that drops a date the moment it expires is silent exactly when it matters — the row would vanish rather than turn red, and the page would look calm. A passed row means either the commitment was met and the register has not been re-derived since, or it was not met at all; the platform cannot tell which, and says so instead of choosing.",
    "它們被刻意留在表上。一個到期就把日期丟掉的倒數計時，恰恰在最要緊的時候安靜下來 —— 那一列會消失、" +
      "而不是變紅，整個頁面看起來一片平靜。一列逾期代表兩件事之一：承諾已經達成、只是登記簿之後沒有重新推導；" +
      "或者根本沒有達成。這個平台分辨不出是哪一種，所以它把這件事說出來，而不是幫你選一個。",
  ],
  "reg.cutoffNote": [
    "Every date any item names that was strictly after the day this payload was derived (cutoff {cutoff}{source}), found by scanning the items themselves, with days counted against the reader's clock. Two limits, stated rather than left to be assumed: the scan cannot tell a date an item {commits} to from one it merely {mentions}, so a row here is not necessarily a deadline; and a date on or before the build day is absent — the register's own working days (2026-08-15 is named by thirteen items) would otherwise bury the commitments. Nothing is missed because it sat in a paragraph nobody re-read.",
    "任何項目所指名的、嚴格晚於這份資料被推導出來那一天的每一個日期（截止點 {cutoff}{source}），" +
      "都是靠掃描項目本身找出來的，天數則是對著讀者自己的時鐘計算。有兩個限制，這裡明說而不留給人假設：" +
      "這個掃描分不出一個項目是{commits}某個日期、還是只是{mentions}它，所以這裡的一列不一定是期限；" +
      "另外，等於或早於建置那一天的日期不會出現 —— 否則登記簿自己的工作日（2026-08-15 被十三個項目指名）" +
      "會把真正的承諾埋掉。沒有任何東西會因為躺在一段沒人重讀的文字裡而被漏掉。",
  ],
  "reg.cutoff.fromBuild": [" — the build stamp", " —— 也就是建置戳記"],
  "reg.cutoff.fromReader": [
    " — the manifest's stamp was unavailable, so the reader's today",
    " —— 清單的戳記取不到，所以用讀者的今天",
  ],
  "reg.cutoff.commits": ["commits", "承諾"],
  "reg.cutoff.mentions": ["mentions", "提到"],
  "reg.h.items": ["Items", "項目"],
  "reg.facet.tier": ["tier", "層級"],
  "reg.h.side": ["Side registers", "附屬登記簿"],
  "reg.side.absent": [
    "{name} is not published in this payload. The build emits null rather than an empty string, so \"the file has no content\" and \"the build did not find the file\" stay distinguishable — they have different causes.",
    "{name} 沒有發佈在這份資料裡。建置程序輸出的是 null 而不是空字串，這樣「檔案沒有內容」和" +
      "「建置程序找不到這個檔案」才分得開 —— 這兩者的原因不一樣。",
  ],
} as const satisfies Record<string, Entry>;

export type Key = keyof typeof STRINGS;
