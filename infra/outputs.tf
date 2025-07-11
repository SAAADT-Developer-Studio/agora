output "server_ip_address" {
  value       = hcloud_server.scraper_server.ipv4_address
  description = "The public IPv4 address of the scraper server."
}
