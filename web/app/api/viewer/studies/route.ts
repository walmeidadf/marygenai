import { searchDemoStudies } from "../../../lib/demo-data";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const upstream = process.env.MARYGENAI_VIEWER_API_BASE_URL;
  if (upstream) {
    try {
      const target = `${upstream.replace(/\/$/, "")}/api/viewer/studies?${url.searchParams}`;
      const response = await fetch(target, { headers: { accept: "application/json" } });
      return new Response(response.body, {
        status: response.status,
        headers: { "content-type": response.headers.get("content-type") ?? "application/json" },
      });
    } catch {
      return Response.json({ detail: "The read-only dataset service is temporarily unavailable." }, { status: 503 });
    }
  }
  return Response.json(searchDemoStudies(url.searchParams));
}
