#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

# The dashboard half of deploy/install-debian.sh, without root: --ui-only
# against a throwaway checkout, with tarballs made here and a local stand-in
# for the GitHub API. Needs bash, tar, gzip, sha256sum, curl and python3.
#
#   tests/deploy/test-ui-install.sh [dist/giq-ui-<version>.tar.gz]
#
# With a tarball argument (make ui-dist) it also installs that real build.

# `cond && pass ... || fail ...` is if-then-else here: pass always succeeds.
# shellcheck disable=SC2015

set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
script=$here/../../deploy/install-debian.sh
real=${1:+$(readlink -f "$1")}
work=$(mktemp -d)
server_pid=
cleanup() {
    [ -z "$server_pid" ] || kill "$server_pid" 2>/dev/null || true
    rm -rf "$work"
}
trap cleanup EXIT

failures=0
pass() { printf 'ok   %s\n' "$*"; }
fail() { printf 'FAIL %s\n' "$*"; failures=$((failures + 1)); }

prefix=$work/opt/giq
ui=$prefix/src/giq/static/ui
mkdir -p "$prefix/src/giq"
printf '[project]\nname = "giq"\nversion = "9.9.9"\n' >"$prefix/pyproject.toml"

# A tarball the way `make ui-pack` makes one: contents, relative paths.
pack() { # name marker
    local src=$work/src-$2
    mkdir -p "$src/assets" "$work/$2"
    echo "<!doctype html><title>$2</title>" >"$src/index.html"
    echo "react@19 MIT; Inter OFL-1.1" >"$src/THIRD_PARTY_LICENSES.txt"
    echo "console.log('$2')" >"$src/assets/$2.js"
    tar -C "$src" -czf "$work/$2/$1" .
    echo "$work/$2/$1"
}

run() { "$script" --ui-only --prefix "$prefix" "$@"; }
leftovers() { find "$prefix/src/giq/static" -maxdepth 1 -name '.ui.*' | wc -l; }

# --- a tarball --------------------------------------------------------------------

t1=$(pack giq-ui-9.9.9.tar.gz first)
if run --ui-tarball "$t1" >/dev/null 2>&1 && grep -q first "$ui/index.html" &&
    [ -f "$ui/THIRD_PARTY_LICENSES.txt" ] && [ -f "$ui/assets/first.js" ]; then
    pass "installs a tarball"
else
    fail "installs a tarball"
fi
[ "$(stat -c %a "$ui/index.html")" = 644 ] && [ "$(stat -c %a "$ui/assets")" = 755 ] &&
    pass "files 0644, directories 0755" || fail "modes: $(stat -c %a "$ui/index.html" "$ui/assets")"
[ "$(leftovers)" = 0 ] && pass "no temporary directories left" || fail "leftover .ui.* directories"

t2=$(pack giq-ui-9.9.9.tar.gz second)
if run --ui-tarball "$t2" >/dev/null 2>&1 && grep -q second "$ui/index.html" &&
    [ ! -e "$ui/assets/first.js" ] && [ "$(leftovers)" = 0 ]; then
    pass "replaces an existing dashboard wholesale"
else
    fail "replaces an existing dashboard wholesale"
fi
run --ui-tarball "$t2" >/dev/null 2>&1 && grep -q second "$ui/index.html" &&
    pass "running it again is harmless" || fail "second identical run"

out=$(run --ui-tarball "$(pack giq-ui-1.0.0.tar.gz third)" 2>&1) &&
    grep -q "not the checkout's version" <<<"$out" &&
    pass "warns about a version mismatch" || fail "no version-mismatch warning"

# --- bad tarballs leave the installed dashboard alone -----------------------------

run --ui-tarball "$t2" >/dev/null 2>&1
before=$(find "$ui" -type f -exec sha256sum {} + | sort)
rejects() { # description tarball [needle]
    local out
    if out=$(run --ui-tarball "$2" 2>&1); then
        fail "$1: accepted"
    elif [ -n "${3:-}" ] && ! grep -q "$3" <<<"$out"; then
        fail "$1: wrong error: $out"
    elif [ "$(find "$ui" -type f -exec sha256sum {} + | sort)" != "$before" ]; then
        fail "$1: the installed dashboard changed"
    elif [ "$(leftovers)" != 0 ]; then
        fail "$1: left temporary directories"
    else
        pass "$1: refused, previous dashboard intact"
    fi
}

src=$work/src-nolicence && mkdir -p "$src" && echo x >"$src/index.html"
tar -C "$src" -czf "$work/nolicence.tar.gz" .
rejects "no THIRD_PARTY_LICENSES.txt" "$work/nolicence.tar.gz" THIRD_PARTY_LICENSES

src=$work/src-noindex && mkdir -p "$src" && echo x >"$src/THIRD_PARTY_LICENSES.txt"
tar -C "$src" -czf "$work/noindex.tar.gz" .
rejects "no index.html" "$work/noindex.tar.gz" index.html

src=$work/src-nested && mkdir -p "$src/ui" && echo x >"$src/ui/index.html" &&
    echo x >"$src/ui/THIRD_PARTY_LICENSES.txt"
tar -C "$src" -czf "$work/nested.tar.gz" ui
rejects "the directory packed instead of its contents" "$work/nested.tar.gz" "top level"

# GNU tar will not write a '..' member, so Python does.
python3 - "$work/climb.tar.gz" <<'PY'
import io, sys, tarfile
with tarfile.open(sys.argv[1], "w:gz") as t:
    for name in ("./index.html", "./THIRD_PARTY_LICENSES.txt", "./assets/../../evil"):
        info = tarfile.TarInfo(name)
        info.size = 2
        t.addfile(info, io.BytesIO(b"x\n"))
