# 0026 — Deployment-Target Registry & Reachability/Isolation Gates

## Status

Accepted (extends [0020](0020-deploy-scaffolding-and-lint-gate.md), [0009](0009-hybrid-skill-routing.md);
sibling of the runtime registry from [0011](0011-secure-sandbox-and-finops-telemetry.md))

## Context

ADR 0020 made a finished app *deployable* — the `devops` agent generates and merges a CI/CD config in a
post-batch phase (E4). But the **deploy mechanics were tangled into the app-shape skills** and the engine
only statically validated that the workflow YAML *parsed*. Three classes of silent, post-merge failure
survived that gate — each invisible until a human opened the live service:

- **Where-to-deploy was implicit.** WHICH platform an archetype targets (Cloud Run for a web service, a
  GitHub Release for a CLI), the WIF/Cloud-Run mechanics, and the app *shape* (container/server vs CLI
  artifact) all lived together in the `devops_{rest_api,crud_app,cli_tool}.md` archetype skills. Adding a
  future cloud meant editing agent code and re-tangling mechanics into every archetype; there was no SSOT
  for the deployment classification the way `SUPPORTED_ENVIRONMENTS` is the SSOT for the *runtime*.

- **The 403 (reachability) class.** A generated Cloud Run workflow that never granted public invocation
  deploys a service that rejects every anonymous request with HTTP 403. Prompt adherence alone is
  probabilistic — a missed `--allow-unauthenticated` / `allUsers`→`run.invoker` binding passed the
  parse-only gate and reddened only at runtime. Worse, the flag is **IAM, stored outside the Knative service
  spec**: in `services replace` / `metadata:` deploy mode the flag is silently dropped and only an explicit
  IAM binding makes the service public (a real live-403 incident).

- **The overwrite (isolation) class.** A managed Cloud Run service is keyed by `(name, region, project)`. A
  **hardcoded** service name lets one app's deploy silently take over another's live URL with a new revision
  — a real collision risk in a multi-app factory.

- **The README-URL publish broke the autonomy loop.** The post-deploy/post-release step that stamps the live
  URL into `README.md` did a bare `git push`. `actions/checkout` leaves the workspace in **detached HEAD**
  (and a tag-gated release run has no branch at all), so it died with `fatal: You are not currently on a
  branch`; a protected default branch rejected it regardless. The deploy succeeded but the loop never closed
  itself.

## Decision

Make WHERE-an-app-deploys a **registry** (mirroring the runtime registry) and make reachability + isolation
**green-by-construction with a deterministic gate**, never prompt-only. Keep deploy *mechanics* in
platform skills separate from app *shape* in archetype skills.

- **`SUPPORTED_DEPLOY_TARGETS` registry (the WHERE SSOT).** A new registry in `environments.py`, sibling to
  `SUPPORTED_ENVIRONMENTS` (the WHAT/runtime SSOT). Each entry carries `archetypes` (which app archetypes it
  serves), `skill` (its platform skill), `runtime_constraints` (the contract the APP CODE must satisfy —
  bind `$PORT`/`0.0.0.0`, zero-config boot, statelessness, health endpoint), and an optional
  `requires_public_invoker` flag. Consumed via `deploy_target_for_archetype` / `deploy_skill_for_target` /
  `deploy_target_skills`. A deploy target is a *deployment classification*, NOT a programming language — no
  per-language branching (honors the engine-language-agnostic invariant).

- **Platform skills vs archetype skills (Open-Closed, per ADR 0009).** Deploy mechanics (WIF auth, image
  build/push, the Cloud Run deploy step, the public-invoker grant, the README-URL publish, the GitHub
  Release publish) move into **platform skills** `prompts/skills/deploy_{gcp,github_release}.md`; the
  archetype skills keep ONLY the app shape (container/server vs CLI artifact). The DevOps node force-loads
  BOTH sets — archetype skills + the platform skills named by `deploy_target_skills()`. Adding a future cloud
  is ONE registry entry + one `deploy_<cloud>.md`, with no engine edit.

