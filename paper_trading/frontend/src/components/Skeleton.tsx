/**
 * Lightweight skeleton placeholders for loading states.
 *
 * Usage:
 *   <SkeletonCard />                     — single stat card shimmer
 *   <SkeletonCards n={6} />              — grid of stat cards
 *   <SkeletonTable rows={5} cols={6} />  — table with shimmer rows
 *   <SkeletonText lines={3} />           — paragraph shimmer
 */

import React from "react";

const shimmer: React.CSSProperties = {
  background: "linear-gradient(90deg, #111 25%, #1a1a1a 50%, #111 75%)",
  backgroundSize: "200% 100%",
  animation: "skeleton-shimmer 1.4s ease infinite",
};

const style = `
  @keyframes skeleton-shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
`;

function Bar({ w = "100%", h = 12, mb = 0 }: { w?: string | number; h?: number; mb?: number }) {
  return (
    <div style={{
      ...shimmer,
      width: w, height: h, marginBottom: mb,
      borderRadius: 0,
    }} />
  );
}

export function SkeletonCard() {
  return (
    <div className="card">
      <Bar w="60%" h={8} mb={8} />
      <Bar w="80%" h={22} mb={6} />
      <Bar w="45%" h={8} />
    </div>
  );
}

export function SkeletonCards({ n = 4 }: { n?: number }) {
  return (
    <>
      <style>{style}</style>
      <div className="cards-grid">
        {Array.from({ length: n }).map((_, i) => <SkeletonCard key={i} />)}
      </div>
    </>
  );
}

export function SkeletonTable({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <>
      <style>{style}</style>
      <div className="table-wrapper">
        <table>
          <thead>
            <tr>
              {Array.from({ length: cols }).map((_, i) => (
                <th key={i}><Bar w="70%" h={8} /></th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: rows }).map((_, r) => (
              <tr key={r}>
                {Array.from({ length: cols }).map((_, c) => (
                  <td key={c}><Bar w={`${50 + Math.sin(r * 3 + c) * 30}%`} h={9} /></td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  const widths = ["100%", "88%", "72%", "94%", "60%"];
  return (
    <>
      <style>{style}</style>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {Array.from({ length: lines }).map((_, i) => (
          <Bar key={i} w={widths[i % widths.length]} h={10} />
        ))}
      </div>
    </>
  );
}
