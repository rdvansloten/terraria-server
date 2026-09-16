{{/*
Expand the name of the chart.
*/}}
{{- define "terraria-server.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "terraria-server.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "terraria-server.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "terraria-server.labels" -}}
helm.sh/chart: {{ include "terraria-server.chart" . }}
{{ include "terraria-server.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "terraria-server.selectorLabels" -}}
app.kubernetes.io/name: {{ include "terraria-server.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Config files provided through values, as filename -> content. Empty when nothing is set.
*/}}
{{- define "terraria-server.configFiles" -}}
{{- $files := dict -}}
{{- with .Values.terraria.config }}{{ $_ := set $files "serverconfig.txt" . }}{{ end -}}
{{- with .Values.tshock.config }}{{ $_ := set $files "config.json" . }}{{ end -}}
{{- with .Values.tshock.sscConfig }}{{ $_ := set $files "sscconfig.json" . }}{{ end -}}
{{- toYaml $files -}}
{{- end }}

{{/*
Name of the Secret holding the join password.
*/}}
{{- define "terraria-server.passwordSecretName" -}}
{{- .Values.terraria.password.existingSecret | default (printf "%s-password" (include "terraria-server.fullname" .)) -}}
{{- end }}

{{/*
The join password: explicit value, else the one already stored in the cluster (so upgrades and
manual edits of the Secret keep it), else a freshly generated one. The generated value is cached
on .Values so every template in this render sees the same password.
*/}}
{{- define "terraria-server.password" -}}
{{- $pw := .Values.terraria.password.value -}}
{{- if not $pw -}}
  {{- $existing := lookup "v1" "Secret" .Release.Namespace (include "terraria-server.passwordSecretName" .) -}}
  {{- if and $existing $existing.data (hasKey $existing.data "password") -}}
    {{- $pw = index $existing.data "password" | b64dec -}}
  {{- else if hasKey .Values.terraria.password "_generated" -}}
    {{- $pw = .Values.terraria.password._generated -}}
  {{- else -}}
    {{- $pw = randAlphaNum 20 -}}
    {{- $_ := set .Values.terraria.password "_generated" $pw -}}
  {{- end -}}
{{- end -}}
{{- $pw -}}
{{- end }}
