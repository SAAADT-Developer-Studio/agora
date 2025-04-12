variable "aws_region" {
  default = "eu-central-1"
}

variable "cluster_name" {
  default = "scraper-cluster"
}

variable "container_image" {
  description = "Docker image for the scraper task"
}

variable "subnet_ids" {
  type = list(string)
}
