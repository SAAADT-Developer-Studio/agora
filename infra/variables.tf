variable "hcloud_token" {
  description = "Hetzner Cloud API Token"
  type        = string
  sensitive   = true # Mark as sensitive to prevent logging
}

variable "digitalocean_token" {
  description = "DigitalOcean API Token"
  type        = string
  sensitive   = true # Mark as sensitive to prevent logging
}


variable "cf_account_id" {
  type        = string
  description = "Cloudflare Account ID"
}

variable "cf_zone_id" {
  type        = string
  description = "Cloudflare Zone ID"
}

variable "cf_email" {
  type        = string
  description = "Cloudflare Email"
}

variable "cf_api_token" {
  type        = string
  description = "Cloudflare API Key"
  sensitive   = true # Mark as sensitive to prevent logging
}

variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "eu-central-1"
}

# Grafana Cloud Variables
variable "grafana_url" {
  type        = string
  description = "Grafana Cloud instance URL (e.g., https://your-org.grafana.net)"
}

variable "grafana_service_account_token" {
  type        = string
  description = "Grafana Cloud Service Account Token for Terraform"
  sensitive   = true
}

variable "grafana_loki_datasource_uid" {
  type        = string
  description = "UID of the Loki datasource in Grafana Cloud"
}

variable "grafana_sm_access_token" {
  type        = string
  description = "Grafana Cloud Synthetic Monitoring access token"
  sensitive   = true
}

# Slack Variables
variable "slack_webhook_url" {
  type        = string
  description = "Slack webhook URL for sending alerts"
  sensitive   = true
}

variable "slack_channel" {
  type        = string
  description = "Slack channel to send alerts to (e.g., #alerts)"
  default     = "#vidik-alerts"
}
