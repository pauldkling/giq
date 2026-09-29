// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useRef, useState } from "react";

/* The width of an element, kept current by a ResizeObserver. Charts size
   themselves from this rather than from clientWidth at draw time, which is 0
   while a view is hidden and never updates when the sidebar collapses. */
export function useElementWidth<T extends Element = HTMLDivElement>(): [
  (el: T | null) => void,
  number,
] {
  const [width, setWidth] = useState(0);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: T | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    observer.current = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      // Sub-pixel jitter would re-render every chart for nothing.
      setWidth((prev) => (Math.abs(prev - w) < 0.5 ? prev : w));
    });
    observer.current.observe(el);
  }, []);
  return [ref, width];
}
