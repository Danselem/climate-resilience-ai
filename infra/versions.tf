terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State is local for the pilot. A shared environment needs a remote backend
  # with locking; using local state twice would silently fork the infrastructure.
  #
  # backend "s3" {
  #   bucket         = "crp-terraform-state"
  #   key            = "pilot/terraform.tfstate"
  #   region         = "af-south-1"
  #   dynamodb_table = "crp-terraform-locks"
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "climate-resilience"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
