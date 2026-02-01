# Grafana Cloud Alerting Configuration

provider "grafana" {
  url             = var.grafana_url
  auth            = var.grafana_service_account_token
  sm_access_token = var.grafana_sm_access_token
  sm_url          = "https://synthetic-monitoring-api-eu-west-2.grafana.net"
}

# Get available Grafana Synthetic Monitoring probes
data "grafana_synthetic_monitoring_probes" "main" {}

# Slack Contact Point for scraper alerts
resource "grafana_contact_point" "slack_scraper_alerts" {
  name = "vidik-scraper-alerts"

  slack {
    url                     = var.slack_webhook_url
    title                   = "Vidik Scraper Alert"
    text                    = <<-EOT
      {{ if gt (len .Alerts.Firing) 0 }}
      🚨 **FIRING ALERTS** ({{ len .Alerts.Firing }})
      {{ range .Alerts.Firing }}
      ---
      **Alert:** {{ .Labels.alertname }}
      **Severity:** {{ .Labels.severity }}
      **Description:** {{ .Annotations.description }}
      **Time:** {{ .StartsAt.Format "2006-01-02 15:04:05" }}
      {{ end }}
      {{ end }}

      {{ if gt (len .Alerts.Resolved) 0 }}
      ✅ **RESOLVED ALERTS** ({{ len .Alerts.Resolved }})
      {{ range .Alerts.Resolved }}
      ---
      **Alert:** {{ .Labels.alertname }}
      **Time:** {{ .EndsAt.Format "2006-01-02 15:04:05" }}
      {{ end }}
      {{ end }}
    EOT
    recipient               = var.slack_channel
    username                = "Grafana Alerts"
    mention_channel         = "here"
    disable_resolve_message = false
  }
}

# Slack Contact Point for synthetic monitoring alerts
resource "grafana_contact_point" "slack_synthetic_alerts" {
  name = "vidik-synthetic-alerts"

  slack {
    url                     = var.slack_webhook_url
    title                   = "Vidik Site Monitoring"
    text                    = <<-EOT
      {{ if gt (len .Alerts.Firing) 0 }}
      🌐 **SITE DOWN** ({{ len .Alerts.Firing }})
      {{ range .Alerts.Firing }}
      ---
      **Alert:** {{ .Labels.alertname }}
      **Description:** {{ .Annotations.description }}
      **Time:** {{ .StartsAt.Format "2006-01-02 15:04:05" }}
      {{ end }}
      {{ end }}

      {{ if gt (len .Alerts.Resolved) 0 }}
      ✅ **SITE RECOVERED** ({{ len .Alerts.Resolved }})
      {{ range .Alerts.Resolved }}
      ---
      **Alert:** {{ .Labels.alertname }}
      **Time:** {{ .EndsAt.Format "2006-01-02 15:04:05" }}
      {{ end }}
      {{ end }}
    EOT
    recipient               = var.slack_channel
    username                = "Grafana Alerts"
    mention_channel         = "here"
    disable_resolve_message = false
  }
}

# Alert Rule: Scraper Processing Alert
resource "grafana_rule_group" "scraper_alerts" {
  name             = "scraper-processing-alerts"
  folder_uid       = grafana_folder.alerts.uid
  interval_seconds = 60 # Check every minute

  rule {
    name      = "Scraper Processing Stopped"
    condition = "B"

    # Query A: Count log lines with the success message
    data {
      ref_id = "A"

      relative_time_range {
        from = 1200 # 20 minutes in seconds
        to   = 0
      }

      datasource_uid = var.grafana_loki_datasource_uid

      model = jsonencode({
        expr      = "count_over_time({service_name=\"scraper\"} |~ `Successfully processed .* new articles` [20m])"
        queryType = "instant"
        refId     = "A"
        datasource = {
          type = "loki"
          uid  = var.grafana_loki_datasource_uid
        }
      })
    }

    # Query B: Threshold condition - alert if count is 0
    data {
      ref_id = "B"

      relative_time_range {
        from = 1200
        to   = 0
      }

      datasource_uid = "__expr__"

      model = jsonencode({
        conditions = [
          {
            evaluator = {
              params = [1]
              type   = "lt"
            }
            operator = {
              type = "and"
            }
            query = {
              params = ["B"]
            }
            reducer = {
              params = []
              type   = "last"
            }
            type = "query"
          }
        ]
        datasource = {
          type = "__expr__"
          uid  = "__expr__"
        }
        expression = "A"
        refId      = "B"
        type       = "threshold"
      })
    }

    no_data_state  = "Alerting" # Alert if no data is returned
    exec_err_state = "Alerting" # Alert on query execution errors

    for = "5m" # Alert must be active for 5 minutes before firing

    annotations = {
      description = "The scraper has not successfully processed any articles in the last 20 minutes. Last successful log message: 'Successfully processed X new articles in Y seconds!'"
      summary     = "Scraper processing stopped"
    }

    labels = {
      severity = "critical"
      team     = "backend"
      service  = "scraper"
    }
  }
}

# Create a folder for alerts
resource "grafana_folder" "alerts" {
  title = "Scraper Alerts"
  uid   = "scraper-alerts"
}

# Notification Policy - Route all alerts to Slack
resource "grafana_notification_policy" "scraper_policy" {
  group_by        = ["alertname", "service"]
  contact_point   = grafana_contact_point.slack_scraper_alerts.name
  group_wait      = "30s"
  group_interval  = "5m"
  repeat_interval = "4h"

  policy {
    matcher {
      label = "service"
      match = "="
      value = "scraper"
    }
    contact_point = grafana_contact_point.slack_scraper_alerts.name
    group_by      = ["alertname"]
    continue      = false
  }

  policy {
    matcher {
      label = "namespace"
      match = "="
      value = "synthetic_monitoring"
    }
    contact_point = grafana_contact_point.slack_synthetic_alerts.name
    group_by      = ["alertname"]
    continue      = false
  }
}

# Synthetic Monitoring Check for vidik.si
resource "grafana_synthetic_monitoring_check" "vidik_http_check" {
  job       = "vidik-si-multihttp-check"
  target    = "https://vidik.si"
  enabled   = true
  frequency = 300000 # Check every 5 minutes
  timeout   = 5000

  labels = {
    service = "synthetic-monitoring"
  }

  settings {
    multihttp {
      dynamic "entries" {
        for_each = [
          "https://vidik.si",
          "https://vidik.si/politika",
          "https://vidik.si/gospodarstvo",
          "https://vidik.si/mediji",
          "https://vidik.si/medij/rtv",
        ]
        content {
          request {
            method = "GET"
            url    = entries.value
          }
          assertions {
            type      = "TEXT"
            subject   = "HTTP_STATUS_CODE"
            condition = "EQUALS"
            value     = "200"
          }
        }
      }
    }
  }

  probes = [
    data.grafana_synthetic_monitoring_probes.main.probes.Frankfurt,
    data.grafana_synthetic_monitoring_probes.main.probes.Paris,
    data.grafana_synthetic_monitoring_probes.main.probes.Zurich,
  ]
}


# lint error here for some fucking reason, but it works
resource "grafana_synthetic_monitoring_check_alerts" "vidik_alerts" {
  check_id = grafana_synthetic_monitoring_check.vidik_http_check.id
  alerts = [
    {
      name        = "ProbeFailedExecutionsTooHigh"
      threshold   = 2
      period      = "15m"
      runbook_url = ""
    }
  ]
}
