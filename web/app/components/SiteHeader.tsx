import Link from "next/link";

export function Brand() {
  return (
    <span className="brand-lockup">
      <span className="brand-mark" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span>
        <strong>MaryGenAI</strong>
        <small>scientific source intelligence</small>
      </span>
    </span>
  );
}

export function SiteHeader() {
  return (
    <header className="site-header">
      <div className="shell header-inner">
        <Link href="/" className="brand-link" aria-label="MaryGenAI home">
          <Brand />
        </Link>
        <nav className="primary-nav" aria-label="Primary navigation">
          <Link href="/#how-it-works">How it works</Link>
          <Link href="/#current-state">Current state</Link>
          <Link href="/#collaborate">Collaborate</Link>
          <Link href="/dataset" className="nav-cta">
            Dataset Viewer
          </Link>
        </nav>
      </div>
    </header>
  );
}
