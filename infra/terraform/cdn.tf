resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "citeguard-frontend"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# The browser calls /api/...; the API's routes have no prefix. Same rewrite as the Vite dev proxy.
resource "aws_cloudfront_function" "strip_api" {
  name    = "citeguard-strip-api-prefix"
  runtime = "cloudfront-js-2.0"
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      request.uri = request.uri.replace(/^\/api/, '') || '/';
      return request;
    }
  JS
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

# One HTTPS domain for both the site and the API, so the browser needs no CORS for API calls.
resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "citeguard"
  default_root_object = "index.html"
  price_class         = "PriceClass_200" # includes the India edge locations

  origin {
    origin_id                = "frontend"
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  origin {
    origin_id = "api"
    # No Elastic IP (it is billed even while the instance is stopped), so this name changes at every start:
    # run `terraform apply` after starting the instance. While it is stopped there is no name at all.
    domain_name = coalesce(aws_instance.app.public_dns, "stopped.invalid")
    custom_origin_config {
      http_port  = 80
      https_port = 443
      # shortcut: CloudFront talks to the instance over HTTP (viewers always get HTTPS). Switch to
      # https-only with a certificate on the origin once the project has its own domain.
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 60 # a chat answer can take longer than the 30s default
    }
  }

  default_cache_behavior {
    target_origin_id       = "frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
    compress               = true
  }

  ordered_cache_behavior {
    path_pattern           = "/api/*"
    target_origin_id       = "api"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.disabled.id
    # Forwards every viewer header, including Authorization, to the API.
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.strip_api.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
