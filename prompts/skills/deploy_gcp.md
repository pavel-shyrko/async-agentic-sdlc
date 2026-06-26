---
skill_id: deploy_gcp
type: domain
triggers: [gcp, cloud-run]
nodes: [devops]
---
DEPLOY TARGET: Google Cloud Run (web services) via Workload Identity Federation. This is the PLATFORM layer — HOW to deploy to GCP, independent of the app's shape. The archetype skill defines the container/server; this skill defines the GCP deploy workflow.

## Authentication — Workload Identity Federation (NO embedded credentials)
- Authenticate with `google-github-actions/auth` using `workload_identity_provider: ${{ secrets.GCP_WIF_PROVIDER }}` and `service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}` — NEVER a key JSON, token, or password.
- `permissions: { id-token: write, contents: write }` — `id-token: write` is required for WIF; `contents: write` is required for the post-deploy README commit (below).
- Secrets vs variables (the org is pre-provisioned this way — see docs/guides/devops_setup.md): `GCP_WIF_PROVIDER` + `GCP_SERVICE_ACCOUNT` are repository **secrets** (`${{ secrets.* }}`); `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_REGISTRY_NAME` are repository **variables** (`${{ vars.* }}`). Never inline a key, project id, or region.
- **Add `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true` to the workflow-level `env:` block.** The `google-github-actions/auth` and `google-github-actions/deploy-cloudrun` actions are JavaScript actions that bundle Node.js 20 internally; GitHub Actions runners emit a deprecation warning for Node 20 and will drop support in a future runner version. Setting this flag at the workflow level forces all bundled-Node JS actions to run under Node 24 without requiring individual action version bumps. Place it at the top-level `env:` key (parallel to `jobs:` and `on:`), not inside a step:
  ```yaml
  env:
    FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true
  ```

## Service naming — derive it from the repository, NEVER hardcode
- **FORBIDDEN: a static, hardcoded Cloud Run service name** (`fastapi-app`, `echo-service`, `my-api`, …). Cloud Run keys a service by `(name, region, project)`; deploying a second app under a name already in use does NOT create a new service — it overwrites the existing one with a new revision, silently taking over its URL. In a multi-app factory that means apps clobber each other.
- **The service name MUST be derived from the GitHub repository context** so every repo gets a distinct, stable service: use `${{ github.event.repository.name }}`. Use that SAME derived value as the `<service>` token in BOTH the image path (below) and the deploy step (so the image repo and the service line up).
- **Optional branch isolation:** if a workflow ever deploys non-default branches, suffix the branch to keep per-branch services separate — sanitize it first (Cloud Run names are lowercase, `[a-z0-9-]`, ≤63 chars): `echo "BRANCH=$(echo '${{ github.ref_name }}' | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g')" >> "$GITHUB_ENV"`, then `service: ${{ github.event.repository.name }}-${{ env.BRANCH }}`. The default workflow triggers on the default branch only, so the bare repo name is normally sufficient.

## Build + push the image (Artifact Registry)
- Configure docker auth for Artifact Registry: `gcloud auth configure-docker ${{ vars.GCP_REGION }}-docker.pkg.dev --quiet`.
- Build the image tag from `${{ vars.GCP_REGION }}`, `${{ vars.GCP_PROJECT_ID }}`, `${{ vars.GCP_REGISTRY_NAME }}` and the repo-derived `<service>` name (e.g. `${{ vars.GCP_REGION }}-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/${{ vars.GCP_REGISTRY_NAME }}/${{ github.event.repository.name }}:${{ github.sha }}`), then `docker build` + `docker push`.

