import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const requestedHost = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "localhost";
  const host = /^[a-z0-9.-]+(?::\d+)?$/i.test(requestedHost) ? requestedHost : "localhost";
  const requestedProtocol = requestHeaders.get("x-forwarded-proto");
  const protocol = requestedProtocol === "http" || requestedProtocol === "https"
    ? requestedProtocol
    : host.startsWith("localhost") ? "http" : "https";
  const origin = `${protocol}://${host}`;
  const title = "MaryGenAI | Scientific source intelligence";
  const description = "Evidence-backed candidate retrieval infrastructure for cannabinoid medicine.";
  return {
    metadataBase: new URL(origin),
    title,
    description,
    openGraph: { title, description, type: "website", images: [{ url: `${origin}/og.png`, width: 1200, height: 630, alt: "MaryGenAI scientific source intelligence" }] },
    twitter: { card: "summary_large_image", title, description, images: [`${origin}/og.png`] },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
