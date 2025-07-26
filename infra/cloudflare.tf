provider "cloudflare" {
  api_token = var.cf_api_token
}

resource "cloudflare_r2_bucket" "images_bucket" {
  account_id   = var.cf_account_id
  name         = "images"
  jurisdiction = "eu"

}


// TODO: add cors
resource "cloudflare_r2_custom_domain" "images_custom_domain" {
  account_id   = var.cf_account_id
  bucket_name  = cloudflare_r2_bucket.images_bucket.name
  domain       = "images.vidik.si"
  enabled      = true
  zone_id      = var.cf_zone_id
  jurisdiction = "eu"
}
