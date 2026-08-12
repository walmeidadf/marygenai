output "mcp_endpoint" {
  description = "Authenticated MCP Streamable HTTP endpoint."
  value       = "https://${var.custom_domain_name}/mcp"
}

output "health_endpoint" {
  description = "Unauthenticated health endpoint without corpus data."
  value       = "https://${var.custom_domain_name}/health"
}

output "viewer_api_base_url" {
  description = "Authenticated Dataset Viewer API base URL for the future Cloudflare proxy."
  value       = "https://${var.custom_domain_name}/api/viewer"
}

output "execute_api_mcp_endpoint" {
  description = "Authenticated AWS fallback endpoint used before external DNS is configured."
  value       = "${aws_apigatewayv2_api.mcp.api_endpoint}/mcp"
}

output "execute_api_health_endpoint" {
  description = "Unauthenticated AWS fallback health endpoint."
  value       = "${aws_apigatewayv2_api.mcp.api_endpoint}/health"
}

output "execute_api_viewer_base_url" {
  description = "Authenticated AWS fallback Dataset Viewer API base URL."
  value       = "${aws_apigatewayv2_api.mcp.api_endpoint}/api/viewer"
}

output "acm_dns_validation_records" {
  description = "DNS-only CNAME records that the external DNS operator must create for ACM validation."
  value = {
    for option in aws_acm_certificate.mcp.domain_validation_options :
    option.domain_name => {
      name  = option.resource_record_name
      type  = option.resource_record_type
      value = option.resource_record_value
    }
  }
}

output "custom_domain_cname_target" {
  description = "DNS target for the external custom-domain CNAME after ACM validation."
  value       = aws_apigatewayv2_domain_name.mcp.domain_name_configuration[0].target_domain_name
}

output "retrieval_bucket" {
  description = "Private bucket containing immutable retrieval snapshots."
  value       = aws_s3_bucket.retrieval.id
}

output "retrieval_index_sha256" {
  description = "Content hash validated by Lambda before opening DuckDB."
  value       = local.index_sha256
}

output "lambda_function_name" {
  description = "Read-only gateway Lambda function used for log and performance inspection."
  value       = aws_lambda_function.mcp.function_name
}
