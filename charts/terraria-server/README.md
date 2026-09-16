# terraria-server

Helm chart for a Terraria dedicated server running the
[`rdvansloten/terraria-server`](https://hub.docker.com/r/rdvansloten/terraria-server) image.

It creates a single-replica `Deployment` (strategy `Recreate`), a `ClusterIP` `Service`,
three `PersistentVolumeClaim`s (world, config, logs) and, optionally, a Traefik `IngressRouteTCP`.
Any other objects you need (for example for a different ingress controller) go in `extraObjects`.

## Paths

| Purpose | Mount path in container | PVC |
|---------|-------------------------|-----|
| World files | `/terraria/.local/share/Terraria/Worlds` | `<fullname>-world` |
| `serverconfig.txt` | `/terraria/config` | `<fullname>-config` |
| Server logs | `/terraria/logs` | `<fullname>-logs` |

Gameplay settings (password, max players, port, ...) come from `serverconfig.txt` on the config
volume, or `config.json` for TShock. The image runs as user `terraria` (uid/gid 999), so
`podSecurityContext.fsGroup` defaults to 999.

## Join password

The chart manages the join password as a Kubernetes Secret and hands it to the server as
`TERRARIA_PASSWORD`, which overrides `password=` in `serverconfig.txt`. On first install a random
password is generated and printed once in the install notes. Upgrades keep whatever the Secret
contains, so you can change it at any time:

```bash
kubectl -n terraria create secret generic terraria-password \
  --from-literal=password='new password' --dry-run=client -o yaml | kubectl apply -f -
kubectl -n terraria rollout restart deploy/terraria
```

Set `terraria.password.value` to choose the password through values, `terraria.password.existingSecret`
to bring your own Secret (key `password`), or `terraria.password.enabled: false` to manage the
password in the config file only.

How it reaches the server differs per flavor. Vanilla reads a private copy of `serverconfig.txt`
with the password applied, kept on tmpfs, so the config volume never contains it. TShock only
honors `ServerPassword` in its own `config.json`, so there the entrypoint writes it into that file
on the config volume at every start, which is where TShock stores it anyway.

## Worlds

By default a medium world named after `terraria.world` is generated on first start, driven by
`autocreate=2` in the default `serverconfig.txt` (with `seed=` and `difficulty=` alongside it;
set them through `terraria.config`). To bring your own `.wld` instead, install with
`terraria.waitForWorld: true`: the pod waits, the install notes print the exact `kubectl cp`
command, and the server starts once the copy is complete. The world then lives on the persistent
volume, so `waitForWorld` can stay on.

## Exposing the server

Terraria uses raw TCP on port 7777, so a regular HTTP `Ingress` resource cannot route it.
Pick one of:

| Method | Values | Notes |
|--------|--------|-------|
| LoadBalancer | `service.type: LoadBalancer` | Cloud or MetalLB assigns an external IP. `service.loadBalancerIP` and `service.annotations` for provider specifics |
| NodePort | `service.type: NodePort`, `service.nodePort: 30777` | Reachable on every node at that port. Leave `nodePort` empty for a random one |
| Traefik | `ingress.traefik.enabled: true` | Creates an `IngressRouteTCP` on entrypoint `ingress.traefik.entryPoint`. Traefik must define that TCP entrypoint |
| Anything else | `extraObjects` | A list of extra manifests rendered by the chart, with `{{ }}` templating |

Example: ingress-nginx TCP passthrough via `extraObjects` (the controller needs
`--tcp-services-configmap=ingress-nginx/tcp-services` and the port on its Service):

```yaml
ingress:
  traefik:
    enabled: false
extraObjects:
  - apiVersion: v1
    kind: ConfigMap
    metadata:
      name: tcp-services
      namespace: ingress-nginx
    data:
      "7777": "{{ .Release.Namespace }}/{{ include \"terraria-server.fullname\" . }}:7777"
```

## Server configuration

Set `terraria.config` to the contents of `serverconfig.txt`, or for the TShock image
`tshock.config` (`config.json`) and `tshock.sscConfig` (`sscconfig.json`):

```yaml
terraria:
  config: |
    maxplayers=8
    port=7777
    password=changeme
    motd=Welcome to Terraria!
```

The files are stored in a ConfigMap and copied onto the config volume by an init container on
every start, so they stay writable for the server and your values win over edits made on the
volume. Changing them triggers a rollout. When left empty, nothing on the volume is touched,
except that the image's default `serverconfig.txt` is seeded once if the volume has none.

## Install

```bash
helm install terraria charts/terraria-server -n terraria --create-namespace
```

## Upgrading an existing `terraria` release

This chart was extracted from a chart named `terraria`. The chart name feeds both the resource
names and the immutable Deployment selector label `app.kubernetes.io/name`, so upgrading the
existing release with the defaults would fail on the selector and create new, empty PVCs.
Pin the name instead:

```bash
helm upgrade terraria charts/terraria-server -n terraria \
  --set nameOverride=terraria --set ingress.traefik.enabled=true \
  --set terraria.password.value='<the password currently in serverconfig.txt>'
```

The previous chart always created the Traefik `IngressRouteTCP`; it is now opt-in, hence the
second flag. The chart now also manages the join password and would otherwise generate a new
one, overriding the password on the volume, so pass the current one once (or set
`terraria.password.enabled=false`). With both set the rendered manifests match the previous chart apart from the chart
labels, the removed unused `PASSWORD`, `MAXPLAYERS` and `PORT` environment variables, and the
new config init container.

## Values

| Key | Default | Description |
|-----|---------|-------------|
| `image.repository` | `docker.io/rdvansloten/terraria-server` | Image repository |
| `image.tag` | `"1458"` | Image tag. Vanilla by default; use `<version>-tshock` (see the commented example in values.yaml) for TShock. Both are kept current by Renovate |
| `image.pullPolicy` | `Always` | Pull policy |
| `terraria.world` | `Terraria.wld` | World file name inside the world volume |
| `terraria.waitForWorld` | `false` | Wait for a world file to be copied in instead of generating one |
| `terraria.password.enabled` | `true` | Manage the join password as a Secret, passed as `TERRARIA_PASSWORD` |
| `terraria.password.value` | `""` | Explicit password; empty generates one on first install and keeps it afterwards |
| `terraria.password.existingSecret` | `""` | Use an existing Secret with key `password` |
| `terraria.config` | `""` | Contents of `serverconfig.txt` (password, players, motd, autocreate, seed, ...), written to the config volume on every start |
| `tshock.config`, `tshock.sscConfig` | `""` | Contents of TShock's `config.json` / `sscconfig.json` |
| `persistence.storageClassName` | `nfs-client` | Default storage class for all PVCs |
| `persistence.size` | `10Gi` | Default size for all PVCs |
| `persistence.{world,config,logs}.enabled` | `true` | Disabling falls back to `emptyDir`: data is lost on every pod restart, and the install notes warn about it |
| `persistence.{world,config,logs}.*` | | Per-volume overrides for class, access modes, size, selector, volumeName |
| `service.port` | `7777` | Service port |
| `service.type` | `ClusterIP` | `ClusterIP`, `NodePort` or `LoadBalancer` |
| `service.nodePort` | `""` | Fixed node port for `NodePort` |
| `service.loadBalancerIP` | `""` | Static IP for `LoadBalancer` |
| `service.annotations` | `{}` | Service annotations (MetalLB, cloud providers) |
| `ingress.traefik.enabled` | `false` | Create a Traefik `IngressRouteTCP` |
| `ingress.traefik.entryPoint` | `terraria` | Traefik TCP entrypoint name |
| `extraObjects` | `[]` | Additional manifests (objects or strings), templated with `tpl` |
| `resources` | 500m / 2Gi requests, 4Gi limit | Container resources |
| `podSecurityContext` / `securityContext` | non-root uid 999, no capabilities, read-only root filesystem | Security contexts. The image supports a read-only root; `/tmp` and `/terraria/.local/share/Terraria` are tmpfs/emptyDir |
| `nameOverride` | `""` | Set to `terraria` when upgrading the pre-existing release |
