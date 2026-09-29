// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import "./Menu.css";

/* An accessible popover menu. Only one is open app-wide: opening one closes
   whichever was open (a module-level slot rather than a context, since the
   rule is global by definition). A click outside, Escape or Tab closes it;
   Escape returns focus to the trigger. Arrow keys move between items. */

let closeOpenMenu: (() => void) | null = null;

export interface MenuProps {
  /** Contents of the trigger button. */
  label: ReactNode;
  /** Accessible name of the trigger when its contents are only an icon. */
  ariaLabel?: string;
  /** Classes of the trigger button (default: Nocturne secondary). */
  buttonClassName?: string;
  title?: string;
  disabled?: boolean;
  /** Which edge of the trigger the popover aligns to. */
  align?: "start" | "end";
  /** The items; the render-prop form receives close() for custom content. */
  children: ReactNode | ((close: () => void) => ReactNode);
  onOpenChange?: (open: boolean) => void;
}

export function Menu({
  label,
  ariaLabel,
  buttonClassName = "btn btn-secondary",
  title,
  disabled,
  align = "end",
  children,
  onOpenChange,
}: MenuProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const popover = useRef<HTMLDivElement>(null);
  const id = useId();

  const close = useCallback(() => setOpen(false), []);
  // A notification, not an input: kept in a ref so a new callback identity
  // on every parent render does not re-register the outside-click listener.
  const onOpenChangeRef = useRef(onOpenChange);
  onOpenChangeRef.current = onOpenChange;

  const items = () =>
    Array.from(popover.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? []);

  useEffect(() => {
    onOpenChangeRef.current?.(open);
    if (!open) return;
    if (closeOpenMenu && closeOpenMenu !== close) closeOpenMenu();
    closeOpenMenu = close;
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      if (closeOpenMenu === close) closeOpenMenu = null;
    };
  }, [open, close]);

  const focusItem = (i: number) => {
    const list = items();
    if (!list.length) return;
    list[(i + list.length) % list.length]!.focus();
  };

  const onButtonKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
      const last = e.key === "ArrowUp";
      requestAnimationFrame(() => focusItem(last ? -1 : 0));
    }
  };

  const onMenuKey = (e: KeyboardEvent) => {
    const list = items();
    const at = list.indexOf(document.activeElement as HTMLElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      focusItem(at + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      focusItem(at - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      focusItem(0);
    } else if (e.key === "End") {
      e.preventDefault();
      focusItem(-1);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      button.current?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  };

  return (
    <div className="menu-root" ref={root}>
      <button
        ref={button}
        type="button"
        className={buttonClassName}
        title={title}
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        disabled={disabled}
        onClick={() => {
          const next = !open;
          setOpen(next);
          // Keyboard activation (Enter/Space) lands focus on the first item.
          if (next) requestAnimationFrame(() => focusItem(0));
        }}
        onKeyDown={onButtonKey}
      >
        {label}
      </button>
      {open && (
        <div
          ref={popover}
          id={id}
          role="menu"
          className={`menu-popover menu-${align}`}
          onKeyDown={onMenuKey}
          // An item's own onSelect runs first; any click on an item then closes.
          onClick={(e) => {
            if ((e.target as HTMLElement).closest('[role="menuitem"]')) setOpen(false);
          }}
        >
          {typeof children === "function" ? children(close) : children}
        </div>
      )}
    </div>
  );
}
