// A small markdown renderer that emits React elements and NEVER touches innerHTML.
//
// WHY NOT A LIBRARY, AND WHY NOT `dangerouslySetInnerHTML`
//
// The markdown this renders is `body_md` out of `findings.json`, `registers.json` and
// `citation_policy.json` — that is, the F5 red-team findings, which quote adversarial prompt-injection
// payloads verbatim, and the PII corpora notes. Those strings are hostile input by construction: the
// study's own job was to send them at a guardrail. Piping them through any HTML-producing markdown
// pipeline makes the dashboard the one place in the project where a payload gets to be markup, and a
// sanitiser would then be the only thing between a stored test artifact and script execution inside an
// authenticated Cognito session.
//
// Emitting React elements removes that class of bug rather than filtering it: React escapes text
// children, so `<img src=x onerror=…>` in a finding renders as those characters. The cost is a
// deliberately partial markdown dialect — the block constructs the repo's own markdown actually uses
// (ATX headings, fenced code, GFM tables, lists, blockquotes, rules, paragraphs) plus inline code,
// strong, emphasis and links. Anything outside the dialect renders as its literal source text, which
// is the safe failure: a reader sees `~~struck~~` rather than silently losing the words.
//
// Links are additionally restricted to `http:`, `https:`, `#` and relative paths, so a
// `javascript:` URL in an artifact cannot become an href.

import type { ReactNode } from "react";

