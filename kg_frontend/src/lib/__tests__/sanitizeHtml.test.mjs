// sanitizeHtml: allow-list sanitiser for warehouse manual HTML.
//
// The module uses the browser's DOMParser. Node has none, so the walk/allow-list
// logic is exercised through ./miniDom.mjs, which decodes entities and
// lowercases names the way a browser parser does. Browser-only behaviour
// (HTML5 tree-construction quirks, mXSS via serialise/re-parse) is out of
// reach here and is noted in miniDom.mjs.
import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { sanitizeHtml } from '../sanitizeHtml.js';
import { installMiniDom } from './miniDom.mjs';

describe('sanitizeHtml without a DOM (SSR path)', () => {
  test('falsy input renders as nothing', () => {
    assert.equal(sanitizeHtml(''), '');
    assert.equal(sanitizeHtml(null), '');
    assert.equal(sanitizeHtml(undefined), '');
  });

  test('documented SSR behaviour: input is returned UNCHANGED when DOMParser is absent', () => {
    // Pins the documented trade-off (sanitizeHtml.js:64-66): during a server
    // render nothing is stripped. Any page that server-renders warehouse HTML
    // through ContentRenderer/StackedContent ships it unsanitised.
    assert.equal(typeof globalThis.DOMParser, 'undefined');
    const dirty = '<img src=x onerror=alert(1)>';
    assert.equal(sanitizeHtml(dirty), dirty);
  });
});

