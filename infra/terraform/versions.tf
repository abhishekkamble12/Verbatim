terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
  # Local state (git-ignored). One person, one machine; move to an S3 backend if that changes.
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "citeguard" }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
}
