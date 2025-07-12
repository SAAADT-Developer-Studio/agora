output "server_ip_address" {
  value       = hcloud_server.scraper_server.ipv4_address
  description = "The public IPv4 address of the scraper server."
}

output "database_host" {
  value       = digitalocean_database_cluster.postgres.host
  description = "The host address of the PostgreSQL database cluster."
}

output "database_port" {
  value       = digitalocean_database_cluster.postgres.port
  description = "The port of the PostgreSQL database cluster."
}

output "database_name" {
  value       = digitalocean_database_db.scraper_db.name
  description = "The name of the scraper database."
}

output "database_user" {
  value       = digitalocean_database_user.scraper_user.name
  description = "The username for the database user."
}

output "database_password" {
  value       = digitalocean_database_user.scraper_user.password
  description = "The password for the database user."
  sensitive   = true
}

output "database_uri" {
  value       = digitalocean_database_cluster.postgres.uri
  description = "The full connection URI for the PostgreSQL database."
  sensitive   = true
}
