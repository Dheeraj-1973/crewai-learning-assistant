/*
 * Tests for js/markdown.js (the safe Markdown renderer).
 * Run from the project root with:   node --test frontend/tests/
 * Needs Node.js 18 or newer. No npm packages required.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const SafeMarkdown = require("../js/markdown.js");

const render = SafeMarkdown.render;

test("script tags are escaped, never executed", () => {
  const html = render("Hello <script>alert('x')</script>");
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
});

test("HTML attributes with event handlers are escaped", () => {
  const html = render('<img src=x onerror="alert(1)">');
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;img"));
});

test("only http(s) links become anchors", () => {
  assert.match(render("[docs](https://fastapi.tiangolo.com)"), /<a href="https:\/\/fastapi.tiangolo.com" target="_blank" rel="noopener noreferrer">docs<\/a>/);
  const js = render("[click](javascript:alert(1))");
  assert.ok(!js.includes("<a"));
});

test("quotes in link URLs cannot break out of the attribute", () => {
  const html = render('[x](https://a.com/"onmouseover="alert(1))');
  assert.ok(!/href="[^"]*"\s*onmouseover/.test(html));
});

test("headings are rendered at level 3 or below", () => {
  assert.equal(render("# Title"), "<h3>Title</h3>");
  assert.equal(render("#### Small"), "<h4>Small</h4>");
});

test("headingOffset keeps a document outline", () => {
  assert.equal(render("# A\n## B\n### C", { headingOffset: 2 }), "<h3>A</h3>\n<h4>B</h4>\n<h5>C</h5>");
});

test("double underscores in identifiers are not turned into bold", () => {
  assert.equal(render("Use __init__ and __name__ here"), "<p>Use __init__ and __name__ here</p>");
});

test("code blocks keep their content escaped and get a language tag", () => {
  const html = render("```python\nif a < b:\n    print('<b>')\n```");
  assert.equal(html, '<pre data-language="python"><code>if a &lt; b:\n    print(&#39;&lt;b&gt;&#39;)</code></pre>');
});

test("inline formatting", () => {
  assert.equal(render("**bold** and *italic* and `x<y`"), "<p><strong>bold</strong> and <em>italic</em> and <code>x&lt;y</code></p>");
  assert.equal(render("snake_case_name stays"), "<p>snake_case_name stays</p>");
});

test("formatting markers inside code spans are left alone", () => {
  assert.equal(render("`**not bold**`"), "<p><code>**not bold**</code></p>");
});

test("bullet, numbered and nested lists", () => {
  assert.equal(render("- one\n- two"), "<ul><li>one</li><li>two</li></ul>");
  assert.equal(render("1. one\n2. two"), "<ol><li>one</li><li>two</li></ol>");
  assert.equal(render("- one\n  - inner\n- two"), "<ul><li>one<ul><li>inner</li></ul></li><li>two</li></ul>");
});

test("tables", () => {
  const html = render("| A | B |\n|---|---|\n| 1 | <b>2</b> |");
  assert.ok(html.includes("<th>A</th>"));
  assert.ok(html.includes("<td>&lt;b&gt;2&lt;/b&gt;</td>"));
});

test("blockquotes and paragraphs", () => {
  assert.equal(render("> note"), "<blockquote><p>note</p></blockquote>");
  assert.equal(render("line one\nline two\n\nnext"), "<p>line one line two</p>\n<p>next</p>");
});

test("empty and missing input", () => {
  assert.equal(render(""), "");
  assert.equal(render(null), "");
});
