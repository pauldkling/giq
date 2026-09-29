<!--
SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)

SPDX-License-Identifier: Apache-2.0
-->

# Contributing

Issues and pull requests are welcome. For anything larger than a fix, open an
issue first so the approach can be agreed before the work.

## Setup

```bash
make sync        # Python environments (giq + worker interpreters) and the dashboard
make ui-dev      # dashboard dev server against a running giq
```

See [docs/development.md](docs/development.md) for the layout and
[AGENTS.md](AGENTS.md) for the conventions — they apply to people and coding
agents alike.

## Before sending a pull request

```bash
make test                                  # CPU test suite
make check                                 # ruff + ty
cd frontend && npx tsc --noEmit && npm test
uvx reuse lint
```

`prek install` (or `pre-commit install`) runs the formatting, lint and REUSE
checks on every commit.

- One theme per commit, conventional style (`feat(ocr): …`, `fix: …`,
  `docs: …`).
- New files carry an SPDX header:
  `reuse annotate --copyright "vikworks UG (haftungsbeschränkt)" --license Apache-2.0 <file>`.
- User-facing dashboard strings go into both `en` and `de`.
- Nothing that needs a GPU runs in CI; say in the pull request what you tested
  on real hardware, and on which card.

## Licence

By contributing you agree that your contribution is licensed under the
Apache License 2.0, the licence of this project (see [LICENSE](LICENSE)).
