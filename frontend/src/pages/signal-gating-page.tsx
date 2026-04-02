import { Link } from "react-router-dom";

import { Badge, Card, PageHeader, SectionTitle } from "../components/ui";

export function SignalGatingPage() {
  return (
    <>
      <PageHeader
        kicker="Research"
        title="Signal gating"
        subtitle="This subsection separates review data from the tuning job itself. Use decision samples to inspect evidence, then use the gating job page to change parameters and inspect run history."
      />

      <div className="stack-page">
        <section className="card-grid">
          <Card>
            <SectionTitle
              kicker="Review"
              title="Decision samples"
              subtitle="Review near-misses, actionable cases, and plan-level evidence."
            />
            <div className="helper-text">This page is the review surface for samples and can be reused for future research beyond gating.</div>
            <div className="cluster top-gap-small">
              <Link to="/research/signal-gating/decision-samples" className="button-secondary">Open samples</Link>
              <Badge tone="info">review</Badge>
            </div>
          </Card>

          <Card>
            <SectionTitle
              kicker="Job"
              title="Gating tuning"
              subtitle="Edit the active gating controls, run tuning, and inspect the job history and candidate results."
            />
            <div className="helper-text">This page holds the operational tuning workflow for signal gating.</div>
            <div className="cluster top-gap-small">
              <Link to="/research/signal-gating/gating-job" className="button-secondary">Open tuning job</Link>
              <Badge tone="ok">job</Badge>
            </div>
          </Card>
        </section>
      </div>
    </>
  );
}
