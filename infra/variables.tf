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
