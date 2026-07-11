#!/usr/bin/env python3
"""Resolve Alpine apk dependency closures and emit Starlark pin tables.

Downloads the v3.22 APKINDEX for main+community on x86_64+aarch64, resolves
the transitive dependency closure of each root set below (so:/pc:/cmd:
providers included), downloads every .apk in the closure and sha256s it, then
prints `(name, version, repo, {arch: sha256})` tuples ready to paste into
BUILD.jobs. Run from anywhere; caches downloads under ./.apk-cache.
"""

import hashlib
import io
import os
import sys
import tarfile
import urllib.request

MIRROR = "https://dl-cdn.alpinelinux.org/alpine/v3.22"
ARCHES = ["x86_64", "aarch64"]
REPOS = ["main", "community"]

ROOT_SETS = {
    # gitaly/git build userland: gcc toolchain + meson/ninja + git's -dev deps.
    "GITALY_BUILD_APKS": [
        "busybox", "busybox-binsh", "gcc", "musl-dev", "make", "meson",
        "pkgconf", "zlib-dev", "openssl-dev", "curl-dev", "pcre2-dev",
        "linux-headers",
    ],
    # gitaly runtime: loader + shared libs the meson-built git links against.
    "GITALY_RUNTIME_APKS": [
        "musl", "busybox", "zlib", "libcurl", "pcre2", "libssl3",
        "libcrypto3", "ca-certificates-bundle",
    ],
    # workhorse runtime: exiftool (perl) for image scrubbing.
    "WORKHORSE_RUNTIME_APKS": [
        "musl", "busybox", "exiftool",
    ],
}


def fetch(url):
    with urllib.request.urlopen(url) as r:
        return r.read()


def parse_index(data):
    """APKINDEX.tar.gz -> list of dicts with P/V/D/p/k fields."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        raw = tf.extractfile("APKINDEX").read().decode()
    pkgs = []
    cur = {}
    for line in raw.splitlines():
        if not line.strip():
            if cur:
                pkgs.append(cur)
                cur = {}
            continue
        if len(line) > 2 and line[1] == ":":
            cur[line[0]] = line[2:]
    if cur:
        pkgs.append(cur)
    return pkgs


def strip_constraint(tok):
    for sep in ["><", ">=", "<=", "=", ">", "<", "~"]:
        if sep in tok:
            return tok.split(sep)[0]
    return tok


def build_universe(arch):
    """name/provider -> (entry, repo); entry name -> (entry, repo)."""
    by_name = {}
    providers = {}
    for repo in REPOS:
        for e in parse_index(fetch(f"{MIRROR}/{repo}/{arch}/APKINDEX.tar.gz")):
            name = e["P"]
            by_name.setdefault(name, (e, repo))
            for p in e.get("p", "").split():
                key = strip_constraint(p)
                prio = int(e.get("k", "0") or "0")
                cur = providers.get(key)
                if cur is None or prio > cur[2]:
                    providers[key] = (e, repo, prio)
    return by_name, providers


def resolve(roots, by_name, providers):
    """BFS closure; returns {name: (entry, repo)}."""
    out = {}
    todo = list(roots)
    while todo:
        want = strip_constraint(todo.pop())
        if want.startswith("!"):
            continue
        hit = by_name.get(want)
        if hit is None and want in providers:
            e, repo, _ = providers[want]
            hit = (e, repo)
        if hit is None:
            print(f"  !! no provider for {want}", file=sys.stderr)
            continue
        e, repo = hit
        if e["P"] in out:
            continue
        out[e["P"]] = (e, repo)
        todo.extend(e.get("D", "").split())
    return out


def apk_sha256(repo, arch, name, version):
    os.makedirs(".apk-cache", exist_ok=True)
    fn = f".apk-cache/{arch}-{name}-{version}.apk"
    if not os.path.exists(fn):
        url = f"{MIRROR}/{repo}/{arch}/{name}-{version}.apk"
        with open(fn, "wb") as f:
            f.write(fetch(url))
    with open(fn, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    uni = {arch: build_universe(arch) for arch in ARCHES}
    for set_name, roots in ROOT_SETS.items():
        per_arch = {}
        for arch in ARCHES:
            by_name, providers = uni[arch]
            per_arch[arch] = resolve(roots, by_name, providers)
        names = sorted(set().union(*[set(v) for v in per_arch.values()]))
        print(f"\n{set_name} = [")
        for n in names:
            entries = {a: per_arch[a].get(n) for a in ARCHES}
            missing = [a for a, e in entries.items() if e is None]
            if missing:
                print(f"    # {n}: MISSING on {missing}", file=sys.stderr)
                continue
            versions = {a: e[0]["V"] for a, e in entries.items()}
            repo = entries[ARCHES[0]][1]
            if len(set(versions.values())) != 1:
                print(f"    # {n}: version mismatch {versions}", file=sys.stderr)
            ver = versions[ARCHES[0]]
            shas = {a: apk_sha256(entries[a][1], a, n, versions[a]) for a in ARCHES}
            sha_str = ", ".join(f'"{a}": "{shas[a]}"' for a in ARCHES)
            print(f'    ("{n}", "{ver}", "{repo}", {{{sha_str}}}),')
        print("]")


if __name__ == "__main__":
    main()
