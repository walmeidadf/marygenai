import { demoStudies } from "../../../../lib/demo-data";

export async function GET(
  _request: Request,
  context: { params: Promise<{ documentId: string }> },
) {
  const { documentId } = await context.params;
  const upstream = process.env.MARYGENAI_VIEWER_API_BASE_URL;
  if (upstream) {
    try {
      const response = await fetch(
        `${upstream.replace(/\/$/, "")}/api/viewer/studies/${encodeURIComponent(documentId)}`,
        { headers: { accept: "application/json" } },
      );
      return new Response(response.body, {
        status: response.status,
        headers: { "content-type": response.headers.get("content-type") ?? "application/json" },
      });
    } catch {
      return Response.json({ detail: "The read-only dataset service is temporarily unavailable." }, { status: 503 });
    }
  }
  const study = demoStudies.find((item) => item.documentId === documentId);
  if (!study) return Response.json({ detail: "Study not found in this snapshot." }, { status: 404 });
  return Response.json(study);
}
