provider "aws" {
  region = var.aws_region
}

resource "aws_ecs_cluster" "main" {
  name = var.cluster_name
}

// TODO: maybe use localstack to configure dynamo tables the same as in prod
