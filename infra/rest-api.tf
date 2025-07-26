# ECR repository for the API Docker images
resource "aws_ecr_repository" "vidik_api_repo" {
  name                 = "vidik-api"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = "vidik-api"
    Environment = "production"
  }
}

# ECR lifecycle policy to keep only recent images
resource "aws_ecr_lifecycle_policy" "vidik_api_lifecycle" {
  repository = aws_ecr_repository.vidik_api_repo.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v"]
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Delete untagged images older than 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# IAM role for Lambda execution
resource "aws_iam_role" "lambda_execution_role" {
  name = "vidik-api-lambda-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# Attach basic Lambda execution policy
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
  role       = aws_iam_role.lambda_execution_role.name
}

# Lambda function
resource "aws_lambda_function" "vidik_api" {
  function_name = "vidik-api"
  role          = aws_iam_role.lambda_execution_role.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.vidik_api_repo.repository_url}:latest"
  timeout       = 30
  memory_size   = 512

  environment {
    variables = {
      DATABASE_URL = digitalocean_database_cluster.postgres.uri
    }
  }

  tags = {
    Name        = "vidik-api"
    Environment = "production"
  }
}

# Lambda function URL for public access
resource "aws_lambda_function_url" "vidik_api_url" {
  function_name      = aws_lambda_function.vidik_api.function_name
  authorization_type = "NONE"

  cors {
    allow_credentials = false
    allow_headers     = ["date", "keep-alive"]
    allow_methods     = ["*"]
    allow_origins     = ["*"]
    expose_headers    = ["date", "keep-alive"]
    max_age           = 86400
  }
}

# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "vidik_api_logs" {
  name              = "/aws/lambda/vidik-api"
  retention_in_days = 14
}
