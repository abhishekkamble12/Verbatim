# /citeguard/app/*    -> the instance's .env (deploy.sh reads the whole path)
# /citeguard/deploy/* -> read by the GitHub Actions deploy workflow
locals {
  app_params = {
    AUTH_MODE     = "cognito"
    AWS_REGION    = var.region
    S3_BUCKET     = aws_s3_bucket.uploads.bucket
    SQS_QUEUE_URL = aws_sqs_queue.jobs.url
    LLM_PROVIDER  = "groq"
  }
  deploy_params = {
    ECR_REPO               = aws_ecr_repository.app.repository_url
    FRONTEND_BUCKET        = aws_s3_bucket.frontend.bucket
    CF_DISTRIBUTION_ID     = aws_cloudfront_distribution.site.id
    INSTANCE_ID            = aws_instance.app.id
    VITE_COGNITO_DOMAIN    = "${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com"
    VITE_COGNITO_CLIENT_ID = aws_cognito_user_pool_client.web.id
  }
}

resource "aws_ssm_parameter" "app" {
  for_each = local.app_params
  name     = "/citeguard/app/${each.key}"
  type     = "String"
  value    = each.value
}

resource "aws_ssm_parameter" "deploy" {
  for_each = local.deploy_params
  name     = "/citeguard/deploy/${each.key}"
  type     = "String"
  value    = each.value
}

# Created as placeholders. You set the real values with `aws ssm put-parameter --overwrite`,
# so secrets are never in Terraform state or git. deploy.sh refuses to start while one says CHANGE_ME.
resource "aws_ssm_parameter" "secret" {
  for_each = toset(["GROQ_API_KEY", "VOYAGE_API_KEY", "POSTGRES_PASSWORD"])
  name     = "/citeguard/app/${each.key}"
  type     = "SecureString"
  value    = "CHANGE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}
