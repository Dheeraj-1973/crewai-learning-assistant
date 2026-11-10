/*
 * markdown.js - a small, SAFE Markdown renderer.
 *
 * Why not just use innerHTML with the model's text?
 *   The text comes from an AI model. If it contained <script> or
 *   <img onerror=...>, putting it into the page as HTML could run code.
 *
 * How this file stays safe (two layers):
 *   1. ESCAPE FIRST. Every character of the input is HTML-escaped before any
 *      Markdown formatting is applied, so the only HTML tags in the output are
 *      the ones this file writes itself (<p>, <h3>, <code>, ...).
 *   2. SANITIZE AFTER. In the browser, toFragment() parses the HTML inside an
 *      inert <template> and removes any tag or attribute not on an allowlist.
 *      This is a second safety net in case of a bug in layer 1.
 *
 * Supported Markdown: headings, paragraphs, **bold**, *italic*, `code`,
 * fenced code blocks, bullet and numbered lists (with simple nesting),
 * blockquotes, tables, horizontal rules and http(s) links.
 *
 * Works in the browser (window.SafeMarkdown) and in Node.js (for the tests).
 */
(function (root) {
  "use strict";

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /* Inline formatting. Input must ALREADY be escaped. */
  function renderInline(escaped) {
    // Pull out `code` spans first so nothing inside them gets formatted.
    const codeSpans = [];
    let text = escaped.replace(/`([^`]+)`/g, function (_m, code) {
      codeSpans.push("<code>" + code + "</code>");
      return "\u0000" + (codeSpans.length - 1) + "\u0000";
    });

    // [label](https://link) - only http and https links are allowed.
    text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, function (_m, label, url) {
      return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + label + "</a>";
    });

    // Only * is used for emphasis. Underscore emphasis (__x__, _x_) is
    // deliberately NOT supported: in technical text it would turn names
    // like __init__ or snake_case into bold/italic by mistake.
    text = text
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, "$1<em>$2</em>");

    return text.replace(/\u0000(\d+)\u0000/g, function (_m, i) {
      return codeSpans[Number(i)];
    });
  }

  const LIST_ITEM = /^(\s*)([-*+•]|\d+[.)])\s+(.*)$/;

  function isTableSeparator(line) {
    return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
  }

  function splitRow(line) {
    return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(function (c) {
      return c.trim();
    });
  }

  function renderList(lines, start) {
    // Collect consecutive list lines (and their continuation lines).
    const items = [];
    let i = start;
    const baseIndent = lines[start].match(LIST_ITEM)[1].length;
    const ordered = /\d/.test(lines[start].match(LIST_ITEM)[2]);

    while (i < lines.length) {
      const line = lines[i];
      const match = line.match(LIST_ITEM);
      if (match && match[1].length === baseIndent) {
        items.push({ text: match[3], children: [] });
        i += 1;
      } else if (match && match[1].length > baseIndent && items.length) {
        const nested = renderList(lines, i);
        items[items.length - 1].children.push(nested.html);
        i = nested.next;
      } else if (line.trim() && /^\s+/.test(line) && items.length && !match) {
        items[items.length - 1].text += " " + line.trim();
        i += 1;
      } else {
        break;
      }
    }

    const tag = ordered ? "ol" : "ul";
    const html =
      "<" + tag + ">" +
      items.map(function (item) {
        return "<li>" + renderInline(escapeHtml(item.text)) + item.children.join("") + "</li>";
      }).join("") +
      "</" + tag + ">";
    return { html: html, next: i };
  }

  /*
   * options.headingOffset: how many levels to push headings down.
   *   0 (default): "# A" and "### A" both become <h3> (agents' own headings).
   *   2: "# A" -> <h3>, "## B" -> <h4>, "### C" -> <h5> (keeps the outline of
   *      the complete notes document, which uses # and ## itself).
   */
  function render(markdown, options) {
    const headingOffset = (options && options.headingOffset) || 0;
    const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    let paragraph = [];
    let i = 0;

    function flushParagraph() {
      if (paragraph.length) {
        out.push("<p>" + renderInline(escapeHtml(paragraph.join(" "))) + "</p>");
        paragraph = [];
      }
    }

    while (i < lines.length) {
      const line = lines[i];

      // Fenced code block ```lang ... ```
      const fence = line.match(/^\s*```\s*([\w+#.-]*)\s*$/);
      if (fence) {
        flushParagraph();
        const language = fence[1].toLowerCase().replace(/[^a-z0-9+#-]/g, "");
        const code = [];
        i += 1;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
          code.push(lines[i]);
          i += 1;
        }
        i += 1; // skip closing fence (or end of text)
        out.push(
          '<pre data-language="' + escapeHtml(language || "text") + '"><code>' +
          escapeHtml(code.join("\n")) + "</code></pre>"
        );
        continue;
      }

      if (!line.trim()) {
        flushParagraph();
        i += 1;
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
      if (heading) {
        flushParagraph();
        // Generated content never gets <h1>/<h2>; the page owns those levels.
        const level = Math.min(6, Math.max(3, heading[1].length + headingOffset));
        out.push("<h" + level + ">" + renderInline(escapeHtml(heading[2])) + "</h" + level + ">");
        i += 1;
        continue;
      }

      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
        flushParagraph();
        out.push("<hr>");
        i += 1;
        continue;
      }

      if (/^\s*>/.test(line)) {
        flushParagraph();
        const quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) {
          quote.push(lines[i].replace(/^\s*>\s?/, ""));
          i += 1;
        }
        out.push("<blockquote>" + render(quote.join("\n"), options) + "</blockquote>");
        continue;
      }

      if (line.indexOf("|") !== -1 && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
        flushParagraph();
        const header = splitRow(line);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].indexOf("|") !== -1 && lines[i].trim()) {
          rows.push(splitRow(lines[i]));
          i += 1;
        }
        const cell = function (tag) {
          return function (c) { return "<" + tag + ">" + renderInline(escapeHtml(c)) + "</" + tag + ">"; };
        };
        out.push(
          '<div class="table-wrap"><table><thead><tr>' + header.map(cell("th")).join("") +
          "</tr></thead><tbody>" +
          rows.map(function (r) { return "<tr>" + r.map(cell("td")).join("") + "</tr>"; }).join("") +
          "</tbody></table></div>"
        );
        continue;
      }

      if (LIST_ITEM.test(line)) {
        flushParagraph();
        const list = renderList(lines, i);
        out.push(list.html);
        i = list.next;
        continue;
      }

      paragraph.push(line.trim());
      i += 1;
    }
    flushParagraph();
    return out.join("\n");
  }

  /* ---- Layer 2: allowlist sanitizer (browser only) ---- */

  const ALLOWED_TAGS = new Set([
    "P", "H3", "H4", "H5", "H6", "STRONG", "EM", "CODE", "PRE", "UL", "OL", "LI",
    "BLOCKQUOTE", "HR", "A", "TABLE", "THEAD", "TBODY", "TR", "TH", "TD", "DIV", "BR",
  ]);
  const ALLOWED_ATTRIBUTES = {
    A: ["href", "target", "rel"],
    PRE: ["data-language"],
    DIV: ["class"],
  };

  function sanitizeNode(node) {
    Array.from(node.childNodes).forEach(function (child) {
      if (child.nodeType === 3) return; // text is always safe
      if (child.nodeType !== 1 || !ALLOWED_TAGS.has(child.tagName)) {
        child.remove();
        return;
      }
      const allowed = ALLOWED_ATTRIBUTES[child.tagName] || [];
      Array.from(child.attributes).forEach(function (attribute) {
        if (allowed.indexOf(attribute.name) === -1) child.removeAttribute(attribute.name);
      });
      if (child.tagName === "A") {
        const href = child.getAttribute("href") || "";
        if (!/^https?:\/\//i.test(href)) child.removeAttribute("href");
        child.setAttribute("rel", "noopener noreferrer");
        child.setAttribute("target", "_blank");
      }
      if (child.tagName === "DIV" && child.getAttribute("class") !== "table-wrap") {
        child.removeAttribute("class");
      }
      sanitizeNode(child);
    });
  }

  /* Render Markdown and return a sanitized DocumentFragment for the page. */
  function toFragment(markdown, options) {
    const template = document.createElement("template"); // inert: nothing runs or loads
    template.innerHTML = render(markdown, options);
    sanitizeNode(template.content);
    return template.content;
  }

  const api = { render: render, escapeHtml: escapeHtml, toFragment: toFragment };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.SafeMarkdown = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
