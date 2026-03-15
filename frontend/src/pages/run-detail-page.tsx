import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getJson } from "../api";
import { WorkflowRunResults } from "../components/workflow-run-results";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle } from "../components/ui";
import type { RunDetailResponse } from "../types";
import { diagnosticsMessages, directionTone, formatDate, formatDuration, isRecord, jobTypeLabel, parseJsonRecord, recommendationStateTone, runTone } from "../utils";

const DOC_BASE = "https://github.com/NLK511/essepoitenepenti/blob/main/docs/recommendation-methodology.md";

const INFO_DESCRIPTIONS = {
  trading: {
    description: "Review the entry, stop loss, and take profit structure that defines the proposal",
    link: `${DOC_BASE}#proposal-structure`,
  },
  summary: {
    description: "See how summary methods and enhanced sentiment characterise the recommendation narrative",
    link: `${DOC_BASE}#summary-and-sentiment`,
  },
  diagnostics: {
    description: "Dive into structured signals and diagnostic warnings recorded for this recommendation",
    link: `${DOC_BASE}#structured-diagnostics`,
  },
  messages: {
    description: "Understand warning classification that operators see when data arrives incomplete",
    link: `${DOC_BASE}#diagnostics`,
  },
  raw: {
    description: "Inspect the raw JSON emitted by the pipeline if you need the un-parsed payload",
    link: `${DOC_BASE}#raw-output`,
  },
  contextFlags: {
    description: "Context flags flag key conditions that influenced this proposal",
    link: `${DOC_BASE}#context-flags`,
  },
  highlights: {
    description: "Normalized highlight metrics show how feature vectors compare across runs",
    link: `${DOC_BASE}#feature-vectors`,
  },
  aggregations: {
    description: "Aggregator totals summarize counts or dollar amounts used in scoring",
    link: `${DOC_BASE}#aggregations`,
  },
  weights: {
    description: "Confidence weights show how each signal contributed to the final recommendation",
    link: `${DOC_BASE}#confidence-weights`,
  },
  news: {
    description: "News coverage aggregates headline data and sentiment for this ticker",
    link: `${DOC_BASE}#news-coverage`,
  },
  coverage: {
    description: "Understand why sentiment stayed neutral by reviewing keyword hits and missing coverage",
    link: `${DOC_BASE}#sentiment-coverage`,
  },
  fieldEntry: {
    description: "Entry price defines where the system would enter the position",
    link: `${DOC_BASE}#proposal-structure`,
  },
  fieldStop: {
    description: "Stop loss caps downside risk for this recommendation",
    link: `${DOC_BASE}#proposal-structure`,
  },
  fieldTake: {
    description: "Take profit outlines the target level for the trade",
    link: `${DOC_BASE}#proposal-structure`,
  },
  summaryMethod: {
    description: "The summary method tells you which service provided this narrative",
    link: `${DOC_BASE}#summary-and-sentiment`,
  },
};

