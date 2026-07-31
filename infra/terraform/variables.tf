variable "aws_region" {
  description = "AWS region for the isolated MCP environment."
  type        = string
  default     = "us-east-2"
}

variable "aws_profile" {
  description = "Optional local AWS shared-config profile. Set null in CI."
  type        = string
  default     = null
  nullable    = true
}

variable "environment" {
  description = "Short environment name used in resource names and tags."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9-]{1,12}$", var.environment))
    error_message = "environment must contain 1-12 lowercase letters, digits, or hyphens."
  }
}

variable "custom_domain_name" {
  description = "Public custom hostname for the remote MCP endpoint. DNS remains externally managed."
  type        = string
  default     = "mcp-server.marygenai.com"

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$", var.custom_domain_name))
    error_message = "custom_domain_name must be a lowercase fully qualified domain name."
  }
}

variable "index_file_path" {
  description = "Local ignored DuckDB snapshot uploaded as an immutable S3 object."
  type        = string
}

variable "manifest_file_path" {
  description = "Local ignored retrieval manifest uploaded for deployment provenance."
  type        = string
}

variable "lambda_zip_path" {
  description = "Local Lambda ZIP created by marygenai deployment build-lambda."
  type        = string
}

variable "mcp_bearer_token_sha256" {
  description = "SHA-256 of the temporary high-entropy pilot bearer token."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.mcp_bearer_token_sha256))
    error_message = "mcp_bearer_token_sha256 must contain 64 lowercase hexadecimal digits."
  }
}

variable "allow_query_token" {
  description = "Allow the explicit dev-only ?key= compatibility credential for hosted connector UIs without static headers."
  type        = bool
  default     = false
}

variable "lambda_memory_mb" {
  description = "Lambda memory allocation in MiB."
  type        = number
  default     = 1024
}

variable "lambda_reserved_concurrency" {
  description = "Environment-level concurrency ceiling used as an initial cost guard."
  type        = number
  default     = 10
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the dev environment."
  type        = number
  default     = 14
}

variable "force_destroy_index_bucket" {
  description = "Allow Terraform to delete a non-empty dev index bucket."
  type        = bool
  default     = false
}
