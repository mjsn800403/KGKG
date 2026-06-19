// components/NodeList.js
import NodeItem from './NodeItem';

export default function NodeList({ nodes, brand, year, model, currentPath }) {
  if (!nodes || nodes.length === 0) {
    return (
      <div className="empty-state">
        <p>No items found in this section.</p>
      </div>
    );
  }

  return (
    <div className="node-list">
      {nodes.map((node) => (
        <NodeItem
          key={node.id}
          node={node}
          brand={brand}
          year={year}
          model={model}
          currentPath={currentPath}
        />
      ))}
    </div>
  );
}