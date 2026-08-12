export function viewerUpstreamBase() {
  const configured = process.env.MARYGENAI_VIEWER_API_BASE_URL?.replace(/\/$/, "");
  if (!configured) return null;
  return configured.endsWith("/api/viewer")
    ? configured
    : `${configured}/api/viewer`;
}

export function viewerUpstreamHeaders() {
  const token = process.env.MARYGENAI_VIEWER_API_BEARER_TOKEN;
  return {
    accept: "application/json",
    ...(token ? { authorization: `Bearer ${token}` } : {}),
  };
}

export function proxyViewerResponse(response: Response) {
  return new Response(response.body, {
    status: response.status,
    headers: {
      "cache-control": "private, no-store",
      "content-type": response.headers.get("content-type") ?? "application/json",
      "x-content-type-options": "nosniff",
    },
  });
}
