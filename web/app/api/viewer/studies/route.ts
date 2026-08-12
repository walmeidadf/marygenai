import { searchDemoStudies } from "../../../lib/demo-data";
import {
  proxyViewerResponse,
  viewerUpstreamBase,
  viewerUpstreamHeaders,
} from "../../../lib/viewer-upstream";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const upstream = viewerUpstreamBase();
  if (upstream) {
    try {
      const target = `${upstream}/studies?${url.searchParams}`;
      const response = await fetch(target, {
        cache: "no-store",
        headers: viewerUpstreamHeaders(),
      });
      return proxyViewerResponse(response);
    } catch {
      return Response.json({ detail: "The read-only dataset service is temporarily unavailable." }, { status: 503 });
    }
  }
  return Response.json(searchDemoStudies(url.searchParams));
}
