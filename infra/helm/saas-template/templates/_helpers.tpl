{{- define "saas-template.name" -}}
{{- .Values.nameOverride | default .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "saas-template.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "saas-template.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "saas-template.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}
