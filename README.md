# terraria-server

Terraria server Docker image and Helm chart for vanilla and TShock

Images are published to [`docker.io/rdvansloten/terraria-server`](https://hub.docker.com/r/rdvansloten/terraria-server)
for `linux/amd64`, `linux/arm64` and `linux/arm/v7`.

| Flavor  | Directory                           | Tags                            | Notes                                                         |
| ------- | ----------------------------------- | ------------------------------- | ------------------------------------------------------------- |
| Vanilla | [`images/vanilla/`](images/vanilla) | `latest`, `vanilla`, `1458`, `1.4.5.8`, `1458-vanilla`, `1.4.5.8-vanilla` | Official dedicated server from terraria.org. The default flavor: unsuffixed tags are vanilla |
| TShock  | [`images/tshock/`](images/tshock)   | `tshock`, `6.1.0-tshock`, `1456-tshock`, `1.4.5.6-tshock`                  | [TShock](https://github.com/Pryaxis/TShock) server on .NET 9. `<terraria version>-tshock` is the Terraria version that TShock release targets |

Both images run as user `terraria` (uid/gid 999) with data under `/terraria`:

| Path                                     | Purpose                                                                                       |
| ---------------------------------------- | --------------------------------------------------------------------------------------------- |
| `/terraria/.local/share/Terraria/Worlds` | World files. Mount a volume here; `WORLD_FILENAME` selects the world (default `Terraria.wld`) |
| `/terraria/config`                       | `serverconfig.txt` (vanilla) or TShock's `config.json`, `sscconfig.json` and `tshock.sqlite`  |
| `/terraria/logs`                         | Server logs                                                                                   |
| `/terraria/plugins`                      | Extra TShock plugins (TShock only)                                                            |

When the world file does not exist yet, the server follows `autocreate=` in `serverconfig.txt`
(the default config generates a medium world; `seed=`, `difficulty=` and `worldname=` apply to
it). Remove `autocreate=` to make a missing world an error instead. A few environment variables
adjust this without editing the config:

| Variable                          | Effect                                                                                                                                         |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `AUTOCREATE`, `SEED`, `DIFFICULTY` | Override the same settings from `serverconfig.txt`                                                                                            |
| `WAIT_FOR_WORLD`                  | Wait until a world file is copied in (`kubectl cp`, or `docker exec -i <c> sh -c 'cat > <path>' < my.wld`), then start. Wins over autocreate   |
| `TEST_MODE`                       | Small world with a random seed, used by the tests                                                                                              |
| `TERRARIA_PASSWORD`               | Join password. Vanilla applies it via a private config copy on tmpfs; TShock writes it to `ServerPassword` in `config.json` (the only place it honors) |

An existing world is never overwritten.

## Quick start

```bash
docker run -d -p 7777:7777 \
  -v $HOME/terraria/worlds:/terraria/.local/share/Terraria/Worlds \
  -v $HOME/terraria/config:/terraria/config \
  -e WORLD_FILENAME=MyWorld.wld \
  rdvansloten/terraria-server:latest
```

`MyWorld.wld` is generated on first start (a medium world, per the default config); mount a
folder that already contains it to use an existing world. For TShock use the
`tshock` tag; everything else is the same.

### Hardened run

Both images run with a read-only root filesystem, no capabilities and no privilege escalation,
which is also the Helm chart's default. The server only writes to the volumes and to two tmpfs
mounts:

```bash
docker run -d -p 7777:7777 --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:uid=999,gid=999,mode=1777 \
  --tmpfs /terraria/.local/share/Terraria:uid=999,gid=999 \
  -v $HOME/terraria/worlds:/terraria/.local/share/Terraria/Worlds \
  -v $HOME/terraria/config:/terraria/config \
  -v $HOME/terraria/logs:/terraria/logs \
  -e WORLD_FILENAME=MyWorld.wld \
  rdvansloten/terraria-server:latest
```

## Configuration

Both flavors keep their settings in the folder mounted at `/terraria/config`, and fill it on
first start, so the flow is the same: start once, edit the files on the host, restart.

| Flavor  | File                | Created on first start | Common settings                                                        |
| ------- | ------------------- | ---------------------- | ---------------------------------------------------------------------- |
| Vanilla | `serverconfig.txt`  | seeded from the image  | `password`, `maxplayers`, `motd`, `port`, `secure`, `language`         |
| TShock  | `config.json`       | generated by TShock    | `ServerPassword`, `MaxSlots`, `ServerPort`, `RestApiEnabled`, and more |
| TShock  | `serverconfig.txt`  | seeded from the image  | World generation only: `autocreate`, `difficulty`, `seed`, `worldname` |
| TShock  | `sscconfig.json`    | generated by TShock    | Server-side characters                                                 |

The server reads its config at startup only, so `docker restart <container>` applies changes.
Files that already exist are never overwritten. On Linux hosts the mounted folder must be
writable by uid 999 (`chown 999 <folder>`), otherwise the seed step is skipped with a warning
and the server runs on built-in defaults.
TShock also stores its database (`tshock.sqlite`: accounts, groups, bans) in this folder, which is
why it must be a persistent volume. The Helm chart exposes the same files as `terraria.config`,
`tshock.config` and `tshock.sscConfig`.

## Logging

Both servers write everything to stdout, so `docker logs` and any Kubernetes log collector
(Promtail, Alloy, an OpenTelemetry collector) pick it up without extra configuration. Vanilla
writes nothing to `/terraria/logs` except crash dumps. TShock additionally keeps a timestamped copy
of the same lines there, plus the API layer's `ServerLog.txt` with startup details, so the logs
volume is a persisted archive rather than the primary source. World generation on first start is
noisy: expect a few tens of thousands of progress lines.

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
  test each platform from it, and push the tested manifest to Docker Hub only on `main`. Before the
  push they also stand up a single-node kind cluster, install the Helm chart on a throwaway copy of
  the image, and run `tests/test_chart.py`, which waits for the pod and drives the Terraria handshake
  through a port-forward, so a broken chart or a server that will not serve in-cluster fails the run.
- `renovate.yaml` runs self-hosted Renovate daily from the official image, authenticated as a
  GitHub App so its pull requests trigger the build workflows. It opens PRs for new Terraria server
  releases (via terraria.org's release list), TShock releases, base image digests and GitHub Actions
  digests, and maintains a Dependency Dashboard issue listing pending and errored updates. Merging a
  PR publishes the image. Repository rules are in `renovate.json`, credentials and identity in
  `.github/renovate.config.js`.

Required repository settings:

| Name                                 | Kind     | Used by                                                                                               |
| ------------------------------------ | -------- | ----------------------------------------------------------------------------------------------------- |
| `DOCKER_USERNAME`, `DOCKER_PASSWORD` | secrets  | Pushing images, authenticated Docker Hub lookups in Renovate                                          |
| `RENOVATE_APP_ID`                    | variable | Client id of a GitHub App installed on the repo with Contents, Pull requests, Workflows and Issues read/write |
| `RENOVATE_APP_PRIVATE_KEY`           | secret   | Private key of that app                                                                               |

## License

GPL-2.0, see [LICENSE](LICENSE). Derived from [ryansheehan/terraria](https://github.com/ryansheehan/terraria) (MIT), see [NOTICE](NOTICE).
