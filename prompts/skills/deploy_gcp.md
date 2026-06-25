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

  Reference implementation for the binding step (runs after the deploy step):
  ```yaml
        - name: Allow public (unauthenticated) invocation
          run: |
            gcloud run services add-iam-policy-binding ${{ github.event.repository.name }} \
              --region="${{ vars.GCP_REGION }}" \
              --project="${{ vars.GCP_PROJECT_ID }}" \
              --member="allUsers" \
              --role="roles/run.invoker"
  ```
- The container listens on `$PORT` (Cloud Run injects it) and binds `0.0.0.0` — that is the archetype skill's Dockerfile/server concern; this deploy step does not set the port.

## Cloud SQL (only for a database-backed CRUD service)
- Attach the instance to the Cloud Run revision via `--add-cloudsql-instances` (or the Cloud SQL Auth Proxy), referencing `${{ secrets.CLOUD_SQL_CONNECTION_NAME }}`.
- If the app has a schema/migrations step, run migrations against the database BEFORE the new revision serves traffic (a migrate step gated on the same WIF auth).

## Post-deploy: publish the live URL into the README
- **After the deploy step, add an "Update README with deployment URL" step** that:
  1. Reads the URL from `${{ steps.deploy.outputs.url }}`.
  2. If `README.md` already contains the marker `<!-- DEPLOYMENT_URL_START -->`, replaces everything between `<!-- DEPLOYMENT_URL_START -->` and `<!-- DEPLOYMENT_URL_END -->` with a markdown link to the live URL. If the markers are absent, appends a new `## 🚀 Live Deployment` section with the markers and the link.
  3. Uses `perl -i -0pe` for the in-place multiline replacement (available on all ubuntu-latest runners).
  4. Commits only when `README.md` actually changed (`git diff --quiet` ⇒ exit early), and the commit message MUST end with `[skip ci]` to prevent a re-trigger loop.
  5. **Pushes with the `HEAD:<default-branch>` refspec, NEVER a bare `git push`.** `actions/checkout` leaves the workspace in **detached HEAD** (it checks out `github.sha`, not a branch), so a bare `git push` fails with `fatal: You are not currently on a branch`. The refspec form `git push origin HEAD:"$DEFAULT_BRANCH"` pushes the just-made commit straight to the default-branch ref and works from a detached HEAD. Resolve the branch from `${{ github.event.repository.default_branch }}` — never hardcode `main`.
  6. **Branch-protection prerequisite (one-time org setup):** a protected default branch rejects this push unless the `github-actions` app is on the branch rule's **"Allow bypass"** list. Grant that bypass once per org/repo — see docs/guides/devops_setup.md. (The push is best-effort: if the default branch advanced since checkout, the non-fast-forward push is skipped and the next deploy re-applies the URL.)
  7. Authenticates via the default `GITHUB_TOKEN` (no extra secret — `contents: write` above covers it).

  Reference implementation for the step:
  ```yaml
        - name: Update README with deployment URL
          run: |
            LIVE_URL="${{ steps.deploy.outputs.url }}"
            perl -i -0pe \
              "s|<!-- DEPLOYMENT_URL_START -->.*?<!-- DEPLOYMENT_URL_END -->|<!-- DEPLOYMENT_URL_START -->\n**Live:** [$LIVE_URL]($LIVE_URL)\n<!-- DEPLOYMENT_URL_END -->|s" \
              README.md || true
            if ! grep -q "DEPLOYMENT_URL_START" README.md; then
              printf '\n## 🚀 Live Deployment\n<!-- DEPLOYMENT_URL_START -->\n**Live:** [%s](%s)\n<!-- DEPLOYMENT_URL_END -->\n' \
                "$LIVE_URL" "$LIVE_URL" >> README.md
            fi
            # Nothing changed → nothing to push (and no re-trigger loop).
            if git diff --quiet README.md; then
              echo "README deployment URL already current; nothing to do."
              exit 0
            fi
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add README.md
            git commit -m "docs: update live deployment URL [skip ci]"
            # HEAD:<default-branch> pushes the detached-HEAD commit straight to the branch ref —
            # this is what avoids "fatal: You are not currently on a branch". Requires the
            # github-actions app to have an "Allow bypass" on the protected default branch.
            git push origin HEAD:"${{ github.event.repository.default_branch }}"
  ```
