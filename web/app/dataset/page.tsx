import type { Metadata } from "next";
import { SiteFooter } from "../components/SiteFooter";
import { SiteHeader } from "../components/SiteHeader";
import { DatasetViewer } from "./DatasetViewer";

export const metadata: Metadata = {
  title: "Dataset Viewer | MaryGenAI",
  description: "Inspect read-only AI-classified candidate records, evidence, uncertainty, and provenance.",
};

export default function DatasetPage() {
  return (
    <>
      <a className="skip-link" href="#dataset-results">Skip to dataset results</a>
      <SiteHeader />
      <DatasetViewer />
      <SiteFooter />
    </>
  );
}
