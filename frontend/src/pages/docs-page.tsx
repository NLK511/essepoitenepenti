import mermaid from "mermaid";
import { ChangeEvent, ReactNode, createElement, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson } from "../api";
import { Card, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import type { DocDocument, DocsResponse } from "../types";

interface DocGroupDefinition {
  id: string;
  title: string;
  description: string;
  slugs: string[];
}

interface DocGroup {
  id: string;
  title: string;
  description: string;
  documents: DocDocument[];
}

interface GlossaryEntry {
  term: string;
  definition: string;
}

const DOC_GROUPS: DocGroupDefinition[] = [
  {
    id: "start",
    title: "Start here",
    description: "Setup, orientation, and the shortest path to a working local app.",
    slugs: ["readme", "getting-started", "status"],
  },
  {
    id: "operate",
    title: "Using the app",
    description: "What the product does today and how an operator typically moves through it.",
    slugs: ["features-and-capabilities", "user-journeys"],
  },
  {
    id: "understand",
    title: "Understanding recommendations",
    description: "How recommendation outputs are formed and how to read stored diagnostics.",
    slugs: ["recommendation-methodology", "raw-details-reference"],
  },
  {
    id: "product",
    title: "Product and planning",
    description: "Product intent, roadmap, and critical review of the current direction.",
    slugs: ["product-plan", "roadmap", "critical-review", "review-summary", "review-email-draft"],
  },
  {
    id: "technical",
    title: "Architecture and engineering",
    description: "Runtime structure, module boundaries, and implementation constraints.",
    slugs: ["architecture"],
  },
];

const DOC_GROUP_LOOKUP = new Map(
  DOC_GROUPS.flatMap((group, groupIndex) =>
    group.slugs.map((slug, docIndex) => [slug, { groupId: group.id, groupIndex, docIndex }] as const),
  ),
);

let mermaidDiagramCounter = 0;

function normalizeDocPath(path: string): string {
  const segments: string[] = [];
  for (const part of path.split("/")) {
    if (!part || part === ".") {
      continue;
    }
    if (part === "..") {
      segments.pop();
      continue;
    }
    segments.push(part);
  }
  return segments.join("/");
}

function resolveInternalDocTarget(
  href: string,
  currentDocument: DocDocument,
  documents: DocDocument[],
): { slug: string; sectionId?: string } | null {
  if (!href || href.startsWith("#") || /^[a-z]+:/i.test(href)) {
    return null;
  }

  const [rawPath, rawHash] = href.split("#", 2);
  if (!rawPath.endsWith(".md")) {
    return null;
  }

  const currentDir = currentDocument.path.includes("/")
    ? currentDocument.path.slice(0, currentDocument.path.lastIndexOf("/") + 1)
    : "";
  const resolvedPath = normalizeDocPath(rawPath.startsWith("/") ? rawPath.slice(1) : `${currentDir}${rawPath}`);
  const match = documents.find((document) => document.path === resolvedPath);
  if (!match) {
    return null;
  }

  const sectionId = rawHash ? rawHash.trim() : undefined;
  return { slug: match.slug, sectionId };
}

function stripMarkdownFormatting(text: string): string {
  return text
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/^[-*]\s+/, "")
    .trim();
}

function extractGlossaryEntries(documents: DocDocument[]): GlossaryEntry[] {
  const glossaryDocument = documents.find((document) => document.slug === "glossary");
  if (!glossaryDocument) {
    return [];
  }

  const entries: GlossaryEntry[] = [];
  const lines = glossaryDocument.content.split(/\r?\n/);
  let currentTerm = "";
  let currentDefinitionLines: string[] = [];

  const flush = () => {
    const definition = currentDefinitionLines
      .map((line) => stripMarkdownFormatting(line))
      .filter(Boolean)
      .join(" ")
      .trim();
    if (currentTerm && definition) {
      entries.push({ term: currentTerm, definition });
    }
    currentTerm = "";
    currentDefinitionLines = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith("### ")) {
      flush();
      currentTerm = stripMarkdownFormatting(trimmed.slice(4));
      continue;
    }
    if (trimmed.startsWith("## ")) {
      flush();
      continue;
    }
    if (!currentTerm || trimmed === "---") {
      continue;
    }
    currentDefinitionLines.push(trimmed);
  }
  flush();

  return entries.sort((left, right) => right.term.length - left.term.length);
}

