variable "region" {
  type    = string
  default = "us-east-1"
}

variable "instance_type" {
  description = "t4g.micro (1 GB + swap) is enough for a demo. Use t4g.small if uploads run out of memory; changing it only restarts the instance."
  type        = string
  default     = "t4g.micro"
}

variable "alert_email" {
  description = "Receives budget alerts and CloudWatch alarms. AWS sends a confirmation link first."
  type        = string
}

variable "github_repo" {
  description = "owner/name of the repository allowed to deploy through GitHub OIDC."
  type        = string
  default     = "abhishekkamble12/Verbatim"
}

variable "create_github_oidc_provider" {
  description = "Set to false if this AWS account already has the GitHub OIDC provider (one per account)."
  type        = bool
  default     = true
}

variable "allow_signup" {
  description = "true: anyone can create an account and spend your LLM quota. false: you create users in the Cognito console."
  type        = bool
  default     = true
}

variable "stop_nightly" {
  description = "Stop the instance at midnight IST to save compute cost. You start it again yourself."
  type        = bool
  default     = true
}
