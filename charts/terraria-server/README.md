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

The server reads its settings (password, max players, port, difficulty, ...) from
`serverconfig.txt` on the config volume. The `terraria.*` values are exposed as environment
variables for compatibility but the image does not read them; edit `serverconfig.txt` instead.
The image runs as user `terraria` (uid/gid 999), so `podSecurityContext.fsGroup` defaults to 999.

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
helm upgrade terraria charts/terraria-server -n terraria --set nameOverride=terraria
```

With `nameOverride=terraria` the rendered manifests are identical to the previous chart apart
from the chart labels and the removed `PASSWORD` environment variable (which the image never read).

## Values

| Key | Default | Description |
|-----|---------|-------------|
| `image.repository` | `docker.io/rdvansloten/terraria-server` | Image repository |
| `image.tag` | `"1458"` | Image tag, i.e. Terraria 1.4.5.8. Falls back to `appVersion` |
| `image.pullPolicy` | `Always` | Pull policy |
| `terraria.world` | `Terraria.wld` | World file name inside the world volume |
| `persistence.storageClassName` | `nfs-client` | Default storage class for all PVCs |
| `persistence.size` | `10Gi` | Default size for all PVCs |
| `persistence.{world,config,logs}.*` | | Per-volume overrides for class, access modes, size, selector, volumeName |
| `service.port` | `7777` | Service port |
| `service.type` | `ClusterIP` | `ClusterIP`, `NodePort` or `LoadBalancer` |
| `service.nodePort` | `""` | Fixed node port for `NodePort` |
| `service.loadBalancerIP` | `""` | Static IP for `LoadBalancer` |
| `service.annotations` | `{}` | Service annotations (MetalLB, cloud providers) |
| `ingress.traefik.enabled` | `true` | Create a Traefik `IngressRouteTCP` |
| `ingress.traefik.entryPoint` | `terraria` | Traefik TCP entrypoint name |
| `extraObjects` | `[]` | Additional manifests (objects or strings), templated with `tpl` |
| `resources` | 500m / 2Gi requests, 4Gi limit | Container resources |
| `podSecurityContext` / `securityContext` | non-root, uid 999, no capabilities | Security contexts |
| `nameOverride` | `""` | Set to `terraria` when upgrading the pre-existing release |
