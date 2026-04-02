import { Link } from "react-router-dom";

import { Badge, Card, PageHeader, SectionTitle } from "../components/ui";

export function ResearchPage() {
  return (
    <>
      <PageHeader
        kicker="Research"
        title="Calibration, tuning, and replay work lives here."
        subtitle="Use this area for review surfaces that help you learn from past decisions before changing how the planner behaves. Decision samples are available now; plan-generation tuning and backtesting will live here too."
      />

      <div className="stack-page">
        <section className="card-grid">
          <Card>
            <SectionTitle
              kicker="Available now"
              title="Decision samples"
              subtitle="Review near-misses, actionable cases, and the evidence that may feed future tuning and replay workflows."
            />
            <div className="helper-text">This is the shared evidence surface. It is not exclusive to signal gating, even though gating uses it today.</div>
            <div className="cluster top-gap-small">
              <Link to="/research/decision-samples" className="button-secondary">Open decision samples</Link>
              <Badge tone="info">active</Badge>
            </div>
          </Card>

          <Card>
            <SectionTitle
              kicker="Available now"
              title="Signal gating"
              subtitle="The signal-gating subsection collects the tuning job and supporting review links so the controls stay grouped without owning the samples themselves."
            />
            <div className="helper-text">Use the gating subsection when you want to adjust live gating parameters or inspect tuning history.</div>
            <div className="cluster top-gap-small">
              <Link to="/research/signal-gating" className="button-secondary">Open signal gating</Link>
              <Badge tone="info">active</Badge>
            </div>
          </Card>

          <Card>
            <SectionTitle
              kicker="Planned"
              title="Plan generation tuning"
              subtitle="A future page for experimenting with generation rules, shortlist thresholds, and planner behavior separately from sample review."
            />
            <div className="helper-text">This slot is reserved for research on proposal-generation tuning once we split it out from decision-sample review.</div>
            <div className="cluster top-gap-small">
              <Badge tone="neutral">coming soon</Badge>
            </div>
          </Card>

          <Card>
            <SectionTitle
              kicker="Planned"
              title="Backtesting"
              subtitle="A future page for historical replay, comparison, and scenario analysis."
            />
            <div className="helper-text">This slot is reserved for replay-style experiments and historical validation workflows.</div>
            <div className="cluster top-gap-small">
              <Badge tone="neutral">coming soon</Badge>
            </div>
          </Card>
        </section>
      </div>
    </>
  );
}
