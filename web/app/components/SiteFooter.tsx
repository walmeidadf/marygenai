import Link from "next/link";
import { Brand } from "./SiteHeader";

const repository = "https://github.com/walmeidadf/marygenai";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="shell footer-grid">
        <div>
          <Brand />
          <p className="footer-note">
            Candidate scientific metadata for discovery and inspection. Not medical advice.
          </p>
        </div>
        <nav aria-label="Footer navigation">
          <Link href="/dataset">Dataset Viewer</Link>
          <a href={`${repository}/tree/main/docs`}>Documentation</a>
          <a href={repository}>Repository</a>
        </nav>
        <p className="license-note">
          No software or data license has been published. Public visibility does not grant
          redistribution rights.
        </p>
      </div>
    </footer>
  );
}
