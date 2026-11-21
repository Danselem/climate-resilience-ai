variable "region" {
  description = "AWS region. af-south-1 is the closest region to the pilot."
  type        = string
  default     = "af-south-1"
}

variable "environment" {
  description = "Deployment name, used in resource names and tags."
  type        = string
  default     = "pilot"
}

variable "vpc_cidr" {
  description = "Address space for the pilot VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "db_instance_class" {
  description = "RDS instance class. t4g.micro is enough for 1,707 rows and a pilot's query load."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_password" {
  description = "Database password. Empty means generate one and store it in Secrets Manager."
  type        = string
  default     = ""
  sensitive   = true
}

variable "db_publicly_accessible" {
  description = <<-EOT
    Whether RDS gets a public endpoint. Only for loading the mart from a host
    outside the VPC; leave false and use a bastion or VPN otherwise.
  EOT
  type        = bool
  default     = false
}

variable "db_ingress_cidrs" {
  description = "CIDRs allowed to reach the database directly. Empty means nobody."
  type        = list(string)
  default     = []
}

variable "api_cpu" {
  description = "Fargate CPU units for each API task (256 = 0.25 vCPU)."
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "Fargate memory (MiB) for each API task. The embedding model is the large object."
  type        = number
  default     = 2048
}

variable "api_desired_count" {
  description = "API tasks. Two keeps the pilot available through a single task replacement."
  type        = number
  default     = 2
}

variable "worker_cpu" {
  description = "Fargate CPU units for the report worker."
  type        = number
  default     = 512
}

variable "worker_memory" {
  description = "Fargate memory (MiB) for the report worker."
  type        = number
  default     = 2048
}

variable "image_tag" {
  description = "Image tag to deploy. The same image serves the API and the worker."
  type        = string
  default     = "latest"
}

variable "llm_models" {
  description = "OpenRouter model chain, tried in order."
  type        = string
  default     = "amazon/nova-micro-v1,particle-ai/particle-1:free"
}

variable "alarm_email" {
  description = "Where CloudWatch alarms go. Empty creates the topic without a subscription."
  type        = string
  default     = ""
}
