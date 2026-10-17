# State lives in Cloudflare R2 (S3-compatible). The bucket is created by hand,
# not managed here. Credentials and endpoint come from the environment:
#   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY  - R2 API token
#   AWS_ENDPOINT_URL_S3                        - https://<account_id>.r2.cloudflarestorage.com
terraform {
  backend "s3" {
    bucket = "vidik-tfstate"
    key    = "prod/terraform.tfstate"
    region = "auto"

    use_lockfile                = true
    use_path_style              = true
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
  }
}
