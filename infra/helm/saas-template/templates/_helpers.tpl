{{- define "saas-template.fullname" -}}
{{- printf "%s-%s" .Release.Name "saas-template" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "saas-template.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}