PY
rejects "a '..' path" "$work/climb.tar.gz" "'..'"

src=$work/src-link && mkdir -p "$src" && echo x >"$src/index.html" &&
    echo x >"$src/THIRD_PARTY_LICENSES.txt" && ln -s /etc/passwd "$src/passwd"
tar -C "$src" -czf "$work/link.tar.gz" .
rejects "a symlink" "$work/link.tar.gz" "plain files"

head -c 300 "$t2" >"$work/truncated.tar.gz"
rejects "a truncated tarball" "$work/truncated.tar.gz"

if run --ui-tarball "$work/does-not-exist.tar.gz" >/dev/null 2>&1; then
    fail "a missing file: accepted"
else
    pass "a missing file: refused"
fi

# --- no source and no Node.js -------------------------------------------------------

mkdir -p "$work/fakebin"
printf '#!/bin/sh\nexit 1\n' >"$work/fakebin/node"
cp "$work/fakebin/node" "$work/fakebin/npm"
chmod +x "$work/fakebin/node" "$work/fakebin/npm"
out=$(PATH=$work/fakebin:$PATH run 2>&1) && fail "--ui-only with nothing to install: accepted" ||
    { grep -q -- "--ui-tarball or --ui-release" <<<"$out" &&
        pass "--ui-only with no source and no Node.js says what to pass" ||
        fail "--ui-only with no source: $out"; }

# --- from a release ------------------------------------------------------------------

rel=$work/release
mkdir -p "$rel"
t3=$(pack giq-ui-9.9.9.tar.gz released)
cp "$t3" "$rel/giq-ui-9.9.9.tar.gz"
(cd "$rel" && sha256sum giq-ui-9.9.9.tar.gz >SHA256SUMS && echo "0000  giq-9.9.9.tar.gz" >>SHA256SUMS)

# The API's shape: the release by tag lists assets by API URL, and an asset
# URL serves the bytes only with Accept: application/octet-stream. Everything
# answers 404 without the token, as GitHub does for a private repository.
cat >"$work/server.py" <<'PY'
import http.server, json, os, sys

rel, portfile = sys.argv[1], sys.argv[2]

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer sekrit":
            return self.send(404, b'{"message": "Not Found"}')
        base = f"http://127.0.0.1:{self.server.server_port}"
        if self.path == "/repos/acme/giq/releases/tags/v9.9.9":
            assets = [{"name": n, "url": f"{base}/assets/{n}",
                       "browser_download_url": "https://example.invalid/"}
                      for n in sorted(os.listdir(rel))]
            return self.send(200, json.dumps({"tag_name": "v9.9.9", "assets": assets}).encode())
        if self.path.startswith("/assets/"):
            if self.headers.get("Accept") != "application/octet-stream":
                return self.send(200, b'{"name": "metadata, not the file"}')
            path = os.path.join(rel, self.path[len("/assets/"):])
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    return self.send(200, f.read(), "application/octet-stream")
        self.send(404, b'{"message": "Not Found"}')

s = http.server.HTTPServer(("127.0.0.1", 0), H)
with open(portfile, "w") as f:
    f.write(str(s.server_port))
s.serve_forever()
PY
python3 "$work/server.py" "$rel" "$work/port" &
server_pid=$!
for _ in $(seq 50); do [ -s "$work/port" ] && break; sleep 0.1; done
api=http://127.0.0.1:$(cat "$work/port")

from_release() {
    GIQ_GITHUB_API=$api run --repo https://github.com/acme/giq.git --ui-release v9.9.9
}

GIQ_GITHUB_TOKEN=sekrit from_release >/dev/null 2>&1 && grep -q released "$ui/index.html" &&
    pass "installs from a release, checked against SHA256SUMS" || fail "install from a release"

run --ui-tarball "$t2" >/dev/null 2>&1
before=$(find "$ui" -type f -exec sha256sum {} + | sort)
if GIQ_GITHUB_TOKEN=wrong from_release >/dev/null 2>&1; then
    fail "a token that cannot read the repository: accepted"
else
    pass "a token that cannot read the repository: refused"
fi

echo tampered >>"$rel/giq-ui-9.9.9.tar.gz"
out=$(GIQ_GITHUB_TOKEN=sekrit from_release 2>&1) && fail "a tampered asset: accepted" ||
    { grep -q "does not match" <<<"$out" &&
        [ "$(find "$ui" -type f -exec sha256sum {} + | sort)" = "$before" ] &&
        pass "a tampered asset: refused, previous dashboard intact" ||
        fail "a tampered asset: $out"; }

GIQ_GITHUB_TOKEN=sekrit GIQ_GITHUB_API=http://127.0.0.1:9 run --repo https://github.com/acme/giq.git \
    --ui-release v9.9.9 --ui-tarball "$t1" >/dev/null 2>&1 && grep -q first "$ui/index.html" &&
    pass "--ui-tarball wins over --ui-release" || fail "--ui-tarball over --ui-release"

# --- the real build ------------------------------------------------------------------

if [ -n "$real" ]; then
    ver=$(basename "$real" .tar.gz)
    ver=${ver#giq-ui-}
    printf '[project]\nname = "giq"\nversion = "%s"\n' "$ver" >"$prefix/pyproject.toml"
    out=$(run --ui-tarball "$real" 2>&1) && [ -f "$ui/index.html" ] &&
        grep -q 'react@' "$ui/THIRD_PARTY_LICENSES.txt" && ! grep -q warning <<<"$out" &&
        pass "installs $(basename "$real")" || fail "installing $(basename "$real"): $out"
fi

if [ "$failures" -gt 0 ]; then
    echo "$failures failed"
    exit 1
fi
echo "all passed"
