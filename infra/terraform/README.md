# MaryGenAI AWS Read-Only Retrieval Environment

This Terraform root deploys the remote, read-only MaryGenAI MCP and Dataset
Viewer test environment:

```text
API Gateway HTTP API
  -> Lambda Python 3.13
     -> /mcp with the MCP credential
     -> /api/viewer/* with a separate Viewer credential
     -> /health without corpus data
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

Generate separate temporary MCP and Viewer tokens into ignored private files.
The commands print only each digest and path, not the token:

```bash
uv run marygenai mcp generate-access-token \
  --output-path data/private/mcp-dev-access-token.json
uv run marygenai mcp generate-access-token \
  --output-path data/private/viewer-dev-access-token.json
```

Store both plaintext tokens in a password manager and keep them distinct. Copy
only the reported SHA-256 digests into `mcp_bearer_token_sha256` and
`viewer_bearer_token_sha256` in a local `terraform.tfvars`. The ignored token
files are created with mode `0600` and are never overwritten by the command:

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
terraform output -raw viewer_api_base_url
```

Health does not expose corpus data:

```bash
curl "$(terraform output -raw health_endpoint)"
```

MCP requests require:

```text
Authorization: Bearer <pilot-token>
```

Viewer requests require the separate Viewer token:

```bash
curl --fail-with-body \
  --header "Authorization: Bearer <viewer-token>" \
  "$(terraform output -raw viewer_api_base_url)/meta"
curl --fail-with-body \
  --header "Authorization: Bearer <viewer-token>" \
  "$(terraform output -raw viewer_api_base_url)/studies?page=1&pageSize=6"
```

The Viewer token must fail on `/mcp`, the MCP token must fail on
`/api/viewer/*`, and Viewer credentials are never accepted in a query string.
The future Cloudflare proxy receives only the Viewer token.

Bearer remains the preferred transport. The development environment can enable
an explicit query-token compatibility mode only for hosts that cannot configure
fixed request headers. Other credential parameter names remain rejected, and
providing both header and query credentials is rejected as ambiguous.

Do not place a secret-bearing connector URL in documentation, tickets,
screenshots, shell history, logs, or committed configuration. Configure the
endpoint and credential directly in the authorized host, then rotate the token
after any unintended exposure. Never include patient-identifying information in
MCP requests.

The MCP query-token mode is a temporary shared-pilot compatibility boundary.
It never applies to Viewer routes. Disable it when fixed request headers are
available. OAuth or another per-user mechanism is required before claiming
individual identity, scopes, or independent revocation.

## Snapshot Update

Rebuild the ignored local index, verify it, and run a new plan. Terraform uploads
the DuckDB and manifest under content-addressed S3 keys. Lambda validates the
DuckDB SHA-256 before opening it and reuses the verified `/tmp` copy in a warm
execution environment. Before every apply, compare the planned Lambda index hash
and object key with the approved snapshot; never let a stale local variable file
replace a newer deployed snapshot unintentionally.