function isGlossaryBoundary(character: string | undefined): boolean {
  return !character || !/[a-z0-9]/i.test(character);
}

function applyGlossaryTooltips(text: string, keyPrefix: string, glossaryEntries: GlossaryEntry[]): ReactNode[] {
  if (!text || glossaryEntries.length === 0) {
    return [text];
  }

  const pattern = new RegExp(glossaryEntries.map((entry) => entry.term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "gi");
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null = pattern.exec(text);

  while (match) {
    const matchedText = match[0];
    const start = match.index;
    const end = start + matchedText.length;
    const before = text[start - 1];
    const after = text[end];

    if (!isGlossaryBoundary(before) || !isGlossaryBoundary(after)) {
      match = pattern.exec(text);
      continue;
    }

    if (start > cursor) {
      nodes.push(text.slice(cursor, start));
    }

    const glossaryEntry = glossaryEntries.find((entry) => entry.term.toLowerCase() === matchedText.toLowerCase());
    if (glossaryEntry) {
      nodes.push(
        <span
          key={`${keyPrefix}-glossary-${nodes.length}`}
          className="glossary-term"
          tabIndex={0}
          data-definition={glossaryEntry.definition}
          aria-label={`${matchedText}: ${glossaryEntry.definition}`}
        >
          {matchedText}
        </span>,
      );
    } else {
      nodes.push(matchedText);
    }
    cursor = end;
    match = pattern.exec(text);
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }

  return nodes.length > 0 ? nodes : [text];
}

function inlineNodes(
  text: string,
  keyPrefix: string,
  currentDocument: DocDocument,
  documents: DocDocument[],
  glossaryEntries: GlossaryEntry[],
): ReactNode[] {
  const tokenPattern = /(`[^`]+`|\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  const matches = Array.from(text.matchAll(tokenPattern));
  if (matches.length === 0) {
    return applyGlossaryTooltips(text, keyPrefix, glossaryEntries);
  }

  const nodes: ReactNode[] = [];
  let cursor = 0;
  matches.forEach((match, index) => {
    const token = match[0];
    const start = match.index ?? 0;
    if (start > cursor) {
      nodes.push(...applyGlossaryTooltips(text.slice(cursor, start), `${keyPrefix}-text-${index}`, glossaryEntries));
    }

    if (token.startsWith("`") && token.endsWith("`")) {
      const codeText = token.slice(1, -1);
      const internalTarget = resolveInternalDocTarget(codeText, currentDocument, documents);
      if (internalTarget) {
        const params = new URLSearchParams({ doc: internalTarget.slug });
        if (internalTarget.sectionId) {
          params.set("section", internalTarget.sectionId);
        }
        nodes.push(
          <Link key={`${keyPrefix}-code-link-${index}`} to={`/docs?${params.toString()}`}>
            <code>{codeText}</code>
          </Link>,
        );
      } else {
        nodes.push(<code key={`${keyPrefix}-code-${index}`}>{codeText}</code>);
      }
    } else if (token.startsWith("[")) {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        const label = linkMatch[1];
        const href = linkMatch[2];
        const internalTarget = resolveInternalDocTarget(href, currentDocument, documents);
        if (internalTarget) {
          const params = new URLSearchParams({ doc: internalTarget.slug });
          if (internalTarget.sectionId) {
            params.set("section", internalTarget.sectionId);
          }
          nodes.push(
            <Link key={`${keyPrefix}-link-${index}`} to={`/docs?${params.toString()}`}>
              {label}
            </Link>,
          );
        } else {
          nodes.push(
            <a key={`${keyPrefix}-link-${index}`} href={href} target="_blank" rel="noreferrer">
              {label}
            </a>,
          );
        }
      } else {
        nodes.push(token);
      }
    } else if (token.startsWith("**") && token.endsWith("**")) {
      nodes.push(
        <strong key={`${keyPrefix}-strong-${index}`}>
          {applyGlossaryTooltips(token.slice(2, -2), `${keyPrefix}-strong-${index}`, glossaryEntries)}
        </strong>,
      );
    } else if (token.startsWith("*") && token.endsWith("*")) {
      nodes.push(
        <em key={`${keyPrefix}-em-${index}`}>
          {applyGlossaryTooltips(token.slice(1, -1), `${keyPrefix}-em-${index}`, glossaryEntries)}
        </em>,
      );
    } else {
      nodes.push(token);
    }
    cursor = start + token.length;
  });

  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }

  return nodes;
}

function isSpecialLine(line: string): boolean {
  const trimmed = line.trim();
  return (
    trimmed === "" ||
    trimmed.startsWith("```") ||
    /^#{1,6}\s+/.test(trimmed) ||
    /^[-*]\s+/.test(trimmed) ||
    /^\d+\.\s+/.test(trimmed)
  );
}

