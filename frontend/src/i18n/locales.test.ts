// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/* Every language carries every key of English, and nothing a translator
   left blank: a missing key silently falls back to English mid-sentence,
   an empty one renders as nothing at all. Walks the locales folder, so a new
   namespace or language is covered without touching this file. */

const dir = join(__dirname, "..", "locales");
const langs = readdirSync(dir, { withFileTypes: true })
  .filter((d) => d.isDirectory())
  .map((d) => d.name);
const namespaces = readdirSync(join(dir, "en")).filter((f) => f.endsWith(".json"));

type Tree = { [k: string]: string | Tree };
const load = (lang: string, ns: string): Tree =>
  JSON.parse(readFileSync(join(dir, lang, ns), "utf8")) as Tree;

function flatten(t: Tree, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [k, v] of Object.entries(t)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (typeof v === "string") out.set(key, v);
    else for (const [kk, vv] of flatten(v, key)) out.set(kk, vv);
  }
  return out;
}

// i18next plural suffixes: languages differ in which forms they need, so
// "_one"/"_other" keys are compared by their stem.
const PLURAL = /_(zero|one|two|few|many|other)$/;
const stems = (keys: Iterable<string>) => new Set([...keys].map((k) => k.replace(PLURAL, "")));

describe("locales", () => {
  it("has English and German", () => {
    expect(langs).toContain("en");
    expect(langs).toContain("de");
  });

  for (const lang of langs.filter((l) => l !== "en")) {
    for (const ns of namespaces) {
      it(`${lang}/${ns} has exactly the keys of en/${ns}`, () => {
        const en = flatten(load("en", ns));
        const other = flatten(load(lang, ns));
        expect([...stems(other.keys())].sort()).toEqual([...stems(en.keys())].sort());
      });

      it(`${lang}/${ns} leaves nothing blank that English fills`, () => {
        const en = flatten(load("en", ns));
        const other = flatten(load(lang, ns));
        const blank = [...en]
          .filter(([k, v]) => v.trim() !== "" && other.has(k) && other.get(k)!.trim() === "")
          .map(([k]) => k);
        expect(blank).toEqual([]);
      });

      it(`${lang}/${ns} keeps every {{placeholder}}`, () => {
        const en = flatten(load("en", ns));
        const other = flatten(load(lang, ns));
        const vars = (s: string) => [...s.matchAll(/{{\s*(\w+)\s*}}/g)].map((m) => m[1]).sort();
        const wrong = [...en]
          .filter(([k, v]) => other.has(k) && vars(v).join() !== vars(other.get(k)!).join())
          .map(([k]) => k);
        expect(wrong).toEqual([]);
      });
    }
  }
});
