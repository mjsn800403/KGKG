'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { searchNodes, buildNodeHref } from '@/utils/api';

// Per-car search box with autocomplete. Input is English (matches the English
// manual data). Shows up to 5 live suggestions; ↑/↓ to move, Enter on a
// suggestion jumps straight to that node, Enter/submit otherwise opens the
// full search-results page.
export default function SearchBox({ brand, year, model, initialQuery = '' }) {
  const router = useRouter();
  const [query, setQuery] = useState(initialQuery);
  const [suggestions, setSuggestions] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const boxRef = useRef(null);

  // Debounced autocomplete fetch. Autocomplete now hits the semantic retriever
  // (which embeds the query under a GPU lock shared with the assistant), so the
  // debounce is a bit longer and we skip 1-char queries to avoid hammering it on
  // every keystroke.
  useEffect(() => {
    const q = query.trim();
    let cancelled = false;
    const t = setTimeout(async () => {
      if (q.length < 2) {
        if (!cancelled) {
          setSuggestions([]);
          setActive(-1);
        }
        return;
      }
      const results = await searchNodes(brand, year, model, q, 5);
      if (cancelled) return;
      setSuggestions(results);
      setActive(-1);
      setOpen(true);
    }, q ? 350 : 0);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [query, brand, year, model]);

  // Close the dropdown when clicking outside.
  useEffect(() => {
    function onClick(e) {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  function goToResults() {
    const q = query.trim();
    if (!q) return;
    setOpen(false);
    router.push(
      `/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}/search?q=${encodeURIComponent(q)}`
    );
  }

  function goToNode(s) {
    setOpen(false);
    router.push(buildNodeHref(brand, year, model, s.segments));
  }

  function onKeyDown(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (suggestions.length) {
        setOpen(true);
        setActive((i) => (i + 1) % suggestions.length);
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (suggestions.length) {
        setOpen(true);
        setActive((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
      }
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (open && active >= 0 && suggestions[active]) {
        goToNode(suggestions[active]);
      } else {
        goToResults();
      }
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  }

  return (
    <div className="searchbox" ref={boxRef}>
      <input
        type="text"
        dir="auto"
        className="search-input"
        placeholder="جستجو… مثلاً «فیلتر روغن» یا oil filter"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => suggestions.length && setOpen(true)}
        onKeyDown={onKeyDown}
        aria-label="Search this vehicle"
      />
      <button type="button" className="search-btn" onClick={goToResults} aria-label="Search">
        ⌕
      </button>

      {open && suggestions.length > 0 && (
        <ul className="search-suggestions" dir="ltr">
          {suggestions.map((s, i) => (
            <li
              key={`${s.path}-${i}`}
              className={`search-suggestion${i === active ? ' active' : ''}`}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => {
                e.preventDefault();
                goToNode(s);
              }}
            >
              <span className="ss-title">{s.title}</span>
              {s.segments && s.segments.length > 1 && (
                <span className="ss-path">{s.segments.slice(0, -1).join(' / ')}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
