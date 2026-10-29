// Minimal DOMParser stand-in for unit-testing sanitizeHtml under Node, which
// has no DOM. It implements only what the sanitiser touches (childNodes,
// nodeType, tagName, attributes, removeAttribute, remove, insertBefore,
// firstChild, innerHTML) plus an HTML tokenizer that, like a browser, lowercases
// tag/attribute names and DECODES character references in text and attribute
// values before the sanitiser sees them.
//
// It is NOT an HTML5 tree builder: no foster parenting, no implicit closes, no
// foreign-content namespaces, no re-parse. Mutation-XSS (mXSS) that depends on
// the browser's serialise/re-parse round trip cannot be exercised here; those
// cases need a real browser (e.g. a Playwright test).

const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
  'link', 'meta', 'source', 'track', 'wbr']);
const RAW_TEXT = new Set(['script', 'style', 'textarea', 'title', 'iframe',
  'noscript', 'xmp', 'noembed', 'noframes']);
const IGNORED = new Set(['html', 'body']);

const NAMED = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
  colon: ':', Tab: '\t', NewLine: '\n', lpar: '(', rpar: ')', sol: '/',
};

export function decodeEntities(s) {
  return s.replace(/&(#[xX][0-9a-fA-F]+|#\d+|[A-Za-z]+);?/g, (m, body) => {
    if (body[0] === '#') {
      const cp = body[1] === 'x' || body[1] === 'X'
        ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
      return Number.isFinite(cp) ? String.fromCodePoint(cp) : m;
    }
    return Object.prototype.hasOwnProperty.call(NAMED, body) ? NAMED[body] : m;
  });
}

class Node {
  constructor(nodeType) {
    this.nodeType = nodeType;
    this.parentNode = null;
    this.childNodes = [];
  }

  get firstChild() { return this.childNodes[0] || null; }

  remove() {
    if (!this.parentNode) return;
    const sib = this.parentNode.childNodes;
    sib.splice(sib.indexOf(this), 1);
    this.parentNode = null;
  }

  appendChild(n) {
    n.remove();
    n.parentNode = this;
    this.childNodes.push(n);
    return n;
  }

  insertBefore(n, ref) {
    n.remove();
    const i = this.childNodes.indexOf(ref);
    n.parentNode = this;
    this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, n);
    return n;
  }
}

class Text extends Node {
  constructor(data) { super(3); this.data = data; }
}

class Comment extends Node {
  constructor(data) { super(8); this.data = data; }
}

const escText = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/ /g, '&nbsp;');
const escAttr = (s) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
  .replace(/ /g, '&nbsp;');

class Element extends Node {
  constructor(tag) {
    super(1);
    this.localName = tag;
    this.tagName = tag.toUpperCase();
    this._attrs = [];
  }

  get attributes() { return this._attrs.slice(); }

  getAttribute(name) {
    const a = this._attrs.find((x) => x.name === name.toLowerCase());
    return a ? a.value : null;
  }

  setAttribute(name, value) {
    const n = name.toLowerCase();
    const a = this._attrs.find((x) => x.name === n);
    if (a) a.value = String(value); else this._attrs.push({ name: n, value: String(value) });
  }

  removeAttribute(name) {
    const n = name.toLowerCase();
    this._attrs = this._attrs.filter((x) => x.name !== n);
  }

  get outerHTML() {
    const attrs = this._attrs.map((a) => ` ${a.name}="${escAttr(a.value)}"`).join('');
    if (VOID.has(this.localName)) return `<${this.localName}${attrs}>`;
    return `<${this.localName}${attrs}>${this.innerHTML}</${this.localName}>`;
  }

  get innerHTML() {
    const raw = RAW_TEXT.has(this.localName);
    return this.childNodes.map((c) => {
      if (c.nodeType === 3) return raw ? c.data : escText(c.data);
      if (c.nodeType === 8) return `<!--${c.data}-->`;
      return c.outerHTML;
    }).join('');
  }
}

const ATTR_RE = /([^\s"'>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;

function parseInto(body, html) {
  const stack = [body];
  const top = () => stack[stack.length - 1];
  let i = 0;
  while (i < html.length) {
    if (html.startsWith('<!--', i)) {
      const end = html.indexOf('-->', i + 4);
      const stop = end < 0 ? html.length : end;
      top().appendChild(new Comment(html.slice(i + 4, stop)));
      i = end < 0 ? html.length : end + 3;
      continue;
    }
    if (html[i] === '<' && html[i + 1] === '!') {        // doctype etc.
      const end = html.indexOf('>', i);
      i = end < 0 ? html.length : end + 1;
      continue;
    }
    const close = /^<\/([A-Za-z][^\s/>]*)[^>]*>/.exec(html.slice(i));
    if (close) {
      const tag = close[1].toLowerCase();
      i += close[0].length;
      if (IGNORED.has(tag)) continue;
      for (let k = stack.length - 1; k > 0; k--) {
        if (stack[k].localName === tag) { stack.length = k; break; }
      }
      continue;
    }
    const open = /^<([A-Za-z][^\s/>]*)((?:[^>"']|"[^"]*"|'[^']*')*)>/.exec(html.slice(i));
    if (open) {
      const tag = open[1].toLowerCase();
      i += open[0].length;
      if (IGNORED.has(tag)) continue;
      const el = new Element(tag);
      let m;
      ATTR_RE.lastIndex = 0;
      const attrSrc = open[2].replace(/\/\s*$/, '');
      while ((m = ATTR_RE.exec(attrSrc))) {
        const name = m[1].toLowerCase();
        if (el.getAttribute(name) !== null) continue;      // first wins, as in HTML
        const v = m[2] ?? m[3] ?? m[4] ?? '';
        el._attrs.push({ name, value: decodeEntities(v) });
      }
      top().appendChild(el);
      if (RAW_TEXT.has(tag)) {
        const endRe = new RegExp(`</${tag}\\s*>`, 'i');
        const rest = html.slice(i);
        const e = endRe.exec(rest);
        const text = e ? rest.slice(0, e.index) : rest;
        if (text) el.appendChild(new Text(text));
        i += e ? e.index + e[0].length : rest.length;
      } else if (!VOID.has(tag) && !/\/\s*$/.test(open[2])) {
        stack.push(el);
      }
      continue;
    }
    const next = html.indexOf('<', i + 1);
    const stop = next < 0 ? html.length : next;
    top().appendChild(new Text(decodeEntities(html.slice(i, stop))));
    i = stop;
  }
}

export class MiniDOMParser {
  parseFromString(str) {
    const body = new Element('body');
    parseInto(body, String(str));
    return { body };
  }
}

/** Install the shim as the globals sanitizeHtml checks; returns an uninstaller. */
export function installMiniDom() {
  const prevWindow = globalThis.window;
  const prevParser = globalThis.DOMParser;
  globalThis.window = globalThis;
  globalThis.DOMParser = MiniDOMParser;
  return () => {
    if (prevWindow === undefined) delete globalThis.window; else globalThis.window = prevWindow;
    if (prevParser === undefined) delete globalThis.DOMParser; else globalThis.DOMParser = prevParser;
  };
}
