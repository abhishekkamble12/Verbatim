output "site_url" {
  value = local.site_url
}

output "github_deploy_role_arn" {
  description = "Set this as the AWS_ROLE_ARN repository variable in GitHub."
  value       = aws_iam_role.deploy.arn
}

output "instance_id" {
  value = aws_instance.app.id
}

output "uploads_bucket" {
  value = aws_s3_bucket.uploads.bucket
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}
