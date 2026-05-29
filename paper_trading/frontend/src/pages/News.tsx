import React, { useEffect, useState } from "react";
import { api } from "../api";
import type { NewsItem, NewsData } from "../api";

const SOURCE_COLORS: Record<string, string> = {
  "CoinDesk":        "#ff6600",
  "Cointelegraph":   "#3399ff",
  "The Block":       "#00cc44",
  "Decrypt":         "#ffcc00",
  "Bitcoin Magazine": "#ff3333",
};

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function NewsCard({ item }: { item: NewsItem }) {
  const color = SOURCE_COLORS[item.source] ?? "#666";
  return (
    <div className="card" style={{ marginBottom: 8, borderLeft: `3px solid ${color}` }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
        <span style={{
          fontSize: 9, fontWeight: 700, color, fontFamily: "Arial",
          textTransform: "uppercase", letterSpacing: 0.5,
        }}>
          {item.source}
        </span>
        <span style={{ fontSize: 9, color: "#444", fontFamily: "Courier New", whiteSpace: "nowrap", marginLeft: 8 }}>
          {timeAgo(item.published_at)}
        </span>
      </div>

      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          color: "#e0e0e0", textDecoration: "none", fontSize: 13, fontWeight: 700,
          lineHeight: 1.4, display: "block", marginBottom: 4,
        }}
      >
        {item.title}
      </a>

      {item.summary && (
        <div style={{ fontSize: 11, color: "#555", lineHeight: 1.5, fontFamily: "Courier New" }}>
          {item.summary}
        </div>
      )}

      {item.published_at && (
        <div style={{ marginTop: 4, fontSize: 9, color: "#333", fontFamily: "Courier New" }}>
          {new Date(item.published_at).toLocaleString()}
        </div>
      )}
    </div>
  );
}

export default function News() {
  const [data, setData] = useState<NewsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);

  const sources = Object.keys(SOURCE_COLORS);

  const load = (source?: string) => {
    setLoading(true);
    setError(null);
    api.news(60, source)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const items = data?.items ?? [];
  const filtered = sourceFilter
    ? items.filter(i => i.source === sourceFilter)
    : items;

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-title">News</div>
          <div className="page-subtitle">
            {data
              ? `${data.total} articles · ${data.sources_ok.join(", ")} · ${new Date(data.fetched_at).toLocaleString()}`
              : "Crypto news aggregator · RSS feeds"}
          </div>
        </div>
        <button className="btn btn-ghost" onClick={() => load(sourceFilter ?? undefined)}>↻ Refresh</button>
      </div>

      {error && <div className="error-msg" style={{ marginBottom: 12 }}>{error}</div>}

      {/* Source filter */}
      <div className="btn-row" style={{ marginBottom: 16 }}>
        <button
          className={`btn ${sourceFilter === null ? "btn-primary" : "btn-ghost"}`}
          onClick={() => { setSourceFilter(null); load(); }}
        >
          All Sources
        </button>
        {sources.map(s => (
          <button
            key={s}
            className={`btn ${sourceFilter === s ? "btn-secondary" : "btn-ghost"}`}
            style={{ borderLeft: `2px solid ${SOURCE_COLORS[s]}` }}
            onClick={() => { setSourceFilter(s); }}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Failed sources warning */}
      {data && data.sources_err.length > 0 && (
        <div style={{
          background: "#1a1400", border: "1px solid #443300", color: "#ffcc00",
          fontSize: 10, fontFamily: "Courier New", padding: "6px 10px", marginBottom: 12,
        }}>
          Feed unavailable: {data.sources_err.join(", ")} (RSS may be blocked or rate-limited)
        </div>
      )}

      {loading && <div className="loading">Loading news feeds…</div>}

      {!loading && filtered.length === 0 && !error && (
        <div className="card" style={{ color: "#555" }}>
          No news available. RSS feeds may be blocked in this environment.
        </div>
      )}

      {/* Two-column layout for wider screens */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(500px, 1fr))",
        gap: 0,
        alignItems: "start",
      }}>
        <div>
          {filtered.filter((_, i) => i % 2 === 0).map((item) => (
            <NewsCard key={`${item.url}|${item.published_at}`} item={item} />
          ))}
        </div>
        <div>
          {filtered.filter((_, i) => i % 2 === 1).map((item) => (
            <NewsCard key={`${item.url}|${item.published_at}`} item={item} />
          ))}
        </div>
      </div>
    </div>
  );
}
