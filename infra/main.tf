terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "1.51.0"
    }
  }
}
provider "hcloud" {
  token = var.hcloud_token
}

resource "hcloud_server" "scraper_server" {
  name        = "scraper-app-server"
  image       = "docker-ce"
  server_type = "cpx11"
  location    = "fsn1"                      # DE Falkenstein fsn1
  ssh_keys    = [hcloud_ssh_key.default.id] # Link to your SSH key resource
  labels = {
    env = "production"
    app = "scraper"
  }
}

resource "hcloud_ssh_key" "default" {
  name       = "scraper-ssh-key"
  public_key = file("~/.ssh/id_ed25519.pub")
}
