#!/usr/bin/env bash
# One-time: move local terraform.tfstate into the R2 bucket and store the
# R2 credentials as GitHub secrets for CI.
#
# Needs an R2 API token (Cloudflare dashboard -> R2 -> Manage API tokens ->
# Object Read & Write, scoped to vidik-tfstate). Run from infra/ with the
# local terraform.tfstate and prod.tfvars present.
set -euo pipefail
cd "$(dirname "$0")"

read -rp "R2 Access Key ID: " AWS_ACCESS_KEY_ID
read -rsp "R2 Secret Access Key: " AWS_SECRET_ACCESS_KEY
echo
CF_ACCOUNT_ID=$(sed -nE 's/^cf_account_id *= *"(.*)"/\1/p' prod.tfvars)
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
export AWS_ENDPOINT_URL_S3="https://${CF_ACCOUNT_ID}.r2.cloudflarestorage.com"

rm -f backend_override.tf
terraform init -migrate-state -force-copy -input=false
terraform state list >/dev/null # fails if the remote state isn't readable

gh secret set TF_STATE_R2_ACCESS_KEY_ID --body "$AWS_ACCESS_KEY_ID"
gh secret set TF_STATE_R2_SECRET_ACCESS_KEY --body "$AWS_SECRET_ACCESS_KEY"

mkdir -p .local-state-backup
mv terraform.tfstate* .local-state-backup/ 2>/dev/null || true
echo "Done. State is in R2; local copies moved to infra/.local-state-backup/"