function normalizeMermaidChart(chart: string): string {
  const lines = chart.replace(/\r\n/g, "\n").split("\n");
  while (lines.length > 0 && lines[0].trim() === "") {
    lines.shift();
  }
  while (lines.length > 0 && lines[lines.length - 1].trim() === "") {
    lines.pop();
  }
  const indents = lines
    .filter((line) => line.trim().length > 0)
    .map((line) => line.match(/^\s*/)?.[0].length ?? 0);
  const commonIndent = indents.length > 0 ? Math.min(...indents) : 0;
  return lines.map((line) => line.slice(commonIndent)).join("\n");
}

function MermaidDiagram(props: { chart: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const normalizedChart = useMemo(() => normalizeMermaidChart(props.chart), [props.chart]);
  const diagramId = useMemo(() => {
    mermaidDiagramCounter += 1;
    return `mermaid-diagram-${mermaidDiagramCounter}`;
  }, []);

  useEffect(() => {
    let cancelled = false;
    const mermaidModule = mermaid as typeof mermaid & { parseError?: ((error: unknown) => void) | undefined };
    const previousParseError = mermaidModule.parseError;

    async function renderDiagram() {
      try {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "default",
          flowchart: { htmlLabels: false },
          suppressErrors: true,
        });
        mermaidModule.parseError = () => undefined;

        const parsed = await mermaid.parse(normalizedChart, { suppressErrors: true });
        if (!parsed) {
          throw new Error("Mermaid diagram syntax could not be parsed");
        }

        const rendered = await mermaid.render(diagramId, normalizedChart);
        if (cancelled) {
          return;
        }

        if (rendered.svg.includes("Syntax error in text")) {
          throw new Error("Mermaid diagram syntax error");
        }

        setSvg(rendered.svg);
        setError(null);
      } catch (renderError) {
        if (!cancelled) {
          setSvg(null);
          setError(renderError instanceof Error ? renderError.message : "Failed to render Mermaid diagram");
        }
      } finally {
        mermaidModule.parseError = previousParseError;
      }
    }

    void renderDiagram();
    return () => {
      cancelled = true;
      mermaidModule.parseError = previousParseError;
    };
  }, [diagramId, normalizedChart]);

  if (error) {
    return (
      <div className="mermaid-error-block">
        <div className="helper-text">Mermaid diagram could not be rendered.</div>
        <pre>{normalizedChart}</pre>
        <div className="warning-text top-gap-small">{error}</div>
      </div>
    );
  }

  if (!svg) {
    return <div className="empty-state">Rendering diagram…</div>;
  }

  return <div className="mermaid-diagram" dangerouslySetInnerHTML={{ __html: svg }} />;
}