- **Deterministic reachability/isolation gate.** `run_devops_gate(repo_dir, archetype)` is extended beyond
  YAML/Dockerfile-directive linting with two registry-driven, archetype-aware assertions for a
  `requires_public_invoker` target: (1) the workflow grants public invocation — **deploy-mode-aware**: in
  image-deploy mode either `--allow-unauthenticated` OR an `allUsers`→`run.invoker` binding satisfies it, but
  in manifest-deploy mode (the flag is inert) ONLY the explicit IAM binding counts; (2) the service name is
  derived from the repository context (`github.event.repository.name` / `github.repository`), never a static
  literal. A miss feeds the existing `DEVOPS_MAX_RETRIES` self-heal loop. `archetype=None` (or a target
  without the flag, e.g. the CLI path) skips both checks.

- **Runtime-constraint contract propagation.** The SA selects a target (from an injected awareness list) and
  records it in the Blueprint's `## Deployment Target`; the TPM propagates the target's `runtime_constraints`
  into the relevant tickets' architectural constraints; the building agents (TechLead/Developer/QA) satisfy
  them (zero-config boot is also a TechLead HARD-gate contract). The deploy axis thus mirrors the runtime
  axis's `authoring_contract` chain.

- **README-URL publish via the `HEAD:<default-branch>` refspec + a one-time bypass.** The platform skills'
  post-deploy/post-release step commits the live/release URL between pre-seeded markers and pushes with
  `git push origin HEAD:"${{ github.event.repository.default_branch }}"` — the refspec form sends the
  detached-HEAD commit straight to the default-branch ref (resolved from repo context, never a hardcoded
  `main`), with a `[skip ci]` commit to avoid a re-trigger loop. Branch protection is handled out-of-band by
  a one-time `github-actions` **"Allow bypass"** grant (documented in `docs/guides/devops_setup.md`); only
  `contents: write` is needed. (Deliberately distinct from the engine's own E2/E4 forge flow, which lands an
  audited PR via host-side `finalize_pr` under the engine's creds — there is no second reviewer identity
  inside the user's deployed workflow, so a cosmetic URL stamp uses a bypass, not a self-approved PR.)

## Consequences

- Adding a future deploy target (a new cloud, a new registry) is a closed-for-modification change: one
  `SUPPORTED_DEPLOY_TARGETS` entry + one `deploy_<cloud>.md` platform skill, no agent-code edit — the same
  Open-Closed property ADR 0009 gave skill routing and ADR 0011 gave the runtime registry.
- The 403 and overwrite classes are caught at **scaffold time** by a deterministic gate, not at runtime by a
  human — reachability and inter-app isolation become green-by-construction, the same philosophy as the
  `lint_cmd` CI-parity SSOT (ADR 0020).
- The shape/mechanics split keeps a Cloud-Run/WIF detail from leaking back into an archetype skill (and a CLI
  archetype can never accrue a Cloud Run step); a skill miss still yields a correctly-shaped service because
  the archetype branch is also pinned in the `devops.md` system prompt.
- The deploy workflow now closes its own loop autonomously (stamps the live URL) without a human tag/merge,
  at the cost of a one-time per-org branch-protection bypass for the robot identity — a deliberate, narrowly
  scoped trust grant (a `[skip ci]` README commit only), surfaced as an explicit org-setup step rather than a
  hidden default.
- The gate is conservative and archetype-aware: a CLI/library run (`archetype=None` or a target without
  `requires_public_invoker`) is unaffected, so the new assertions never false-positive a non-web build.

## Notes

Seams: `SUPPORTED_DEPLOY_TARGETS` / `deploy_target_for_archetype` / `deploy_skill_for_target` /
`deploy_target_skills` (`src/shared/core/environments.py`); `run_devops_gate` (`src/deployment/provision/gates.py`);
the DevOps skill assembly `_archetype_guidance` + `deploy_target_skills()` (`src/shared/core/prompts.py`);
the platform skills `prompts/skills/deploy_{gcp,github_release}.md` and archetype skills
`prompts/skills/devops_{rest_api,crud_app,cli_tool}.md`; the SA/TPM constraint propagation in
`prompts/system/{sa,tpm}.md`. One-time org setup: `docs/guides/devops_setup.md` (§2.4 the bypass, the WIF
bridge). Related rules: `deploy-scaffolding-and-ci-parity`, `engine-language-agnostic`,
`skill-routing-frontmatter`, `subprocess-and-external-call-safety`.