const SAFE_HREF = /^(https?:\/\/|#|\.{0,2}\/|[A-Za-z0-9._-]+(\/|$|#))/;

function safeHref(raw: string): string | null {
  const href = raw.trim();
  if (!href || /\s/.test(href)) return null;
  if (/^[A-Za-z][A-Za-z0-9+.-]*:/.test(href) && !/^https?:/i.test(href)) return null;
  return SAFE_HREF.test(href) ? href : null;
}

/** Inline pass: `code`, **strong**, *em*, [text](href). Longest-token-first, single scan. */
export function inline(src: string, keyBase = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let buf = "";
  let k = 0;
  const flush = () => {
    if (buf) {
      out.push(buf);
      buf = "";
    }
  };
  let i = 0;
  while (i < src.length) {
    const rest = src.slice(i);

    // `code` — first, so markup inside a code span stays literal.
    const code = /^`([^`]+)`/.exec(rest);
    if (code && code[1] !== undefined) {
      flush();
      out.push(<code key={`${keyBase}-${k++}`}>{code[1]}</code>);
      i += code[0].length;
      continue;
    }

    const strong = /^\*\*([\s\S]+?)\*\*/.exec(rest);
    if (strong && strong[1] !== undefined) {
      flush();
      out.push(<strong key={`${keyBase}-${k++}`}>{inline(strong[1], `${keyBase}-${k}`)}</strong>);
      i += strong[0].length;
      continue;
    }

    const em = /^\*([^*\n]+)\*/.exec(rest);
    if (em && em[1] !== undefined) {
      flush();
      out.push(<em key={`${keyBase}-${k++}`}>{inline(em[1], `${keyBase}-${k}`)}</em>);
      i += em[0].length;
      continue;
    }

    const link = /^\[([^\]]*)\]\(([^)\s]+)\)/.exec(rest);
    if (link && link[1] !== undefined && link[2] !== undefined) {
      const href = safeHref(link[2]);
      flush();
      if (href) {
        const external = /^https?:/i.test(href);
        out.push(
          <a
            key={`${keyBase}-${k++}`}
            href={href}
            {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})}
          >
            {inline(link[1], `${keyBase}-${k}`)}
          </a>,
        );
      } else {
        // A rejected scheme is shown, not dropped: the reader should see that the artifact
        // contained a link the renderer refused rather than see nothing at all.
        buf += link[0];
      }
      i += link[0].length;
      continue;
    }

    buf += src[i];
    i += 1;
  }
  flush();
  return out;
}

function splitRow(line: string): string[] {
  const t = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return t.split("|").map((c) => c.trim());
}

const isDivider = (line: string) => /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line) && line.includes("-");

/** Block pass. Returns React nodes; unknown constructs fall through to paragraphs verbatim. */
export function markdown(src: string): ReactNode[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  let key = 0;
  const K = () => `b${key++}`;

  while (i < lines.length) {
    const line = lines[i] ?? "";

    if (!line.trim()) {
      i += 1;
      continue;
    }

    // fenced code — the fence's own language is ignored (no highlighter, so no tokeniser to trust)
    const fence = /^\s*(```+|~~~+)(.*)$/.exec(line);
    if (fence && fence[1] !== undefined) {
      const marker = fence[1][0] === "`" ? "```" : "~~~";
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !(lines[i] ?? "").trimStart().startsWith(marker)) {
        body.push(lines[i] ?? "");
        i += 1;
      }
      i += 1; // closing fence, or end of input
      out.push(
        <pre key={K()}>
          <code>{body.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    const head = /^(#{1,6})\s+(.*)$/.exec(line);
    if (head && head[1] !== undefined && head[2] !== undefined) {
      const depth = Math.min(head[1].length, 4);
      const Tag = (["h1", "h2", "h3", "h4"] as const)[depth - 1] ?? "h4";
      out.push(<Tag key={K()}>{inline(head[2])}</Tag>);
      i += 1;
      continue;
    }

    if (/^\s*(---+|\*\*\*+|___+)\s*$/.test(line)) {
      out.push(<hr key={K()} />);
      i += 1;
      continue;
    }

    // GFM table: a header row followed by a divider row
    if (line.includes("|") && isDivider(lines[i + 1] ?? "")) {
      const header = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && (lines[i] ?? "").includes("|") && (lines[i] ?? "").trim()) {
        rows.push(splitRow(lines[i] ?? ""));
        i += 1;
      }
      out.push(
        <table key={K()}>
          <thead>
            <tr>
              {header.map((c, n) => (
                <th key={n}>{inline(c, `h${n}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, rn) => (
              <tr key={rn}>
                {header.map((_, cn) => (
                  <td key={cn}>{inline(r[cn] ?? "", `c${rn}-${cn}`)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      );
      continue;
    }

    if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i] ?? "")) {
        body.push((lines[i] ?? "").replace(/^\s*>\s?/, ""));
        i += 1;
      }
      out.push(<blockquote key={K()}>{markdown(body.join("\n"))}</blockquote>);
      continue;
    }

    const bullet = /^(\s*)([-*+]|\d+[.)])\s+/.exec(line);
    if (bullet && bullet[2] !== undefined) {
      const ordered = /\d/.test(bullet[2]);
      const items: string[][] = [];
      while (i < lines.length) {
        const cur = lines[i] ?? "";
        const m = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(cur);
        if (m && m[3] !== undefined && /\d/.test(m[2] ?? "") === ordered) {
          items.push([m[3]]);
          i += 1;
          // continuation lines: indented, and not themselves a new bullet
          while (i < lines.length) {
            const nxt = lines[i] ?? "";
            if (!nxt.trim() || !/^\s{2,}\S/.test(nxt) || /^\s*([-*+]|\d+[.)])\s/.test(nxt)) break;
            items[items.length - 1]?.push(nxt.trim());
            i += 1;
          }
        } else break;
      }
      const List = ordered ? "ol" : "ul";
      out.push(
        <List key={K()}>
          {items.map((parts, n) => (
            <li key={n}>{inline(parts.join(" "), `l${n}`)}</li>
          ))}
        </List>,
      );
      continue;
    }

    // paragraph: consume until a blank line or the start of another block
    const para: string[] = [];
    while (i < lines.length) {
      const cur = lines[i] ?? "";
      if (
        !cur.trim() ||
        /^(#{1,6})\s/.test(cur) ||
        /^\s*(```|~~~)/.test(cur) ||
        /^\s*>/.test(cur) ||
        /^\s*([-*+]|\d+[.)])\s/.test(cur) ||
        /^\s*(---+|\*\*\*+|___+)\s*$/.test(cur) ||
        (cur.includes("|") && isDivider(lines[i + 1] ?? ""))
      )
        break;
      para.push(cur);
      i += 1;
    }
    out.push(<p key={K()}>{inline(para.join("\n"))}</p>);
  }

  return out;
}

export function Markdown({ src }: { src: string }) {
  return <div className="md">{markdown(src)}</div>;
}
