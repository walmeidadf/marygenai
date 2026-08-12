import { demoMeta } from "../../../lib/demo-data";

export async function GET() {
  const upstream = process.env.MARYGENAI_VIEWER_API_BASE_URL;
  if (upstream) {
    try {
      const response = await fetch(`${upstream.replace(/\/$/, "")}/api/viewer/meta`, {
        headers: { accept: "application/json" },
      });
      return new Response(response.body, {
        status: response.status,
        headers: { "content-type": response.headers.get("content-type") ?? "application/json" },
      });
    } catch {
      return Response.json({ detail: "The read-only dataset service is temporarily unavailable." }, { status: 503 });
    }
  }
  return Response.json(demoMeta);
}
