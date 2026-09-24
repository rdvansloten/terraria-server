// Self-hosted (global) Renovate configuration, used by .github/workflows/renovate.yaml.
// Repository rules live in renovate.json. This file only wires credentials and identity
// from the environment so no secrets end up in the repository.
module.exports = {
  // Platform and repositories come from the workflow environment (RENOVATE_REPOSITORIES).
  onboarding: false,
  requireConfig: "required",

  // Identity of the GitHub App the workflow runs as; both come from the token step.
  username: process.env.RENOVATE_USERNAME,
  gitAuthor: process.env.RENOVATE_GIT_AUTHOR,

  // Authenticated Docker Hub lookups avoid the anonymous rate limit for digest pinning.
  // Only added when credentials are present so local dry runs without them stay warning-free.
  hostRules:
    process.env.RENOVATE_DOCKERHUB_USERNAME && process.env.RENOVATE_DOCKERHUB_TOKEN
      ? [
          {
            hostType: "docker",
            matchHost: "docker.io",
            username: process.env.RENOVATE_DOCKERHUB_USERNAME,
            password: process.env.RENOVATE_DOCKERHUB_TOKEN,
          },
        ]
      : [],

  printConfig: false,
};
