import { demoMeta } from "../../../lib/demo-data";
import {
  proxyViewerResponse,
  viewerUpstreamBase,
  viewerUpstreamHeaders,
} from "../../../lib/viewer-upstream";

export async function GET() {
  const upstream = viewerUpstreamBase();
  if (upstream) {
    try {
      const response = await fetch(`${upstream}/meta`, {
        cache: "no-store",
        headers: viewerUpstreamHeaders(),
      });
      return proxyViewerResponse(response);
    } catch {
      return Response.json({ detail: "The read-only dataset service is temporarily unavailable." }, { status: 503 });
    }
  }
  return Response.json(demoMeta);
}