describe('sanitizeHtml with a DOM', () => {
  let uninstall;
  before(() => { uninstall = installMiniDom(); });
  after(() => uninstall());

  const clean = (s) => sanitizeHtml(s);
  const noJs = (out) => {
    assert.doesNotMatch(out, /<script/i);
    assert.doesNotMatch(out, /\son[a-z]+\s*=/i);
    assert.doesNotMatch(out, /javascript\s*:/i);
    assert.doesNotMatch(out, /alert\(/);
  };

  describe('script and active-content elements', () => {
    test('<script> is dropped together with its body (no "alert(1)" text left behind)', () => {
      const out = clean('<p>before</p><script>alert(1)</script><p>after</p>');
      assert.equal(out, '<p>before</p><p>after</p>');
    });

    test('uppercase / attributed <SCRIPT> is dropped as well', () => {
      const out = clean('<SCRIPT type="text/javascript" src="//evil.example/x.js"></SCRIPT>ok');
      assert.equal(out, 'ok');
    });

    for (const tag of ['style', 'iframe', 'object', 'embed', 'form', 'textarea', 'template',
      'noscript', 'button', 'select', 'meta', 'link', 'base', 'title']) {
      test(`<${tag}> is removed with its content`, () => {
        const html = ['embed', 'meta', 'link', 'base'].includes(tag)
          ? `<p>a</p><${tag} src="javascript:alert(1)" href="//evil.example"><p>b</p>`
          : `<p>a</p><${tag} src="javascript:alert(1)">payload-${tag}</${tag}><p>b</p>`;
        const out = clean(html);
        assert.equal(out, '<p>a</p><p>b</p>');
      });
    }

    test('<input> is removed', () => {
      assert.equal(clean('<p>x<input value="y" onfocus="alert(1)" autofocus></p>'), '<p>x</p>');
    });

    test('HTML comments are removed (no conditional-comment smuggling)', () => {
      const out = clean('<p>a<!--[if IE]><script>alert(1)</script><![endif]--></p>');
      assert.equal(out, '<p>a</p>');
    });
  });

  describe('event-handler attributes', () => {
    test('on* handlers are stripped from allowed tags, safe attributes stay', () => {
      const out = clean('<img src="a.png" alt="شکل ۱" onerror="alert(1)" ONLOAD="alert(2)" onMouseOver="x()">');
      assert.equal(out, '<img src="a.png" alt="شکل ۱">');
    });

    test('handler on a nested element inside an UNKNOWN wrapper is still stripped', () => {
      // The unknown <custom> is unwrapped, and its children must be walked too.
      const out = clean('<div><custom><font><img src="x.png" onerror="alert(1)"></font></custom></div>');
      assert.equal(out, '<div><img src="x.png"></div>');
    });

    test('attributes outside the allow-list are dropped (srcset, formaction, target, xmlns)', () => {
      const out = clean('<a href="pages/1.html" target="_blank" formaction="javascript:alert(1)">x</a>' +
        '<img src="a.png" srcset="javascript:alert(1) 1x">');
      assert.equal(out, '<a href="pages/1.html">x</a><img src="a.png">');
    });
  });

  describe('URL schemes in href/src', () => {
    const blocked = [
      'javascript:alert(1)',
      'JaVaScRiPt:alert(1)',
      '  javascript:alert(1)  ',
      '\njavascript:alert(1)',
      '&#106;avascript:alert(1)',           // entity-encoded first letter
      '&#x6A;&#x61;vascript:alert(1)',
      'javascript&colon;alert(1)',           // named-entity colon
      'vbscript:msgbox(1)',
      'data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
      'data:application/javascript,alert(1)',
      'file:///etc/passwd',
    ];
    for (const url of blocked) {
      test(`href "${url.trim()}" is removed`, () => {
        const out = clean(`<a href="${url}" class="x">link</a>`);
        assert.equal(out, '<a class="x">link</a>');
      });
    }

    test('javascript: in <img src> is removed', () => {
      assert.equal(clean('<img src="javascript:alert(1)" alt="a">'), '<img alt="a">');
    });

    const kept = [
      'pages/1234.html#section-2',      // in-manual cross-link (must survive)
      '#anchor',
      '/car/toyota/camry',
      '../images/fig1.png',
      'https://example.com/a?b=c',
      'http://example.com/',
      'mailto:support@example.com',
      'tel:+982100000000',
    ];
    for (const url of kept) {
      test(`href "${url}" is kept`, () => {
        const out = clean(`<a href="${url}">l</a>`);
        assert.equal(out, `<a href="${url.replace(/&/g, '&amp;')}">l</a>`);
      });
    }

    test('data:image/* is kept for inline illustrations', () => {
      const src = 'data:image/png;base64,iVBORw0KGgo=';
      assert.equal(clean(`<img src="${src}">`), `<img src="${src}">`);
    });

    test('regression: a tab/newline INSIDE the scheme is stripped by the browser URL parser', () => {
      for (const url of ['java\tscript:alert(1)', 'java&#10;script:alert(1)', 'java&#9;script:alert(1)', '\u0001javascript:alert(1)']) {
        const out = clean(`<a href="${url}">x</a>`);
        assert.equal(out, '<a>x</a>', `kept: ${JSON.stringify(url)}`);
      }
    });
  });

  describe('SVG / MathML vectors', () => {
    test('<svg onload> is unwrapped and the handler never survives', () => {
      const out = clean('<svg onload="alert(1)"><circle r="5"></circle></svg>تست');
      assert.equal(out, 'تست');
    });

    test('<script> nested in <svg> is dropped', () => {
      const out = clean('<svg><script>alert(1)</script><p>ok</p></svg>');
      assert.equal(out, '<p>ok</p>');
    });

    test('xlink:href javascript: inside SVG <a> is dropped', () => {
      const out = clean('<svg><a xlink:href="javascript:alert(1)" href="javascript:alert(2)">x</a></svg>');
      noJs(out);
      assert.equal(out, '<a>x</a>');
    });

    test('MathML href / xlink:href vectors are dropped', () => {
      const out = clean('<math><mi xlink:href="javascript:alert(1)">x</mi><maction actiontype="statusline">y</maction></math>');
      noJs(out);
      assert.equal(out, 'xy');
    });

    test('<svg><animate> attributeName/values trick cannot add an href', () => {
      const out = clean('<svg><a><animate attributeName="href" values="javascript:alert(1)"></animate><text>c</text></a></svg>');
      noJs(out);
      assert.equal(out, '<a>c</a>');
    });
  });

  describe('style attribute', () => {
    const bad = [
      'width: expression(alert(1))',
      'background: url(javascript:alert(1))',
      'background-image: URL( "https://tracker.example/p.gif" )',
      'color: red; x: javascript:alert(1)',
    ];
    for (const css of bad) {
      test(`style "${css}" is removed`, () => {
        assert.equal(clean(`<td style='${css}'>v</td>`), '<td>v</td>');
      });
    }

    test('benign layout style is kept', () => {
      assert.equal(clean('<td style="width: 50%; text-align: center">v</td>'),
        '<td style="width: 50%; text-align: center">v</td>');
    });
  });

  describe('nested / malformed markup', () => {
    test('unknown wrappers are unwrapped, their content survives', () => {
      assert.equal(clean('<font color="red"><b>گشتاور</b> 25 N·m</font>'), '<b>گشتاور</b> 25 N·m');
    });

    test('unclosed tags do not let a handler escape', () => {
      const out = clean('<div><p>text<img src=x onerror=alert(1)//>');
      noJs(out);
      assert.equal(out, '<div><p>text<img src="x"></p></div>');
    });

    test('split/obfuscated script tag does not reassemble into a script', () => {
      const out = clean('<scr<script>x</script>ipt>alert(1)</scr<script>x</script>ipt>');
      assert.doesNotMatch(out, /<script/i);
    });

    test('entity-encoded markup in TEXT stays text (escaped on output)', () => {
      const out = clean('<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>');
      assert.equal(out, '<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>');
    });

    test('deeply nested payload is fully walked', () => {
      const deep = '<div>'.repeat(50) + '<img src="a.png" onerror="alert(1)">' + '</div>'.repeat(50);
      const out = clean(deep);
      noJs(out);
      assert.match(out, /<img src="a.png">/);
    });
  });

  describe('legitimate manual HTML survives unchanged', () => {
    test('spec table with colspan/rowspan/class/align', () => {
      const html = '<table class="spec" border="1" cellpadding="2" cellspacing="0">' +
        '<colgroup><col width="40%"><col width="60%"></colgroup>' +
        '<thead><tr><th colspan="2" align="center">Torque Specification</th></tr></thead>' +
        '<tbody><tr><td rowspan="2" valign="top">Caliper × Mounting</td><td>34 N·m (350 kgf·cm, 25 ft·lbf)</td></tr>' +
        '<tr><td>Hint: <sup>*1</sup> <sub>a</sub></td></tr></tbody></table>';
      assert.equal(clean(html), html);
    });

    test('illustration and in-manual cross-link', () => {
      const html = '<p><img src="../images/A123456.png" alt="Illustration" width="300" height="200" title="fig"></p>' +
        '<p><a href="pages/1234.html#step-3" name="ref1" id="r1">See Removal</a></p>';
      assert.equal(clean(html), html);
    });

    test('Persian RTL text with ZWNJ, lists and definition lists', () => {
      const html = '<div dir="rtl" lang="fa"><h2>باز و بست لنت ترمز</h2>' +
        '<ol><li>چرخ را باز کنید.</li><li>پیچ‌های کالیپر را شل کنید.</li></ol>' +
        '<dl><dt>گشتاور</dt><dd>۳۴ نیوتن‌متر</dd></dl>' +
        '<ul><li><strong>هشدار:</strong> <em>از ابزار مخصوص</em> استفاده کنید.</li></ul></div>';
      assert.equal(clean(html), html);
    });
  });
});
