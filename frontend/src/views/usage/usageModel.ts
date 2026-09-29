// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { GpuEra, StatsUsage, UsagePeriod } from "../../api/types";
import type { BarBucket } from "../../components/charts";
import { assignSeriesColors } from "../../lib/series";

/* The usage view's arithmetic, kept free of React so it can be tested
   without a DOM: the chart's x-domain, its bucket labels, the stacks, and
   which card era is the current one. */

type Row = { worker: string; model: string };

/* Keyed on worker/model, not model: flux_klein exists under both text2image
   and image_edit, and they are different entities. */
export const modelKey = (m: Row): string => `${m.worker}/${m.model}`;

const tokens = (r: { tokens_in: number | null; tokens_out: number | null }): number =>
  (r.tokens_in ?? 0) + (r.tokens_out ?? 0);

const pad2 = (n: number) => String(n).padStart(2, "0");
/** The server's local-time day key, "YYYY-MM-DD". */
export const dayKey = (d: Date): string =>
  `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;

/* The full x-domain of bucket keys, so quiet hours and days render as gaps
   rather than as missing columns that squeeze the rest together. The keys
   match what /stats/usage emits (strftime in the server's local time):
   "YYYY-MM-DD HH:00" for a day, "YYYY-MM-DD" for a week or a month,
   "YYYY-MM" for all time — where the domain is only the months actually
   seen, since "all" has no fixed start. */
export function usageDomain(period: UsagePeriod, present: string[], now = new Date()): string[] {
  if (period === "all") return [...new Set(present)].sort();
  const keys: string[] = [];
  if (period === "day") {
    for (let h = 0; h <= now.getHours(); h++) keys.push(`${dayKey(now)} ${pad2(h)}:00`);
    return keys;
  }
  const days = period === "week" ? 7 : 30;
  for (let i = days - 1; i >= 0; i--) {
    // Calendar arithmetic, not now − i·24 h, so a DST switch cannot skip or repeat a day.
    keys.push(dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() - i)));
  }
  return keys;
}

/** A bucket key back to the local Date it starts at. */
export function bucketDate(b: string): Date {
  const [date = "", time] = b.split(" ");
  const [y = 1970, m = 1, d = 1] = date.split("-").map(Number);
  const h = time ? Number(time.slice(0, 2)) : 0;
  return new Date(y, m - 1, d, h);
}

const dtf = new Map<string, Intl.DateTimeFormat>();
function df(lang: string, opts: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = lang + JSON.stringify(opts);
  let f = dtf.get(key);
  if (!f) dtf.set(key, (f = new Intl.DateTimeFormat(lang, opts)));
  return f;
}

/** Axis label for a bucket: the hour for a day, the date for a week or month, month and year for all time. */
export function bucketLabel(b: string, period: UsagePeriod, lang: string): string {
  const d = bucketDate(b);
  if (period === "day") return df(lang, { hour: "2-digit", minute: "2-digit" }).format(d);
  if (period === "all") return df(lang, { month: "short", year: "numeric" }).format(d);
  return df(lang, { month: "short", day: "numeric" }).format(d);
}

/** Tooltip heading for a bucket: a little more than the axis has room for. */
export function bucketTitle(b: string, period: UsagePeriod, lang: string): string {
  const d = bucketDate(b);
  if (period === "day") {
    const end = new Date(d.getTime() + 3600_000);
    return df(lang, { hour: "2-digit", minute: "2-digit" }).formatRange(d, end);
  }
  if (period === "all") return df(lang, { month: "long", year: "numeric" }).format(d);
  return df(lang, { weekday: "short", month: "short", day: "numeric" }).format(d);
}

export type SeriesPoint = StatsUsage["series"][number];

export interface UsageChart {
  /** Every bucket of the domain; each segment id is a model key, value its tokens. */
  buckets: BarBucket[];
  /** The domain keys, parallel to buckets (for labels and tooltips). */
  keys: string[];
  /** Per bucket: the series points behind its segments, bottom to top. */
  points: SeriesPoint[][];
  /** The models that have tokens in the window, in stack/legend order. */
  models: Row[];
  colors: Map<string, string>;
}

/* Stacks follow the per-model table's order (most tokens first, bottom of
   the stack), and only models with tokens take part: an image model's calls
   carry no tokens and would be an empty legend entry. Colours are assigned
   over every model in the window, alphabetically, so a model keeps its
   colour when a period or GPU switch changes what else is on screen. */
export function buildUsageChart(d: StatsUsage, period: UsagePeriod, now = new Date()): UsageChart {
  const colors = assignSeriesColors(d.models.map(modelKey));
  const models = d.models.filter((m) => tokens(m) > 0);
  const order = models.map(modelKey);
  const perBucket = new Map<string, Map<string, SeriesPoint>>();
  for (const p of d.series) {
    let per = perBucket.get(p.b);
    if (!per) perBucket.set(p.b, (per = new Map()));
    per.set(modelKey(p), p);
  }
  const keys = usageDomain(
    period,
    d.series.map((p) => p.b),
    now,
  );
  const points: SeriesPoint[][] = [];
  const buckets = keys.map((key) => {
    const per = perBucket.get(key);
    const stack = order.flatMap((k) => {
      const p = per?.get(k);
      return p && tokens(p) > 0 ? [p] : [];
    });
    points.push(stack);
    return {
      key,
      segments: stack.map((p) => ({
        id: modelKey(p),
        value: tokens(p),
        color: colors.get(modelKey(p)) ?? "var(--series-other)",
      })),
    };
  });
  return { buckets, keys, points, models, colors };
}

/* Token accounting starts later than the call log: an LLM call recorded
   before it counts as a call with no tokens. When such calls fall in the
   window the chart undercounts, and the hint says so. */
export const predatesTokenAccounting = (d: StatsUsage): boolean =>
  d.models.some(
    (m) => m.worker === "llm" && m.jobs > 0 && m.tokens_in == null && m.tokens_out == null,
  );

/** Eras seen within this long are "current" when the live GPU list is unavailable. */
const CURRENT_WINDOW_S = 300;

/* An era is current when its card is in the machine now. The live /gpus
   list says so directly; without it (nvidia-smi failing, first paint),
   an era whose card was sampled in the last five minutes counts, which is
   what the sampler's cadence guarantees for an installed card. */
export function isCurrentEra(e: GpuEra, liveUuids: Set<string> | null, nowS = Date.now() / 1000): boolean {
  if (liveUuids && liveUuids.size) return liveUuids.has(e.uuid);
  return e.last_seen > nowS - CURRENT_WINDOW_S;
}

/** Newest first: the current card is the one the reader cares about. */
export const erasNewestFirst = (eras: GpuEra[]): GpuEra[] =>
  [...eras].sort((a, b) => b.first_seen - a.first_seen);

/** Tokens of an era, or null when none were recorded (it predates accounting). */
export const eraTokens = (e: GpuEra): number | null =>
  e.tokens_in == null && e.tokens_out == null ? null : tokens(e);
