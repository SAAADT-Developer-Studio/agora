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
}

resource "hcloud_ssh_key" "default" {
  name       = "scraper-ssh-key"
  public_key = file("~/.ssh/id_ed25519.pub")
}

resource "hcloud_ssh_key" "ci" {
  name       = "ci-scraper-ssh-key"
  public_key = file("~/.ssh/id_rsa.pub")
}

# DigitalOcean PostgreSQL database cluster
resource "digitalocean_database_cluster" "postgres" {
  name       = "scraper-postgres-cluster"
  engine     = "pg"
  version    = "17"
  size       = "db-s-1vcpu-1gb"  
  storage_size_mib = "30000"
  region     = "fra1"           
  node_count = 1

  tags = ["production", "scraper", "postgres"]
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