## Deploy to Cloud Run
- Deploy with `google-github-actions/deploy-cloudrun@v2` in **image mode**: pass `service: ${{ github.event.repository.name }}` (the repo-derived name — see "Service naming" above; never a hardcoded literal), the pushed `image`, and `region: ${{ vars.GCP_REGION }}`. Do NOT deploy from a Knative `service.yaml` (the action's `metadata:` input, equivalent to `gcloud run services replace`) — see the warning below.
- **Give the deploy step an explicit `id: deploy`** so its `outputs.url` (the live Cloud Run URL) is accessible in later steps.
- **PUBLIC ACCESS (REQUIRED for a public web service) — two-part, and the IAM binding is the authoritative one:**
  1. Pass `flags: '--allow-unauthenticated'` to the deploy step.
  2. **AND** add an explicit, idempotent post-deploy step that binds `allUsers` to `roles/run.invoker` (below). This is the *guaranteed* grant — re-applying it every run is harmless.
  WITHOUT a public-invoker grant, Cloud Run rejects every anonymous request with HTTP 403 ("The request was not authenticated. Either allow unauthenticated invocations or set the proper Authorization header."). Only OMIT public access for an explicitly private/internal service (whose callers then need their own `roles/run.invoker` binding).
- **WHY the explicit IAM binding, not just the flag:** a Cloud Run service's public-access policy is **IAM, stored separately from the service spec** — it is NOT part of the Knative manifest. So `flags: '--allow-unauthenticated'` only takes effect in the action's **image deploy** mode; if the workflow instead deploys a `service.yaml` (`metadata:` / `gcloud run services replace`), that flag is incompatible and silently dropped, IAM is reset to the project default (authenticated-only), and the live service returns HTTP 403 even though the manifest set `ingress: all`. The `add-iam-policy-binding` step sets the policy directly and works regardless of deploy mode — that is why it is mandatory.

  Reference implementation — **one explicit step** run after the deploy step:
  ```yaml
        - name: Allow public (unauthenticated) invocation
          env:
            SERVICE: ${{ github.event.repository.name }}
            REGION: ${{ vars.GCP_REGION }}
            PROJECT: ${{ vars.GCP_PROJECT_ID }}
          run: gcloud run services add-iam-policy-binding "$SERVICE" --region="$REGION" --project="$PROJECT" --member="allUsers" --role="roles/run.invoker"
  ```
  **Why the explicit IAM binding?** `add-iam-policy-binding` is the authoritative access-control mechanism — Cloud Run evaluates the IAM policy on every request; `allUsers → roles/run.invoker` is what makes the service publicly reachable. The `google-github-actions/deploy-cloudrun@v2` action's `flags: '--allow-unauthenticated'` runs gcloud with `ignoreReturnCode: true` and `silent: true` — if the flag is silently rejected (e.g. an org policy constraint or transient API error), the IAM binding step runs explicitly, fails loudly, and guarantees the policy is set. Re-applying the binding every run is idempotent and harmless. **FORBIDDEN: `gcloud run services update --allow-unauthenticated`** — this is NOT a valid command (`--allow-unauthenticated` is unrecognized by `services update`, exits 2). Do NOT emit a separate step with this command; the `add-iam-policy-binding` step is the complete and only required grant.

  **Use single-line `run:` form (no `run: |`) for each step individually.** A multi-line block requires `\` line-continuation backslashes on every line but the last; if any backslash is dropped, the shell runs only the first line as the gcloud command and remaining flag lines execute as separate invalid commands — gcloud returns `argument --member --role: Must be specified` (exit 1). The single-line form with `env:` vars is immune to this class of error.
  The service name MUST remain `${{ github.event.repository.name }}` in each step's `env:` block — never hardcode a literal repo name.
- The container listens on `$PORT` (Cloud Run injects it) and binds `0.0.0.0` — that is the archetype skill's Dockerfile/server concern; this deploy step does not set the port.

## Cloud SQL (only for a database-backed CRUD service)
- Attach the instance to the Cloud Run revision via `--add-cloudsql-instances` (or the Cloud SQL Auth Proxy), referencing `${{ secrets.CLOUD_SQL_CONNECTION_NAME }}`.
- If the app has a schema/migrations step, run migrations against the database BEFORE the new revision serves traffic (a migrate step gated on the same WIF auth).

## Post-deploy: publish the live URLs into the README
- **After the deploy step, add two steps: "Extract Cloud Run URLs" then "Update README with deployment URLs".**

### Why two URLs
Cloud Run Gen1 services had a revision-specific URL (`https://<service>-<hash>-<region-code>.a.run.app`) returned by the deploy action's `outputs.url`, while the stable service URL came from `gcloud run services describe`. On **Cloud Run Gen2** (the current default), `outputs.url` and `status.url` now return the **same stable URL** (`https://<service>-<project-number>.<region>.run.app`), so a naïve `URL_REVISION="${{ steps.deploy.outputs.url }}"` produces two identical links in the README. A distinct legacy `*.a.run.app` URL may still be present in the service's `run.googleapis.com/urls` annotation (Gen1 services, migrated services). The extraction step below tries both sources and falls back to the stable URL when no distinct URL is available. Always write both into the README so users with corporate proxies that distrust new hash-subdomains have the stable regional URL.

### Step 1 — Extract Cloud Run URLs
Add a step with `id: urls` immediately after the deploy step:
```yaml
      - name: Extract Cloud Run URLs
        env:
          SERVICE: ${{ github.event.repository.name }}
          REGION: ${{ vars.GCP_REGION }}
          PROJECT: ${{ vars.GCP_PROJECT_ID }}
        run: |
          SVC_JSON=$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format=json)
          URL_STABLE=$(echo "$SVC_JSON" | jq -r '.status.url')
          URL_REVISION="${{ steps.deploy.outputs.url }}"
          # Cloud Run Gen2: outputs.url and status.url are often the same stable URL.
          # Try the run.googleapis.com/urls annotation for a distinct legacy *.a.run.app URL.
          if [ "$URL_STABLE" = "$URL_REVISION" ] || [ -z "$URL_REVISION" ]; then
            URL_REVISION=$(echo "$SVC_JSON" | jq -r \
              --arg stable "$URL_STABLE" \
              '(.metadata.annotations["run.googleapis.com/urls"] // "[]") | fromjson | .[] | select(. != $stable)' \
              2>/dev/null | head -n1)
            URL_REVISION="${URL_REVISION:-$URL_STABLE}"
          fi
          echo "URL_STABLE=$URL_STABLE" >> "$GITHUB_ENV"
          echo "URL_REVISION=$URL_REVISION" >> "$GITHUB_ENV"
```
A single `gcloud run services describe --format=json` call fetches the full service metadata. `status.url` gives the stable regional URL. If `outputs.url` from the deploy action is identical (Cloud Run Gen2 default), the step falls back to the `run.googleapis.com/urls` annotation (a JSON-encoded array of all service URLs), selecting the first URL that differs from the stable one. If no distinct URL exists, both variables hold the stable URL — the README will show two identical links, which is harmless. Both values are exported into `$GITHUB_ENV` so the next step reads them as plain shell variables.

### Step 2 — Update README with deployment URLs
Rules for this step:
1. Replace everything between `<!-- DEPLOYMENT_URL_START -->` and `<!-- DEPLOYMENT_URL_END -->` with a two-line markdown block listing both URLs. If the markers are absent, append a new `## 🚀 Live Deployment` section with the markers and both links.
2. Uses `perl -i -0pe` for in-place multiline replacement (available on all `ubuntu-latest` runners).
3. Commits only when `README.md` actually changed (`git diff --quiet` ⇒ exit early); the commit message MUST end with `[skip ci]` to prevent a re-trigger loop.
4. **Pushes with the `HEAD:<default-branch>` refspec, NEVER a bare `git push`.** `actions/checkout` leaves the workspace in **detached HEAD** (it checks out `github.sha`, not a branch), so a bare `git push` fails with `fatal: You are not currently on a branch`. The refspec form `git push origin HEAD:"$DEFAULT_BRANCH"` pushes the just-made commit straight to the default-branch ref and works from a detached HEAD. Resolve the branch from `${{ github.event.repository.default_branch }}` — never hardcode `main`.
5. **Branch-protection prerequisite (one-time org setup):** a protected default branch rejects this push unless the `github-actions` app is on the branch rule's **"Allow bypass"** list. Grant that bypass once per org/repo — see docs/guides/devops_setup.md.
6. Authenticates via the default `GITHUB_TOKEN` (no extra secret — `contents: write` above covers it).
7. **Author it as a literal `run: |` block — NEVER assemble the script with a `${{ format(...) }}` expression (or any expression-built `run:`).** A `format()` string-literal escapes every single quote by DOUBLING it (`'` → `''`); that doubling survives into the executed bash, so `printf ''\n…''` word-splits the format string and appends a stray `##` line instead of the URL. Interpolate `${{ github.event.repository.default_branch }}` DIRECTLY inside the literal block.

  Reference implementation:
  ```yaml
        - name: Update README with deployment URLs
          run: |
            perl -i -0pe \
              "s|<!-- DEPLOYMENT_URL_START -->.*?<!-- DEPLOYMENT_URL_END -->|<!-- DEPLOYMENT_URL_START -->\n**Stable (corporate-proxy-safe):** [$URL_STABLE]($URL_STABLE)\n**Revision:** [$URL_REVISION]($URL_REVISION)\n<!-- DEPLOYMENT_URL_END -->|s" \
              README.md || true
            if ! grep -q "DEPLOYMENT_URL_START" README.md; then
              printf '\n## 🚀 Live Deployment\n<!-- DEPLOYMENT_URL_START -->\n**Stable (corporate-proxy-safe):** [%s](%s)\n**Revision:** [%s](%s)\n<!-- DEPLOYMENT_URL_END -->\n' \
                "$URL_STABLE" "$URL_STABLE" "$URL_REVISION" "$URL_REVISION" >> README.md
            fi
            # Nothing changed → nothing to push (and no re-trigger loop).
            if git diff --quiet README.md; then
              echo "README deployment URLs already current; nothing to do."
              exit 0
            fi
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add README.md
            git commit -m "docs: update live deployment URLs [skip ci]"
            # HEAD:<default-branch> pushes the detached-HEAD commit straight to the branch ref —
            # avoids "fatal: You are not currently on a branch" from detached HEAD checkout.
            git push origin HEAD:"${{ github.event.repository.default_branch }}"
  ```
