# Vidik

Similar website that already has article clustering by news event: https://www.times.si/

## Ideas:

- show article alterations
- people mentioned in article (like youtube)
- visualize the frequency of publishing for a news provider with a graph

## Terraform

```bash
cd infra
terraform init
terraform apply -var-file=prod.tvars
```

## SSH

```bash
ssh root@<server_ip>
```
