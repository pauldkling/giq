// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "./ConfirmDialog";

/* window.confirm/alert replaced by themed, translatable dialogs that
   resolve a promise: `if (await confirm({...})) …`. One dialog at a time;
   a second request waits for the first to close. */

export interface ConfirmOptions {
  title: ReactNode;
  body?: ReactNode;
  /** Defaults to "Confirm". */
  confirmLabel?: string;
  /** Defaults to "Cancel". */
  cancelLabel?: string;
  danger?: boolean;
}

export interface NotifyOptions {
  title: ReactNode;
  body?: ReactNode;
  /** Defaults to "OK". */
  okLabel?: string;
}

interface Request {
  opts: ConfirmOptions & { notice?: boolean };
  resolve: (ok: boolean) => void;
}

interface DialogApi {
  confirm: (o: ConfirmOptions) => Promise<boolean>;
  notify: (o: NotifyOptions) => Promise<void>;
}

const Ctx = createContext<DialogApi | null>(null);

export function DialogProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [current, setCurrent] = useState<Request | null>(null);
  const waiting = useRef<Request[]>([]);

  const enqueue = useCallback((req: Request) => {
    setCurrent((cur) => {
      if (cur) {
        waiting.current.push(req);
        return cur;
      }
      return req;
    });
  }, []);

  const finish = (ok: boolean) => {
    current?.resolve(ok);
    setCurrent(waiting.current.shift() ?? null);
  };

  const api = useMemo<DialogApi>(
    () => ({
      confirm: (opts) => new Promise<boolean>((resolve) => enqueue({ opts, resolve })),
      notify: ({ okLabel, ...rest }) =>
        new Promise<void>((resolve) =>
          enqueue({ opts: { ...rest, confirmLabel: okLabel, notice: true }, resolve: () => resolve() }),
        ),
    }),
    [enqueue],
  );

  const o = current?.opts;
  return (
    <Ctx.Provider value={api}>
      {children}
      {o && (
        <ConfirmDialog
          title={o.title}
          body={o.body}
          danger={o.danger}
          confirmLabel={o.confirmLabel ?? (o.notice ? t("actions.ok") : t("actions.confirm"))}
          cancelLabel={o.notice ? undefined : (o.cancelLabel ?? t("actions.cancel"))}
          onConfirm={() => finish(true)}
          onCancel={() => finish(false)}
        />
      )}
    </Ctx.Provider>
  );
}

function useDialogs(): DialogApi {
  const api = useContext(Ctx);
  if (!api) throw new Error("dialog hooks used outside DialogProvider");
  return api;
}

/** `await confirm({title, body, confirmLabel, danger})` → true when confirmed. */
export const useConfirm = () => useDialogs().confirm;

/** `await notify({title, body})` — the themed replacement for alert(). */
export const useNotify = () => useDialogs().notify;
