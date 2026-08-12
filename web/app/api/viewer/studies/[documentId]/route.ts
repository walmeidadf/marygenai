import { demoStudies } from "../../../../lib/demo-data";
import {
  proxyViewerResponse,
  viewerUpstreamBase,
  viewerUpstreamHeaders,
} from "../../../../lib/viewer-upstream";

export async function GET(
  _request: Request,
  context: { params: Promise<{ documentId: string }> },
) {
  const { documentId } = await context.params;
  const upstream = viewerUpstreamBase();
  if (upstream) {
    try {
      const response = await fetch(
        `${upstream}/studies/${encodeURIComponent(documentId)}`,
        { cache: "no-store", headers: viewerUpstreamHeaders() },
      );
      return proxyViewerResponse(response);
    } catch {
      return Response.json({ detail: "The read-only dataset service is temporarily unavailable." }, { status: 503 });
    }
  }
  const study = demoStudies.find((item) => item.documentId === documentId);
  if (!study) return Response.json({ detail: "Study not found in this snapshot." }, { status: 404 });
  return Response.json(study);
}
