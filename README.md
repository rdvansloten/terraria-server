# terraria-server
Terraria server Docker image and Helm chart for vanilla and TShock

Images are published to [`docker.io/rdvansloten/terraria-server`](https://hub.docker.com/r/rdvansloten/terraria-server)
for `linux/amd64`, `linux/arm64` and `linux/arm/v7`.

| Flavor | Directory | Tags | Notes |
|--------|-----------|------|-------|
| Vanilla | [`images/vanilla/`](images/vanilla) | `1458`, `1.4.5.8`, `latest` | Official dedicated server from terraria.org. Version bumps arrive as Renovate PRs |
| TShock | [`images/tshock/`](images/tshock) | `tshock-6.1.0`, `tshock-latest` | [TShock](https://github.com/Pryaxis/TShock) server on .NET 9. Version bumps come in through Renovate |

Both images run as user `terraria` (uid/gid 999) with data under `/terraria`:

| Path | Purpose |
|------|---------|
| `/terraria/.local/share/Terraria/Worlds` | World files. Mount a volume here; `WORLD_FILENAME` selects the world (default `Terraria.wld`) |
| `/terraria/config` | `serverconfig.txt` (vanilla) or TShock's `config.json`, `sscconfig.json` and `tshock.sqlite` |
| `/terraria/logs` | Server logs |
| `/terraria/plugins` | Extra TShock plugins (TShock only) |

Set `TEST_MODE=true` to auto-create a world when none is mounted, which is what the tests do.

## Quick start

```bash
docker run -d -p 7777:7777 \
  -v $HOME/terraria/worlds:/terraria/.local/share/Terraria/Worlds \
  -v $HOME/terraria/config:/terraria/config \
  -e WORLD_FILENAME=MyWorld.wld \
  rdvansloten/terraria-server:latest
```

The container exits with an explanation if the world file does not exist. Create one first by
adding `-autocreate 2 -worldname MyWorld` (1 = small, 2 = medium, 3 = large) to the command.

## Helm chart

[`charts/terraria-server`](charts/terraria-server) deploys either image with persistent
world, config and log volumes, and exposes the TCP port through a `LoadBalancer` Service,
a Traefik `IngressRouteTCP` or ingress-nginx's `tcp-services` ConfigMap. See its README.

## Development

Tooling is managed with [mise](https://mise.jdx.dev) and [Task](https://taskfile.dev):

```bash
mise install          # python, task, uv and a project virtualenv
task --list

task build:vanilla    # build an image for the local platform
task test:tshock      # build and run the pytest suite against the image
task test             # both flavors
PLATFORM=linux/amd64 task test:vanilla   # emulated platform
task test:vanilla -- -k protocol         # pass arguments to pytest
```

The tests in [`tests/`](tests) are image-agnostic: they start the container in `TEST_MODE`,
wait until it listens, then check the Terraria protocol handshake, the non-root user, file
ownership, world creation and clean logs. The same suite runs in CI for all three platforms.

## Automation

- `build-vanilla.yaml` and `build-tshock.yaml` build every platform once into a registry on the runner,
  test each platform from it, and push the tested manifest to Docker Hub only on `main`.
- `renovate.yaml` runs self-hosted Renovate daily from the official image, authenticated as a
  GitHub App so its pull requests trigger the build workflows. It opens PRs for new Terraria server
  releases (via terraria.org's release list), TShock releases, base image digests and GitHub Actions
  digests. Merging publishes the image. Repository rules are in `renovate.json`, credentials and
  identity in `.github/renovate.config.js`.

Required repository settings:

| Name | Kind | Used by |
|------|------|---------|
| `DOCKER_USERNAME`, `DOCKER_PASSWORD` | secrets | Pushing images, authenticated Docker Hub lookups in Renovate |
| `RENOVATE_APP_ID` | variable | Client id of a GitHub App installed on the repo with Contents, Pull requests and Workflows read/write |
| `RENOVATE_APP_PRIVATE_KEY` | secret | Private key of that app |

## License

GPL-2.0, see [LICENSE](LICENSE). Derived from [ryansheehan/terraria](https://github.com/ryansheehan/terraria) (MIT), see [NOTICE](NOTICE).
