# gitlab-build

Hermetic, offline [JOBS](https://github.com/draganm/jobs) builds of the
Cloud Native GitLab (Community Edition) components. Every build runs
`net=none`; every byte consumed is a pinned, content-addressed import.

## Components (phase 1)

| `--param component=` | upstream | output |
|---|---|---|
| `shell` | gitlab-org/gitlab-shell | `bin/gitlab-shell`, `bin/gitlab-sshd`, checks |
| `pages` | gitlab-org/gitlab-pages | `bin/gitlab-pages` |
| `kas` | gitlab-org/cluster-integration/gitlab-agent | `bin/kas` |
| `registry` | gitlab-org/container-registry | `bin/registry` |
| `workhorse` | gitlab-foss `workhorse/` (the master pin) | `bin/gitlab-workhorse` + zip/resize tools |
| `gitaly` | gitlab-org/gitaly | `bin/gitaly` (embeds 2 meson-built bundled gits + aux binaries), praefect, wrapper, backup |
| `rails` | gitlab-org/gitlab-foss | app tree: Ruby 3.3.11 built from source, 579 production gems (musl monsters precompiled), `bin/web` + `bin/sidekiq` |
| `webservice` | gitlab-org/gitlab-foss | rails + yarn-offline webpack assets (`public/assets/webpack/manifest.json`) |

**Verification status (2026-07-12):** shell/pages/kas/registry/workhorse/gitaly
green on the cluster on both arches; `rails` and `webservice` build green
hermetically (local runner, linux/amd64; rails also completed once on the
arm64 cluster runner) — repeated cluster runs of the two monolith components
currently trip JOBS engine/runner scalability bugs under the ~950-import
storm (WriteRefs ack collapse, silent runner wedge, persisted FAILED /
unplaceable verdicts), tracked in draganm/jobs issues.

`jobs image --param component=pages` produces an OCI tarball whose
`docker run` executes the built binary (phase-5 check).

The `sidekiq` role needs no separate build: the rails/webservice artifacts
carry both `bin/web` and `bin/sidekiq`; select at image/deploy time.

Planned next: workhorse, gitaly (bundled git from source), ruby-from-source,
rails, sidekiq, webservice — see the design doc
(`draganm/jobs` → `docs/superpowers/specs/2026-07-11-gitlab-cng-build-design.md`).

## Pinning

`GITLAB` (gitlab-org/gitlab-foss stable CE tag) is the master pin. Satellite
pins are static but **self-checking**: at pin time the recipe reads the
GitLab tree's `GITLAB_*_VERSION` files and fails loudly — with the expected
version — if a satellite pin drifts. container-registry releases
independently and carries its own pin.

**Bump procedure:** update `GITLAB`, run any satellite build, copy the
expected versions from the assertion failures into `SATELLITES`.

Sources come from gitlab.com via
[fetcher-gitlab](https://github.com/jobs-build/fetcher-gitlab) (ref-addressed,
no sha256 — same trust model as fetcher-github). Go modules are resolved by
[plugin-go](https://github.com/jobs-build/plugin-go) from each component's
`go.sum`, one content-addressed import per module.

## Build it

```sh
# on a JOBS cluster:
jobs remote-build --source-dir . --param component=shell

# local (Linux, rootless userns):
jobs run --source . --param component=pages
```
