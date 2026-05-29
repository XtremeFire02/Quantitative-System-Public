/**
 * Minimal toast system. Usage:
 *   import { toast } from "./Toast";
 *   toast.success("Bot added");
 *   toast.error("Failed to remove");
 *   toast.info("Job triggered");
 *
 * Mount <ToastContainer /> once at the app root.
 */

import React, { useEffect, useState, useCallback } from "react";

type ToastKind = "success" | "error" | "info" | "warn";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

type Listener = (items: ToastItem[]) => void;

let _next = 1;
let _items: ToastItem[] = [];
const _listeners = new Set<Listener>();

function notify() {
  const snapshot = [..._items];
  _listeners.forEach(fn => fn(snapshot));
}

function push(kind: ToastKind, message: string) {
  const id = _next++;
  _items = [..._items, { id, kind, message }];
  notify();
  setTimeout(() => {
    _items = _items.filter(t => t.id !== id);
    notify();
  }, kind === "error" ? 6000 : 3500);
}

export const toast = {
  success: (msg: string) => push("success", msg),
  error:   (msg: string) => push("error",   msg),
  info:    (msg: string) => push("info",     msg),
  warn:    (msg: string) => push("warn",     msg),
};

const KIND_STYLE: Record<ToastKind, { border: string; color: string; icon: string }> = {
  success: { border: "#00cc44", color: "#00cc44", icon: "✓" },
  error:   { border: "#ff3333", color: "#ff3333", icon: "✗" },
  info:    { border: "#3399ff", color: "#3399ff", icon: "ℹ" },
  warn:    { border: "#ffcc00", color: "#ffcc00", icon: "⚠" },
};

function ToastCard({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  const s = KIND_STYLE[item.kind];
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 10,
      background: "#0a0a0a", border: `1px solid ${s.border}33`,
      borderLeft: `3px solid ${s.border}`,
      padding: "9px 12px", minWidth: 240, maxWidth: 380,
      boxShadow: `0 2px 12px rgba(0,0,0,0.6)`,
      animation: "toast-in 0.15s ease",
      fontFamily: "Courier New",
    }}>
      <span style={{ color: s.color, fontWeight: 700, fontSize: 13, flexShrink: 0 }}>
        {s.icon}
      </span>
      <span style={{ color: "#cccccc", fontSize: 11, lineHeight: 1.5, flex: 1 }}>
        {item.message}
      </span>
      <button
        onClick={onDismiss}
        style={{
          background: "none", border: "none", color: "#444444",
          cursor: "pointer", fontSize: 14, lineHeight: 1, padding: 0, flexShrink: 0,
        }}
      >×</button>
    </div>
  );
}

export function ToastContainer() {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    _items = _items.filter(t => t.id !== id);
    notify();
  }, []);

  useEffect(() => {
    _listeners.add(setItems);
    return () => { _listeners.delete(setItems); };
  }, []);

  if (items.length === 0) return null;

  return (
    <>
      <style>{`
        @keyframes toast-in {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0);   }
        }
      `}</style>
      <div style={{
        position: "fixed", bottom: 20, right: 20, zIndex: 9999,
        display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end",
      }}>
        {items.map(item => (
          <ToastCard key={item.id} item={item} onDismiss={() => dismiss(item.id)} />
        ))}
      </div>
    </>
  );
}
