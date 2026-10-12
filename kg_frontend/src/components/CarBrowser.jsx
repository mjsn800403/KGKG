'use client';

// Two-pane car browsing layout: the persistent car-tree sidebar on one side and
// the current page's content (cards, a single document, or a flattened subtree)
// on the other. The server page renders the content and passes it as children.
import CarNav from './CarNav';

export default function CarBrowser({ brand, year, model, currentPath = [], children }) {
  return (
    <div className="car-browse">
      <CarNav brand={brand} year={year} model={model} currentPath={currentPath} />
      <div className="car-content">{children}</div>
    </div>
  );
}