function InfoBadge({ description, link }: { description: string; link: string }) {
  return (
    <a
      className="info-badge"
      href={link}
      target="_blank"
      rel="noreferrer"
      title={description}
    >
      ?
    </a>
  );
}

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const [detail, setDetail] = useState<RunDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      if (!runId) {
        setError("Run id is missing");
        return;
      }
      try {
        setError(null);
        setDetail(await getJson<RunDetailResponse>(`/api/runs/${runId}`));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load run");
      }
    }
    void load();
  }, [runId]);

  return (
    <>
      <PageHeader
        kicker="Run detail"
        title={detail ? `Run #${detail.run.id}` : "Run detail"}
        subtitle="A run is one job execution. This page focuses on execution state and the recommendations produced by that run, not on treating the run itself as the trade output."
        actions={
          <>
            <Link to="/jobs/debugger" className="button-secondary">Back to debugger</Link>
            <Link to="/jobs/history" className="button-subtle">Open history</Link>
          </>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {!detail && !error ? <LoadingState message="Loading run detail…" /> : null}
      {detail ? (
        <div className="stack-page">
          <Card>
            <div className="cluster">
              <Badge tone={runTone(detail.run.status)}>{detail.run.status}</Badge>
              <Badge>Job {detail.run.job_id}</Badge>
              <Badge>{jobTypeLabel(detail.run.job_type)}</Badge>
              <Badge>{formatDuration(detail.run.duration_seconds)}</Badge>
            </div>
            <div className="helper-text">Created {formatDate(detail.run.created_at)}</div>
            <div className="helper-text">Scheduled slot {formatDate(detail.run.scheduled_for)}</div>
            <div className="helper-text">Started {formatDate(detail.run.started_at)}</div>
            <div className="helper-text">Completed {formatDate(detail.run.completed_at)}</div>
            {detail.run.error_message ? <div className="alert alert-danger top-gap-small">{detail.run.error_message}</div> : null}
            {detail.run.timing_json ? (
              <div className="helper-text top-gap-small">Timing data is available but hidden on this page to keep the view focused on the trade proposal.</div>
            ) : null}
          </Card>

          <Card>
            <SectionTitle kicker="Produced output" title={detail.run.job_type === "proposal_generation" ? "Recommendations created by this run" : "Workflow result stored on the run"} />
            {detail.run.job_type === "proposal_generation" ? (
              <>
                {detail.outputs.length === 0 ? <EmptyState message="No recommendations stored for this run." /> : null}
                <div className="stack-page">
                  {detail.outputs.map((output) => {
                    const item = output.recommendation;
                    const messages = diagnosticsMessages(output.diagnostics);
                    const analysis = parseJsonRecord(output.diagnostics.analysis_json);
                    const summarySection = isRecord(analysis?.summary) ? (analysis?.summary as Record<string, unknown>) : null;
                    const newsSection = isRecord(analysis?.news) ? (analysis?.news as Record<string, unknown>) : null;
                    const summaryText = typeof summarySection?.text === "string" && summarySection.text ? summarySection.text : null;
                    const summaryMethod = typeof summarySection?.method === "string" ? summarySection.method : null;
                    const summaryBackend = typeof summarySection?.backend === "string" ? summarySection.backend : null;
                    const newsDigest = (() => {
                      const digest = typeof newsSection?.digest === "string" ? newsSection.digest : summarySection?.digest;
                      return typeof digest === "string" && digest ? digest : null;
                    })();
                    const sentimentSection = isRecord(analysis?.sentiment) ? (analysis.sentiment as Record<string, unknown>) : null;
                    const enhancedSentiment = sentimentSection && isRecord(sentimentSection.enhanced) ? (sentimentSection.enhanced as Record<string, unknown>) : null;
                    const enhancedSentimentScore = enhancedSentiment && typeof enhancedSentiment.score === "number" ? enhancedSentiment.score : null;
                    const enhancedSentimentLabel = enhancedSentiment && typeof enhancedSentiment.label === "string" ? enhancedSentiment.label : null;
                    const enhancedComponents = enhancedSentiment && enhancedSentiment.components && isRecord(enhancedSentiment.components) ? (enhancedSentiment.components as Record<string, unknown>) : null;
                    const summaryMethodLabel = summaryMethod || (newsDigest ? "news_digest" : "price_only");
                    const summaryBackendLabel = summaryBackend || "news_digest";
                    const contextFlagsSection = isRecord(analysis?.context_flags) ? (analysis.context_flags as Record<string, unknown>) : null;
                    const featureVectorsSection = isRecord(analysis?.feature_vectors) ? (analysis.feature_vectors as Record<string, unknown>) : null;
                    const normalizedFeatureVectors =
                      featureVectorsSection && isRecord(featureVectorsSection.normalized)
                        ? (featureVectorsSection.normalized as Record<string, unknown>)
                        : null;
                    const aggregatorSection = isRecord(analysis?.aggregations) ? (analysis.aggregations as Record<string, unknown>) : null;
                    const confidenceWeightsSection = isRecord(analysis?.confidence_weights)
                      ? (analysis.confidence_weights as Record<string, unknown>)
                      : null;
                    const contextFlagEntries = contextFlagsSection
                      ? (Object.entries(contextFlagsSection) as [string, unknown][]).filter((entry): entry is [string, number] =>
                          typeof entry[1] === "number" && entry[1] > 0
                        )
                      : [];
                    const highlightKeys = [
                      "sentiment_score",
                      "enhanced_sentiment_score",
                      "news_point_count",
                      "context_count",
                      "polarity_trend",
                    ] as const;
                    const normalizedHighlights = highlightKeys.map((key) => {
                      const rawValue = normalizedFeatureVectors?.[key];
                      return {
                        key,
                        display: typeof rawValue === "number" ? rawValue.toFixed(2) : rawValue ?? "—",
                      };
                    });
                    const aggregatorEntries = aggregatorSection ? Object.entries(aggregatorSection) : [];
                    const confidenceEntries = confidenceWeightsSection ? Object.entries(confidenceWeightsSection) : [];
                    const newsItemCount = typeof newsSection?.item_count === "number" ? newsSection.item_count : null;
                    const newsPointCount = typeof newsSection?.point_count === "number" ? newsSection.point_count : null;
                    const newsSourceCount = typeof newsSection?.source_count === "number" ? newsSection.source_count : null;
                    const rawNewsItems = Array.isArray(newsSection?.items) ? (newsSection.items as unknown[]) : [];
                    const newsItemsList = rawNewsItems.filter(isRecord);
                    const newsStats = [
                      newsItemCount !== null ? { label: "news items", value: newsItemCount } : null,
                      newsPointCount !== null ? { label: "news points", value: newsPointCount } : null,
                      newsSourceCount !== null ? { label: "news sources", value: newsSourceCount } : null,
                    ].filter(Boolean) as { label: string; value: number }[];
                    const newsFeedErrors = Array.isArray(newsSection?.feed_errors)
                      ? (newsSection.feed_errors as unknown[]).filter((value): value is string => typeof value === "string")
                      : [];
                    const sentimentKeywordHits =
                      typeof sentimentSection?.keyword_hits === "number" ? sentimentSection.keyword_hits : null;
                    const coverageInsights = Array.isArray(sentimentSection?.coverage_insights)
                      ? (sentimentSection.coverage_insights as unknown[]).filter(
                          (entry): entry is string => typeof entry === "string"
                        )
                      : [];
                    return (
                      <article key={item.id ?? `${item.ticker}-${item.created_at}`} className="recommendation-card">
                        <div className="card-headline">
                          <div>
                            <div className="cluster">
                              <Link to={`/tickers/${item.ticker}`} className="badge badge-info badge-link">{item.ticker}</Link>
                              <Badge tone={directionTone(item.direction)}>{item.direction}</Badge>
                              <Badge tone={recommendationStateTone(item.state)}>{item.state}</Badge>
                            </div>
                            <h3 className="subsection-title">{item.confidence}% confidence</h3>
                          </div>
                          <Badge tone={messages.length > 0 ? "warning" : "ok"}>
                            {messages.length > 0 ? `${messages.length} warning(s)` : "No warnings"}
                          </Badge>
                        </div>
                        <section className="recommendation-section">
                          <div className="section-heading">
                            <strong>Trading parameters</strong>
                            <InfoBadge {...INFO_DESCRIPTIONS.trading} />
                          </div>
                          <div className="summary-grid">
                            <div className="summary-item">
                              <span className="summary-label summary-label-with-info">
                                Entry
                                <InfoBadge {...INFO_DESCRIPTIONS.fieldEntry} />
                              </span>
                              <span className="summary-value">{item.entry_price}</span>
                            </div>
                            <div className="summary-item">
                              <span className="summary-label summary-label-with-info">
                                Stop loss
                                <InfoBadge {...INFO_DESCRIPTIONS.fieldStop} />
                              </span>
                              <span className="summary-value">{item.stop_loss}</span>
                            </div>
                            <div className="summary-item">
                              <span className="summary-label summary-label-with-info">
                                Take profit
                                <InfoBadge {...INFO_DESCRIPTIONS.fieldTake} />
                              </span>
                              <span className="summary-value">{item.take_profit}</span>
                            </div>
                          </div>
                          <div className="helper-text">{item.indicator_summary || "No indicator summary stored for this recommendation."}</div>
                        </section>
                        {summaryText || newsDigest ? (
                          <section className="recommendation-section">
                            <div className="section-heading">
                              <strong>Summary & sentiment</strong>
                              <InfoBadge {...INFO_DESCRIPTIONS.summary} />
                            </div>
                            <div className="stack-page top-gap-small">
                              <div className="summary-grid">
                                <div className="summary-item summary-method-block">
                                  <span className="summary-label summary-label-with-info">
                                    Summary method
                                    <InfoBadge {...INFO_DESCRIPTIONS.summaryMethod} />
                                  </span>
                                  <span className="summary-method-value">{summaryMethodLabel} ({summaryBackendLabel})</span>
                                </div>
                              </div>
                              {summaryText ? (
                                <div className="summary-text-block">
                                  <p>{summaryText}</p>
                                </div>
                              ) : null}
                              {newsDigest && newsDigest !== summaryText ? (
                                <div className="helper-text">Headline digest: {newsDigest}</div>
                              ) : null}
                              {enhancedSentimentScore !== null ? (
                                <div className="enhanced-sentiment-card">
                                  <div className="summary-grid enhanced-sentiment-grid">
                                    <div className="summary-item">
                                      <span className="summary-label summary-label-with-info">
                                        Enhanced sentiment
                                        <InfoBadge {...INFO_DESCRIPTIONS.summary} />
                                      </span>
                                      <span className="summary-value">{enhancedSentimentScore.toFixed(2)}</span>
                                    </div>
                                    {enhancedSentimentLabel ? (
                                      <div className="summary-item">
                                        <span className="summary-label summary-label-with-info">
                                          Label
                                          <InfoBadge {...INFO_DESCRIPTIONS.summary} />
                                        </span>
                                        <span className="summary-value">{enhancedSentimentLabel}</span>
                                      </div>
                                    ) : null}
                                  </div>
                                  {enhancedComponents ? (
                                    <div className="summary-item">
                                      <span className="summary-label">Components</span>
                                      <pre>{JSON.stringify(enhancedComponents, null, 2)}</pre>
                                    </div>
                                  ) : null}
                                </div>
                              ) : null}
                            </div>
                          </section>
                        ) : null}
                        {analysis ? (
                          <section className="recommendation-section">
                            <div className="section-heading">
                              <strong>Structured diagnostics</strong>
                              <InfoBadge {...INFO_DESCRIPTIONS.diagnostics} />
                            </div>
                            <details className="top-gap-small structured-diagnostics">
                              <summary>Expand diagnostics</summary>
                              <div className="stack-page top-gap-small">
                                <section className="diagnostic-subsection">
                                  <div className="section-heading">
                                    <strong>Context flags</strong>
                                    <InfoBadge {...INFO_DESCRIPTIONS.contextFlags} />
                                  </div>
                                  {contextFlagEntries.length > 0 ? (
                                    <div className="summary-grid">
                                      {contextFlagEntries.map(([flag, value]) => (
                                        <div key={flag} className="summary-item">
                                          <span className="summary-label">{flag.replace(/_/g, " ")}</span>
                                          <span className="summary-value">
                                            {typeof value === "number" ? value.toFixed(2) : value ?? "—"}
                                          </span>
                                        </div>
                                      ))}
                                    </div>
                                  ) : (
                                    <div className="helper-text">No active context flags.</div>
                                  )}
                                </section>
                                <section className="diagnostic-subsection">
                                  <div className="section-heading">
                                    <strong>Normalized highlights</strong>
                                    <InfoBadge {...INFO_DESCRIPTIONS.highlights} />
                                  </div>
                                  <div className="summary-grid">
                                    {normalizedHighlights.map((entry) => (
                                      <div key={entry.key} className="summary-item">
                                        <span className="summary-label">{entry.key.replace(/_/g, " ")}</span>
                                        <span className="summary-value">{String(entry.display)}</span>
                                      </div>
                                    ))}
                                  </div>
                                </section>
                                <section className="diagnostic-subsection">
                                  <div className="section-heading">
                                    <strong>Aggregations</strong>
                                    <InfoBadge {...INFO_DESCRIPTIONS.aggregations} />
                                  </div>
                                  {aggregatorEntries.length > 0 ? (
                                    <div className="summary-grid">
                                      {aggregatorEntries.slice(0, 6).map(([key, value]) => (
                                        <div key={key} className="summary-item">
                                          <span className="summary-label">{key.replace(/_/g, " ")}</span>
                                          <span className="summary-value">
                                            {typeof value === "number" ? value.toFixed(2) : String(value ?? "—")}
                                          </span>
                                        </div>
                                      ))}
                                      {aggregatorEntries.length > 6 && (
                                        <div className="summary-item">
                                          <span className="summary-label">+ more aggregators</span>
                                          <span className="summary-value">+{aggregatorEntries.length - 6} more</span>
                                        </div>
                                      )}
                                    </div>
                                  ) : (
                                    <div className="helper-text">Aggregator totals not available.</div>
                                  )}
                                </section>
                                <section className="diagnostic-subsection">
                                  <div className="section-heading">
                                    <strong>Confidence weights</strong>
                                    <InfoBadge {...INFO_DESCRIPTIONS.weights} />
                                  </div>
                                  {confidenceEntries.length > 0 ? (
                                    <div className="summary-grid">
                                      {confidenceEntries.slice(0, 6).map(([key, value]) => (
                                        <div key={key} className="summary-item">
                                          <span className="summary-label">{key.replace(/_/g, " ")}</span>
                                          <span className="summary-value">
                                            {typeof value === "number" ? value.toFixed(2) : String(value ?? "—")}
                                          </span>
                                        </div>
                                      ))}
                                      {confidenceEntries.length > 6 && (
                                        <div className="summary-item">
                                          <span className="summary-label">+ more weights</span>
                                          <span className="summary-value">+{confidenceEntries.length - 6} more</span>
                                        </div>
                                      )}
                                    </div>
                                  ) : (
                                    <div className="helper-text">Confidence weights are not stored.</div>
                                  )}
                                </section>
                                <section className="diagnostic-subsection">
                                  <div className="section-heading">
                                    <strong>News coverage</strong>
                                    <InfoBadge {...INFO_DESCRIPTIONS.news} />
                                  </div>
                                  {newsStats.length > 0 ? (
                                    <div className="summary-grid">
                                      {newsStats.map((stat) => (
                                        <div key={stat.label} className="summary-item">
                                          <span className="summary-label">{stat.label}</span>
                                          <span className="summary-value">{stat.value}</span>
                                        </div>
                                      ))}
                                    </div>
                                  ) : (
                                    <div className="helper-text">No aggregated news totals.</div>
                                  )}
                                  {newsItemsList.length > 0 ? (
                                    <div className="stack-page top-gap-small">
                                      {newsItemsList.slice(0, 3).map((newsItem, index) => {
                                        const title = typeof newsItem.title === "string" ? newsItem.title : "Untitled article";
                                        const summaryBody = typeof newsItem.summary === "string" ? newsItem.summary : "";
                                        const compound = typeof newsItem.compound === "number" ? newsItem.compound.toFixed(2) : "—";
                                        const publisher = typeof newsItem.publisher === "string" ? newsItem.publisher : "Unknown source";
                                        const publishedAt = typeof newsItem.published_at === "string" ? formatDate(newsItem.published_at) : "—";
                                        return (
                                          <div key={`${title}-${index}`} className="structured-news-item">
                                            <div className="summary-grid">
                                              <div className="summary-item">
                                                <span className="summary-label">Title</span>
                                                <span className="summary-value">{title}</span>
                                              </div>
                                              <div className="summary-item">
                                                <span className="summary-label">Compound</span>
                                                <span className="summary-value">{compound}</span>
                                              </div>
                                            </div>
                                            <div className="helper-text">{summaryBody || "No summary available."}</div>
                                            <div className="helper-text">
                                              {publisher} · {publishedAt}
                                            </div>
                                          </div>
                                        );
                                      })}
                                      {newsItemsList.length > 3 ? (
                                        <div className="helper-text top-gap-small">+{newsItemsList.length - 3} more articles truncated.</div>
                                      ) : null}
                                    </div>
                                  ) : (
                                    <div className="helper-text">No news items stored for this proposal.</div>
                                  )}
                                  {newsFeedErrors.length > 0 ? (
                                    <ul className="warning-text">
                                      {newsFeedErrors.map((error, index) => (
                                        <li key={`${error}-${index}`}>{error}</li>
                                      ))}
                                    </ul>
                                  ) : null}
                                </section>
                                <section className="diagnostic-subsection">
                                  <div className="section-heading">
                                    <strong>Sentiment coverage</strong>
                                    <InfoBadge {...INFO_DESCRIPTIONS.coverage} />
                                  </div>
                                  {sentimentKeywordHits !== null ? (
                                    <div className="summary-grid">
                                      <div className="summary-item">
                                        <span className="summary-label">Keyword hits</span>
                                        <span className="summary-value">{sentimentKeywordHits}</span>
                                      </div>
                                    </div>
                                  ) : null}
                                  {coverageInsights.length > 0 ? (
                                    <>
                                      <div className="helper-text">Each insight describes why the sentiment signal stayed neutral (no articles, no keyword hits, provider failures, etc.).</div>
                                      <ul className="coverage-insights-list">
                                        {coverageInsights.map((insight, index) => (
                                          <li key={`${insight}-${index}`}>{insight}</li>
                                        ))}
                                      </ul>
                                    </>
                                  ) : (
                                    <div className="helper-text">Coverage insights report no detected issues.</div>
                                  )}
                                </section>
                              </div>
                            </details>
                          </section>
                        ) : null}
                        <section className="recommendation-section">
                          <div className="section-heading">
                            <strong>Diagnostic messages</strong>
                            <InfoBadge {...INFO_DESCRIPTIONS.messages} />
                          </div>
                          {messages.length > 0 ? (
                            <ul className="warning-text">
                              {messages.map((message) => (
                                <li key={message}>{message}</li>
                              ))}
                            </ul>
                          ) : (
                            <div className="helper-text">No warnings or errors.</div>
                          )}
                        </section>
                        {output.diagnostics.raw_output ? (
                          <section className="recommendation-section">
                            <div className="section-heading">
                              <strong>Raw details</strong>
                              <InfoBadge {...INFO_DESCRIPTIONS.raw} />
                            </div>
                            <details>
                              <summary>View raw output</summary>
                              <pre>{output.diagnostics.raw_output}</pre>
                            </details>
                          </section>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              </>
            ) : (
              <WorkflowRunResults
                jobType={detail.run.job_type}
                summaryJson={detail.run.summary_json}
                artifactJson={detail.run.artifact_json}
              />
            )}
          </Card>
        </div>
      ) : null}
    </>
  );
}
