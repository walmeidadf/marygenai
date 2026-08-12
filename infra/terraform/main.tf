locals {
  name_prefix      = "marygenai-mcp-${var.environment}"
  index_sha256     = filesha256(var.index_file_path)
  manifest_sha256  = filesha256(var.manifest_file_path)
  index_object_key = "retrieval-indexes/${local.index_sha256}.duckdb"
  manifest_key     = "retrieval-manifests/${local.manifest_sha256}.json"

  common_tags = {
    Project     = "MaryGenAI"
    Component   = "read-only-mcp"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_s3_bucket" "retrieval" {
  bucket        = "${local.name_prefix}-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  force_destroy = var.force_destroy_index_bucket
}

resource "aws_s3_bucket_public_access_block" "retrieval" {
  bucket = aws_s3_bucket.retrieval.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "retrieval" {
  bucket = aws_s3_bucket.retrieval.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "retrieval" {
  bucket = aws_s3_bucket.retrieval.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "retrieval" {
  bucket = aws_s3_bucket.retrieval.id

  rule {
    id     = "expire-old-noncurrent-snapshots"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

resource "aws_s3_object" "index" {
  bucket       = aws_s3_bucket.retrieval.id
  key          = local.index_object_key
  source       = var.index_file_path
  source_hash  = local.index_sha256
  content_type = "application/vnd.duckdb"

  metadata = {
    sha256      = local.index_sha256
    trust-level = "ai-classified-candidate"
  }

  depends_on = [
    aws_s3_bucket_public_access_block.retrieval,
    aws_s3_bucket_server_side_encryption_configuration.retrieval,
    aws_s3_bucket_versioning.retrieval,
  ]
}

resource "aws_s3_object" "manifest" {
  bucket       = aws_s3_bucket.retrieval.id
  key          = local.manifest_key
  source       = var.manifest_file_path
  source_hash  = local.manifest_sha256
  content_type = "application/json"

  metadata = {
    sha256      = local.manifest_sha256
    trust-level = "ai-classified-candidate"
  }

  depends_on = [
    aws_s3_bucket_public_access_block.retrieval,
    aws_s3_bucket_server_side_encryption_configuration.retrieval,
    aws_s3_bucket_versioning.retrieval,
  ]
}

resource "aws_iam_role" "lambda" {
  name = "${local.name_prefix}-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_index_read" {
  name = "read-one-retrieval-index"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadVersionedRetrievalIndex"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = aws_s3_object.index.arn
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.name_prefix}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "mcp" {
  function_name = local.name_prefix
  description   = "Read-only MaryGenAI MCP and Dataset Viewer gateway."
  role          = aws_iam_role.lambda.arn
  handler       = "marygenai.mcp_server.lambda_runtime.handler"
  runtime       = "python3.13"
  architectures = ["x86_64"]

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  memory_size                    = var.lambda_memory_mb
  timeout                        = 29
  reserved_concurrent_executions = var.lambda_reserved_concurrency

  ephemeral_storage {
    size = 512
  }

  environment {
    variables = {
      MARYGENAI_INDEX_S3_BUCKET             = aws_s3_bucket.retrieval.id
      MARYGENAI_INDEX_S3_KEY                = aws_s3_object.index.key
      MARYGENAI_INDEX_SHA256                = local.index_sha256
      MARYGENAI_INDEX_LOCAL_PATH            = "/tmp/marygenai_candidate_retrieval_v1.duckdb"
      MARYGENAI_MCP_BEARER_TOKEN_SHA256     = var.mcp_bearer_token_sha256
      MARYGENAI_MCP_ALLOW_QUERY_TOKEN       = tostring(var.allow_query_token)
      MARYGENAI_MCP_ALLOWED_HOSTS           = "${aws_apigatewayv2_api.mcp.id}.execute-api.${var.aws_region}.amazonaws.com,${var.custom_domain_name}"
      MARYGENAI_VIEWER_BEARER_TOKEN_SHA256  = var.viewer_bearer_token_sha256
      MARYGENAI_RETRIEVAL_MANIFEST_S3_KEY   = aws_s3_object.manifest.key
      MARYGENAI_CANDIDATE_EVIDENCE_BOUNDARY = "ai_classified_candidate"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda_index_read,
    aws_iam_role_policy_attachment.lambda_basic,
  ]
}

resource "aws_apigatewayv2_api" "mcp" {
  name          = local.name_prefix
  protocol_type = "HTTP"
  description   = "Authenticated MCP and Dataset Viewer endpoints for read-only candidate retrieval."
}

resource "aws_acm_certificate" "mcp" {
  domain_name       = var.custom_domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "mcp" {
  certificate_arn = aws_acm_certificate.mcp.arn
  validation_record_fqdns = [
    for option in aws_acm_certificate.mcp.domain_validation_options :
    option.resource_record_name
  ]

  timeouts {
    create = "45m"
  }
}

resource "aws_apigatewayv2_domain_name" "mcp" {
  domain_name = var.custom_domain_name

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.mcp.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.mcp.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.mcp.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

resource "aws_apigatewayv2_route" "routes" {
  for_each = toset([
    "ANY /mcp",
    "GET /health",
    "GET /api/viewer/meta",
    "GET /api/viewer/studies",
    "GET /api/viewer/studies/{document_id}",
  ])

  api_id    = aws_apigatewayv2_api.mcp.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.mcp.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
}

resource "aws_apigatewayv2_api_mapping" "mcp" {
  api_id      = aws_apigatewayv2_api.mcp.id
  domain_name = aws_apigatewayv2_domain_name.mcp.id
  stage       = aws_apigatewayv2_stage.default.id
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowHttpApiInvocation"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.mcp.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.mcp.execution_arn}/*/*"
}
