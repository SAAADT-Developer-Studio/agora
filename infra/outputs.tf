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

# ECR outputs
output "ecr_repository_url" {
  value       = aws_ecr_repository.vidik_api_repo.repository_url
  description = "The URL of the ECR repository for the API."
}

output "ecr_repository_name" {
  value       = aws_ecr_repository.vidik_api_repo.name
  description = "The name of the ECR repository."
}

output "lambda_function_name" {
  value       = aws_lambda_function.vidik_api.function_name
  description = "The name of the Lambda function."
}

output "lambda_function_arn" {
  value       = aws_lambda_function.vidik_api.arn
  description = "The ARN of the Lambda function."
}

// TODO: connect this public URL to api.vidik.si
output "lambda_function_url" {
  value       = aws_lambda_function_url.vidik_api_url.function_url
  description = "The public URL for the Lambda function."
}
