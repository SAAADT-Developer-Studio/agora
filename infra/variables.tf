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
