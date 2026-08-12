export function TrustBadge({ reviewState }: { reviewState: string }) {
  const reviewed = reviewState === "human_reviewed";
  return (
    <span className={`trust-badge ${reviewed ? "trust-reviewed" : "trust-candidate"}`}>
      <span aria-hidden="true" />
      {reviewed ? "Human reviewed" : "AI candidate · needs review"}
    </span>
  );
}
