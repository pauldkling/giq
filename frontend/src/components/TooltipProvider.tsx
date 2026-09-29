// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import "./Tooltip.css";

/* One tooltip for the whole app, positioned at the pointer and clamped to
   the viewport. Charts call show() on pointer move over a mark and hide() on
   leave; the content is React nodes, so server text in it is escaped like
   anywhere else. */

export interface PointerLike {
  clientX: number;
  clientY: number;
}

interface TooltipApi {
  show: (at: PointerLike, content: ReactNode) => void;
  hide: () => void;
}

const Ctx = createContext<TooltipApi | null>(null);

const OFFSET = 14;
const MARGIN = 8;

export function TooltipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<{ x: number; y: number; content: ReactNode } | null>(null);
  const el = useRef<HTMLDivElement>(null);

  const show = useCallback((at: PointerLike, content: ReactNode) => {
    setTip({ x: at.clientX, y: at.clientY, content });
  }, []);
  const hide = useCallback(() => setTip(null), []);
  const api = useMemo(() => ({ show, hide }), [show, hide]);

  // Clamp after layout, when the tooltip's own size is known.
  useLayoutEffect(() => {
    const node = el.current;
    if (!node || !tip) return;
    const w = node.offsetWidth;
    const h = node.offsetHeight;
    let left = tip.x + OFFSET;
    let top = tip.y + OFFSET;
    if (left + w > window.innerWidth - MARGIN) left = Math.max(MARGIN, tip.x - OFFSET - w);
    if (top + h > window.innerHeight - MARGIN) top = Math.max(MARGIN, tip.y - OFFSET - h);
    node.style.left = `${left}px`;
    node.style.top = `${top}px`;
  }, [tip]);

  return (
    <Ctx.Provider value={api}>
      {children}
      {tip && (
        <div ref={el} className="giq-tooltip" role="tooltip">
          {tip.content}
        </div>
      )}
    </Ctx.Provider>
  );
}

/** show(event, content) / hide() on the app's single tooltip. */
export function useTooltip(): TooltipApi {
  const api = useContext(Ctx);
  if (!api) throw new Error("useTooltip outside TooltipProvider");
  return api;
}
