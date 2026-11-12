resource "aws_cognito_user_pool" "main" {
  name                     = "citeguard"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length = 10
  }

  admin_create_user_config {
    allow_admin_create_user_only = !var.allow_signup
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_domain" "main" {
  domain       = "citeguard-${local.account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
}

locals {
  site_url = "https://${aws_cloudfront_distribution.site.domain_name}/"
}

# Public browser client: no secret, authorization code + PKCE (apps/web/src/auth.ts).
resource "aws_cognito_user_pool_client" "web" {
  name                                 = "web"
  user_pool_id                         = aws_cognito_user_pool.main.id
  generate_secret                      = false
  supported_identity_providers         = ["COGNITO"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  # The API validates tokens with Cognito GetUser, which needs the last scope.
  allowed_oauth_scopes = ["openid", "email", "aws.cognito.signin.user.admin"]
  callback_urls        = [local.site_url, "http://localhost:5173/"]
  logout_urls          = [local.site_url, "http://localhost:5173/"]
}
