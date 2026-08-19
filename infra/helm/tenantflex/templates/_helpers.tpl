{{- define "tenantflex.fullname" -}}
{{- printf "%s-%s" .Release.Name "tenantflex" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "tenantflex.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}
