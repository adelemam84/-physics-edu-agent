# Vercel release policy

Automatic Git deployments are intentionally disabled for this project.

## Why

The project is developed through many small, CI-tested pull requests. Vercel Hobby counts
preview/canceled builds toward deployment quotas, so deploying every branch/commit exhausted
the daily deployment allowance and blocked production releases.

## Release contract

1. GitHub CI is the required code-quality gate.
2. Pull requests and intermediate commits do not create Vercel deployments.
3. Production is deployed only after a coherent technical batch is complete.
4. A release must target the current `main` commit.
5. After deployment, verify:
   - `/health`
   - `/health/ready`
   - production runtime errors/logs
   - deployment provenance / commit SHA
6. Roll back to the previous READY production deployment if the post-deploy checks fail.

Do not replace this policy with an Ignored Build Step. Vercel counts canceled ignored builds
toward deployment quotas, so that does not solve the deployment-exhaustion problem.