function renderMarkdown(
  document: DocDocument,
  activeSectionId: string,
  documents: DocDocument[],
  glossaryEntries: GlossaryEntry[],
): ReactNode[] {
  const lines = document.content.split(/\r?\n/);
  const nodes: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const language = trimmed.slice(3).trim().toLowerCase();
      const block: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        block.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      const code = block.join("\n");
      if (language === "mermaid") {
        nodes.push(<MermaidDiagram key={`mermaid-${nodes.length}`} chart={code} />);
      } else {
        nodes.push(
          <pre key={`code-${nodes.length}`} className="markdown-code-block">
            <code data-language={language || undefined}>{code}</code>
          </pre>,
        );
      }
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      const level = Math.min(headingMatch[1].length, 6);
      const text = headingMatch[2].trim();
      const section = document.sections.find((item) => item.title === text && item.level === level);
      const headingId = level === 1 ? document.slug : section?.id ?? `${document.slug}-${nodes.length}`;
      const tagName = `h${level}`;
      nodes.push(
        createElement(
          tagName,
          {
            key: `heading-${nodes.length}`,
            id: headingId,
            className: `markdown-heading markdown-heading-${level}${activeSectionId === headingId ? " is-active-target" : ""}`,
          },
          inlineNodes(text, `heading-${nodes.length}`, document, documents, glossaryEntries),
        ),
      );
      index += 1;
      continue;
    }

    const isOrdered = /^\d+\.\s+/.test(trimmed);
    const isUnordered = /^[-*]\s+/.test(trimmed);
    if (isOrdered || isUnordered) {
      const items: string[] = [];
      const pattern = isOrdered ? /^\d+\.\s+/ : /^[-*]\s+/;
      while (index < lines.length && pattern.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(pattern, ""));
        index += 1;
      }
      const listTag = isOrdered ? "ol" : "ul";
      nodes.push(
        createElement(
          listTag,
          { key: `list-${nodes.length}`, className: "markdown-list" },
          items.map((item, itemIndex) => (
            <li key={`list-item-${nodes.length}-${itemIndex}`}>
              {inlineNodes(item, `list-${nodes.length}-${itemIndex}`, document, documents, glossaryEntries)}
            </li>
          )),
        ),
      );
      continue;
    }

    const paragraphLines = [trimmed];
    index += 1;
    while (index < lines.length && !isSpecialLine(lines[index])) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    nodes.push(
      <p key={`paragraph-${nodes.length}`} className="markdown-paragraph">
        {inlineNodes(paragraphLines.join(" "), `paragraph-${nodes.length}`, document, documents, glossaryEntries)}
      </p>,
    );
  }

  return nodes;
}

function getDocumentSortKey(document: DocDocument): { groupIndex: number; docIndex: number; title: string } {
  const entry = DOC_GROUP_LOOKUP.get(document.slug);
  if (!entry) {
    return { groupIndex: DOC_GROUPS.length, docIndex: Number.MAX_SAFE_INTEGER, title: document.title };
  }
  return { groupIndex: entry.groupIndex, docIndex: entry.docIndex, title: document.title };
}

function buildDocGroups(documents: DocDocument[]): DocGroup[] {
  const ordered = [...documents].sort((left, right) => {
    const leftKey = getDocumentSortKey(left);
    const rightKey = getDocumentSortKey(right);
    if (leftKey.groupIndex !== rightKey.groupIndex) {
      return leftKey.groupIndex - rightKey.groupIndex;
    }
    if (leftKey.docIndex !== rightKey.docIndex) {
      return leftKey.docIndex - rightKey.docIndex;
    }
    return leftKey.title.localeCompare(rightKey.title);
  });

  const groups = DOC_GROUPS.map<DocGroup>((group) => ({
    id: group.id,
    title: group.title,
    description: group.description,
    documents: ordered.filter((document) => DOC_GROUP_LOOKUP.get(document.slug)?.groupId === group.id),
  })).filter((group) => group.documents.length > 0);

  const uncategorizedDocuments = ordered.filter((document) => !DOC_GROUP_LOOKUP.has(document.slug));
  if (uncategorizedDocuments.length > 0) {
    groups.push({
      id: "other",
      title: "Other docs",
      description: "Additional reference material that does not yet have a dedicated section.",
      documents: uncategorizedDocuments,
    });
  }

  return groups;
}

