# MaryGenAI AWS Dev Environment

This Terraform root deploys the first remote, read-only MaryGenAI MCP test
environment:

```text
API Gateway HTTP API
  -> Lambda Python 3.13
  -> immutable DuckDB copied from private S3 to /tmp
  -> DuckDB opened with read_only=True
```

The environment has no SQLite, review-state, provider, or write tool. The
retrieval snapshot contains AI-classified candidate evidence, not reviewed
clinical truth, medical advice, or treatment recommendations.

## Local Prerequisites

- Python 3.13 and `uv`;
- Terraform 1.5.7 or later;
- AWS credentials with S3, IAM, Lambda, API Gateway v2, and CloudWatch Logs
  deployment permissions;
- the ignored DuckDB index and adjacent manifest.

Terraform calls AWS service APIs directly. It does not use CloudFormation.

The deployment principal also needs ACM certificate lifecycle permissions.
DNS remains in Cloudflare and is never changed by this Terraform root.

## Prepare

Generate a temporary pilot token into an ignored private file. The command
prints only the digest and path, not the token:

```bash
uv run marygenai mcp generate-access-token \
  --output-path data/private/mcp-dev-access-token.json
```

Store the plaintext token in a password manager. Copy only the reported SHA-256
digest into a local `terraform.tfvars`. The ignored token file is created with
mode `0600` and is never overwritten by the command:

```bash
cp infra/terraform/dev.tfvars.example infra/terraform/terraform.tfvars
```

Build the Linux Lambda package:

```bash
uv run marygenai deployment build-lambda
```

## Validate And Plan

Run from this directory so the example relative artifact paths resolve:

```bash
cd infra/terraform
terraform init
terraform fmt -check
terraform validate
terraform plan -out=marygenai-mcp-dev.tfplan
terraform show marygenai-mcp-dev.tfplan
```

## Bootstrap External DNS

The custom hostname uses an ACM public certificate while DNS remains in
Cloudflare. Bootstrap the certificate first:

```bash
terraform apply -target=aws_acm_certificate.mcp
terraform output -json acm_dns_validation_records
```

Create the reported ACM validation CNAME in Cloudflare with proxying disabled
(`DNS only`). Do not create the public `mcp-server` CNAME yet. After ACM reports
`ISSUED`, create and apply a normal full plan:

```bash
terraform plan -out=marygenai-mcp-dev.tfplan
terraform apply marygenai-mcp-dev.tfplan
terraform output -raw custom_domain_cname_target
```

Now create the application CNAME in Cloudflare:

```text
Name: mcp-server
Type: CNAME
Target: <custom_domain_cname_target>
Proxy status: DNS only for the first smoke test
```

Cloudflare proxying and WAF controls can be enabled after the direct custom
domain passes the MCP smoke test. Keep the ACM validation CNAME permanently so
ACM can renew the certificate.

Review every create, update, and delete before applying:

```bash
terraform apply marygenai-mcp-dev.tfplan
```

The local state, variable file, plan, generated Lambda ZIP, DuckDB, and manifest
are ignored. The provider lock file should be committed.

## Smoke Test

After apply:

```bash
terraform output -raw health_endpoint
terraform output -raw mcp_endpoint
```

Health does not expose corpus data:

```bash
curl "$(terraform output -raw health_endpoint)"
```

MCP requests require:

```text
Authorization: Bearer <pilot-token>
```

Bearer remains the preferred transport. The dev environment explicitly enables
a temporary `?key=<pilot-token>` compatibility path because the maintainer's
current Claude and ChatGPT connector dialogs do not expose fixed request
headers. Other credential parameter names remain rejected, and providing both
header and query credentials is rejected as ambiguous.

Configure the hosted connectors as follows:

```text
Claude name: MaryGenAI
Claude URL: https://mcp-server.marygenai.com/mcp?key=<pilot-token>
Claude OAuth Client ID/Secret: leave empty

ChatGPT name: MaryGenAI
ChatGPT Server URL: https://mcp-server.marygenai.com/mcp?key=<pilot-token>
ChatGPT Auth: No Auth
```

`No Auth` describes the host-platform handshake; MaryGenAI still verifies the
URL key before serving MCP data. Treat the complete connector URL as a secret.
Do not paste it into tickets, screenshots, shell history, or logs, and do not
include patient-identifying information in MCP requests. Rotate the token by
generating a new one, replacing the Terraform digest, applying, and updating the
connector URL.

Claude documents fixed request headers as a gradual beta rollout. If the
Request headers section becomes available, remove the query key and configure
`Authorization` with the complete value `Bearer <pilot-token>` instead. OAuth
remains the future per-user identity and revocation boundary.

## Snapshot Update

Rebuild the ignored local index, verify it, and run a new plan. Terraform uploads
the DuckDB and manifest under content-addressed S3 keys. Lambda validates the
DuckDB SHA-256 before opening it and reuses the verified `/tmp` copy in a warm
execution environment.
