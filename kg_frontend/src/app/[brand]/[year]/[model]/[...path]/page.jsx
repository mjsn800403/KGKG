// app/[brand]/[year]/[model]/[[...path]]/page.js
import { fetchNodes } from '@/utils/api';
import NodeList from '@/components/NodeList';
import Breadcrumb from '@/components/Breadcrumb';
import ContentRenderer from '@/components/ContentRenderer';

export default async function NodePage({ params }) {
  const raw = await params;
  const brand = decodeURIComponent(raw.brand);
  const year = raw.year;
  const model = decodeURIComponent(raw.model);
  const pathArray = (raw.path || []).map(decodeURIComponent);

  let nodes = [];
  let error = null;
  let isContentPage = false;

  try {
    nodes = await fetchNodes(
      brand,
      parseInt(year),
      model,
      pathArray
    );
    
    // Check if this is a leaf node with content
    // A leaf node typically has content and no children
    isContentPage = nodes && 
                    nodes.length === 1 && 
                    nodes[0]?.content && 
                    (!nodes[0]?.children || nodes[0].children.length === 0);
                    
  } catch (err) {
    console.error('Error fetching nodes:', err);
    error = err.message;
  }

  // Handle errors
  if (error) {
    return (
      <div className="container">
        <h1>Error</h1>
        <div className="error-box">
          <p>Failed to load content: {error}</p>
          <p>Please check that the Django server is running at http://127.0.0.1:8000</p>
          <a href={`/${encodeURIComponent(brand)}`} className="back-link">← Go back</a>
        </div>
      </div>
    );
  }

  // Determine what to display
  // Case 1: We're at the root model page (/brand/year/model/)
  const isRootModel = pathArray.length === 0;
  
  // Case 2: We're at a leaf node with content
  const isLeafWithContent = isContentPage;

  return (
    <div className="container">
      <Breadcrumb 
        brand={brand} 
        year={year} 
        model={model} 
        path={pathArray}
      />
      
      {isLeafWithContent ? (
        // Leaf node with content
        <>
          <h1>{nodes[0].title}</h1>
          <ContentRenderer content={nodes[0].content} brand={brand} year={year} model={model} />
        </>
      ) : (
        // Directory/listing page (either root model or intermediate path)
        <>
          <h1>
            {isRootModel 
              ? decodeURIComponent(model)
              : decodeURIComponent(pathArray[pathArray.length - 1])
            }
          </h1>
          
          {nodes && nodes.length > 0 ? (
            <NodeList 
              nodes={nodes} 
              brand={brand} 
              year={year} 
              model={model}
              currentPath={pathArray}
            />
          ) : (
            <div className="empty-state">
              <p>No items found in this section.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}