export function DocsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [documents, setDocuments] = useState<DocDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [expandedDocuments, setExpandedDocuments] = useState<Record<string, boolean>>({});
  const articleRef = useRef<HTMLElement | null>(null);

  const query = searchParams.get("q") ?? "";
  const selectedSlug = searchParams.get("doc") ?? "";
  const selectedSectionId = searchParams.get("section") ?? "";

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        const response = await getJson<DocsResponse>("/api/docs");
        setDocuments(response.documents);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load docs");
      }
    }
    void load();
  }, []);

  const filteredDocuments = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!documents) {
      return [];
    }
    if (!normalizedQuery) {
      return documents;
    }
    return documents.filter((document) => {
      const sectionTitles = document.sections.map((section) => section.title).join("\n");
      const haystack = `${document.title}\n${document.path}\n${sectionTitles}\n${document.content}`.toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [documents, query]);

  const groupedDocuments = useMemo(() => buildDocGroups(filteredDocuments), [filteredDocuments]);
  const glossaryEntries = useMemo(() => (documents ? extractGlossaryEntries(documents) : []), [documents]);

  const selectedDocument = useMemo(() => {
    if (filteredDocuments.length === 0) {
      return null;
    }
    const explicit = filteredDocuments.find((document) => document.slug === selectedSlug);
    return explicit ?? filteredDocuments[0];
  }, [filteredDocuments, selectedSlug]);

  useEffect(() => {
    if (!selectedDocument) {
      return;
    }

    const scrollTarget = () => {
      if (selectedSectionId) {
        const element = window.document.getElementById(selectedSectionId);
        if (element) {
          element.scrollIntoView({ block: "start", behavior: "smooth" });
          return;
        }
      }

      articleRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    };

    const frame = window.requestAnimationFrame(scrollTarget);
    return () => window.cancelAnimationFrame(frame);
  }, [selectedDocument, selectedSectionId]);

  useEffect(() => {
    if (groupedDocuments.length === 0) {
      return;
    }
    setExpandedGroups((current) => {
      const next = { ...current };
      groupedDocuments.forEach((group, index) => {
        if (query.trim()) {
          next[group.id] = true;
          return;
        }
        if (next[group.id] !== undefined) {
          return;
        }
        next[group.id] = index === 0 || group.documents.some((document) => document.slug === selectedDocument?.slug);
      });
      if (selectedDocument) {
        const containingGroup = groupedDocuments.find((group) => group.documents.some((document) => document.slug === selectedDocument.slug));
        if (containingGroup) {
          next[containingGroup.id] = true;
        }
      }
      return next;
    });
    setExpandedDocuments((current) => {
      if (!selectedDocument) {
        return current;
      }
      return { ...current, [selectedDocument.slug]: true };
    });
  }, [groupedDocuments, query, selectedDocument]);

  function updateParams(nextQuery: string, nextSlug?: string, nextSectionId?: string | null) {
    const params = new URLSearchParams();
    if (nextQuery) {
      params.set("q", nextQuery);
    }
    const slug = nextSlug ?? selectedDocument?.slug ?? filteredDocuments[0]?.slug;
    if (slug) {
      params.set("doc", slug);
    }
    if (nextSectionId) {
      params.set("section", nextSectionId);
    }
    setSearchParams(params, { replace: true });
  }

  function handleSearchChange(event: ChangeEvent<HTMLInputElement>) {
    updateParams(event.target.value, filteredDocuments[0]?.slug, null);
  }

  function toggleGroup(groupId: string) {
    setExpandedGroups((current) => ({ ...current, [groupId]: !current[groupId] }));
  }

  function toggleDocument(slug: string) {
    setExpandedDocuments((current) => ({ ...current, [slug]: !current[slug] }));
  }

  return (
    <>
      <PageHeader
        kicker="Documentation"
        title="Read the app docs in a tighter, operator-first layout."
        subtitle="Start with setup and day-to-day usage at the top, then move into methodology, planning, and technical reference as needed."
      />
      {error ? <ErrorState message={error} /> : null}
      {!documents && !error ? <LoadingState message="Loading docs…" /> : null}
      {documents ? (
        <div className="docs-layout">
          <Card className="docs-sidebar-panel">
            <label className="form-field docs-search-field">
              <span>Full-text search</span>
              <input
                type="search"
                value={query}
                onChange={handleSearchChange}
                placeholder="Search all docs"
              />
            </label>
            <div className="helper-text">{filteredDocuments.length} document(s) matched</div>
            {filteredDocuments.length === 0 ? (
              <EmptyState message="No docs match the current search." />
            ) : (
              <div className="docs-tree">
                {groupedDocuments.map((group) => {
                  const isGroupExpanded = expandedGroups[group.id] ?? false;
                  return (
                    <section key={group.id} className="doc-group">
                      <button
                        type="button"
                        className={`doc-group-button${isGroupExpanded ? " is-expanded" : ""}`}
                        onClick={() => toggleGroup(group.id)}
                        aria-expanded={isGroupExpanded}
                      >
                        <span>
                          <span className="doc-group-title">{group.title}</span>
                          <span className="doc-group-description">{group.description}</span>
                        </span>
                        <span className="doc-group-chevron" aria-hidden="true">
                          {isGroupExpanded ? "−" : "+"}
                        </span>
                      </button>
                      {isGroupExpanded ? (
                        <div className="doc-group-body">
                          {group.documents.map((document) => {
                            const isSelected = selectedDocument?.slug === document.slug;
                            const isExpanded = expandedDocuments[document.slug] ?? isSelected;
                            return (
                              <div key={document.slug} className="doc-nav-group">
                                <div className="doc-nav-row">
                                  <button
                                    type="button"
                                    className={`doc-nav-button${isSelected && !selectedSectionId ? " is-active" : ""}`}
                                    onClick={() => updateParams(query, document.slug, null)}
                                  >
                                    <span className="doc-nav-title">{document.title}</span>
                                    <span className="doc-path">{document.path}</span>
                                  </button>
                                  {document.sections.length > 0 ? (
                                    <button
                                      type="button"
                                      className={`doc-nav-toggle${isExpanded ? " is-expanded" : ""}`}
                                      onClick={() => toggleDocument(document.slug)}
                                      aria-expanded={isExpanded}
                                      aria-label={`${isExpanded ? "Collapse" : "Expand"} sections for ${document.title}`}
                                    >
                                      {isExpanded ? "−" : "+"}
                                    </button>
                                  ) : null}
                                </div>
                                {document.sections.length > 0 && isExpanded ? (
                                  <div className="doc-section-list">
                                    {document.sections.map((section) => (
                                      <button
                                        key={`${document.slug}-${section.id}`}
                                        type="button"
                                        className={`doc-section-button${isSelected && selectedSectionId === section.id ? " is-active" : ""}`}
                                        data-level={section.level}
                                        onClick={() => updateParams(query, document.slug, section.id)}
                                      >
                                        {section.title}
                                      </button>
                                    ))}
                                  </div>
                                ) : null}
                              </div>
                            );
                          })}
                        </div>
                      ) : null}
                    </section>
                  );
                })}
              </div>
            )}
          </Card>
          <Card className="docs-content-panel">
            {selectedDocument ? (
              <article ref={articleRef} className="docs-article markdown-viewer">
                <div className="docs-article-header">
                  <div>
                    <div className="kicker">{selectedDocument.path}</div>
                    <h2 className="section-title">{selectedDocument.title}</h2>
                  </div>
                </div>
                <div className="markdown-content">{renderMarkdown(selectedDocument, selectedSectionId, documents, glossaryEntries)}</div>
              </article>
            ) : (
              <EmptyState message="Select a document to read." />
            )}
          </Card>
        </div>
      ) : null}
    </>
  );
}
