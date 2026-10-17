terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "1.51.0"
    }
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5"
    }
    grafana = {
      source  = "grafana/grafana"
      version = "~> 4.23"
    }
  }
}
provider "hcloud" {
  token = var.hcloud_token
}

provider "digitalocean" {
  token = var.digitalocean_token
}

resource "hcloud_server" "scraper_server" {
  name        = "scraper-app-server"
  image       = "docker-ce"
  server_type = "cpx11"
  location    = "fsn1"                                            # DE Falkenstein fsn1
  ssh_keys    = [hcloud_ssh_key.default.id, hcloud_ssh_key.ci.id] # Link to your SSH key resource
  labels = {
    env = "production"
    app = "scraper"
  }

  lifecycle {
    # The Hetzner API returns an empty location on refresh, which would otherwise
    # force a replacement of the server.
    ignore_changes = [location]
  }
}

resource "hcloud_ssh_key" "default" {
  name       = "scraper-ssh-key"
  public_key = file("${path.module}/ssh/default.pub")
}

resource "hcloud_ssh_key" "ci" {
  name       = "ci-scraper-ssh-key"
  public_key = file("${path.module}/ssh/ci.pub")
}

# DigitalOcean PostgreSQL database cluster
resource "digitalocean_database_cluster" "postgres" {
  name             = "scraper-postgres-cluster"
  engine           = "pg"
  version          = "17"
  size             = "db-s-1vcpu-1gb"
  storage_size_mib = "30720" # 30 GiB, must be a 10 GiB increment
  region           = "fra1"
  node_count       = 1
}

# Create a database within the cluster
resource "digitalocean_database_db" "scraper_db" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "scraper"
}

# Create a database user
resource "digitalocean_database_user" "scraper_user" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "scraper_user"
}


# TODO: firewall should be configured in terraform, currently managed in the UI
# resource "digitalocean_database_firewall" "scraper_server_fw_rule" {
#   cluster_id = digitalocean_database_cluster.postgres.id

#   rule {
#     type  = "ip_addr"
#     value = "${hcloud_server.scraper_server.ipv4_address}/32"
#   }
# }
