output "api_url" {
  description = "Public entry point. There is no TLS on port 80 in the pilot."
  value       = "http://${aws_lb.api.dns_name}"
}

output "ecr_repository" {
  description = "Push the image here, then set image_tag."
  value       = aws_ecr_repository.app.repository_url
}

output "database_endpoint" {
  description = "RDS endpoint. Not reachable from outside the VPC by default."
  value       = aws_db_instance.main.endpoint
  sensitive   = true
}

output "database_url_secret" {
  description = "Secret holding the SQLAlchemy URL the tasks use."
  value       = aws_secretsmanager_secret.database_url.arn
}

output "report_queue" {
  description = "SQS queue for report jobs, with a dead-letter queue behind it."
  value       = aws_sqs_queue.reports.url
}

output "data_bucket" {
  description = "Raw inputs, processed outputs, manifests and reports."
  value       = aws_s3_bucket.data.bucket
}

output "openrouter_secret" {
  description = "Write the API key here before starting the services."
  value       = aws_secretsmanager_secret.openrouter.arn
}

output "api_key_secret" {
  description = "Client key required by every endpoint except /health."
  value       = aws_secretsmanager_secret.api_key.arn
}
