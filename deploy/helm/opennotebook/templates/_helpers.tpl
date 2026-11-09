{{- define "on.name" -}}opennotebook{{- end -}}

{{- define "on.fullname" -}}
{{- if contains "opennotebook" .Release.Name -}}{{ .Release.Name | trunc 50 | trimSuffix "-" }}
{{- else -}}{{ printf "%s-opennotebook" .Release.Name | trunc 50 | trimSuffix "-" }}{{- end -}}
{{- end -}}

{{- define "on.labels" -}}
app.kubernetes.io/name: {{ include "on.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* selector labels of one component: include "on.selector" (list . "api") */}}
{{- define "on.selector" -}}
app.kubernetes.io/name: {{ include "on.name" (index . 0) }}
app.kubernetes.io/instance: {{ (index . 0).Release.Name }}
app.kubernetes.io/component: {{ index . 1 }}
{{- end -}}

{{- define "on.image" -}}
{{- $root := index . 0 -}}
{{ printf "%s/opennotebook-%s:%s" $root.Values.image.registry (index . 1) (default $root.Chart.AppVersion $root.Values.image.tag) }}
{{- end -}}

{{- define "on.secretName" -}}
{{- default (printf "%s-secrets" (include "on.fullname" .)) .Values.existingSecret -}}
{{- end -}}

{{- define "on.host" -}}{{ printf "%s-%s" (include "on.fullname" (index . 0)) (index . 1) }}{{- end -}}

{{/* hardened container security context of the OpenNotebook images (non-root, read-only root FS) */}}
{{- define "on.containerSecurity" -}}
runAsNonRoot: true
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end -}}

{{- define "on.podCommon" -}}
automountServiceAccountToken: false
{{- with .Values.imagePullSecrets }}
imagePullSecrets: {{- toYaml . | nindent 2 }}
{{- end }}
securityContext: {{- toYaml .Values.podSecurityContext | nindent 2 }}
{{- with .Values.nodeSelector }}
nodeSelector: {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations: {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.affinity }}
affinity: {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{/* environment of the api, worker and migration job */}}
{{- define "on.appEnv" -}}
envFrom:
  - configMapRef:
      name: {{ include "on.fullname" . }}-config
  - secretRef:
      name: {{ include "on.secretName" . }}
{{- end -}}
