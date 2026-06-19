// app/[brand]/[year]/[model]/page.js
import { fetchModels } from '@/utils/api';
import NodeList from '@/components/NodeList';
import Breadcrumb from '@/components/Breadcrumb';

export default async function ModelPage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);
  const nodes = await fetchModels(brand, parseInt(year), model);

  return (
    <div className="container">
      <Breadcrumb brand={brand} year={year} model={model} />
      <h1>{decodeURIComponent(model)}</h1>
      <p className="subtitle">Select a section to explore</p>
      <NodeList 
        nodes={nodes} 
        brand={brand} 
        year={year} 
        model={model}
        currentPath={[]}
      />
    </div>
  );
}