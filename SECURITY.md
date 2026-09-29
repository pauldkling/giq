<!--
SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)

SPDX-License-Identifier: Apache-2.0
-->

# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's **Report a
vulnerability** button on the repository's Security tab — not in a public
issue. Include what you found, how to reproduce it, and the giq version
(`/status` reports it).

You will get an acknowledgement within a few working days. Fixes are released
as a new version; the advisory is published once a fixed release is out.

## Scope

giq runs models on a machine it controls and exposes an HTTP API. Of
particular interest:

- bypasses of the access rules — Host and Origin checks, the optional token
  (see [docs/access-and-privacy.md](docs/access-and-privacy.md));
- anything that lets a request execute code, read files or spawn processes
  outside the configured engines;
- request content (prompts, documents, audio, images) leaking into logs, the
  stats database or error responses, which giq promises not to record.

Vulnerabilities in the engines giq starts (llama.cpp, stable-diffusion.cpp,
vLLM, …) or in model weights belong with those projects; a report here is
still welcome when giq's use of them makes the issue reachable.

## Supported versions

Security fixes land on the latest release only.
