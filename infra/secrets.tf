resource "aws_secretsmanager_secret" "database" {
  name                    = "crp-${var.environment}-database"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "database" {
  secret_id = aws_secretsmanager_secret.database.id
  secret_string = jsonencode({
    username = aws_db_instance.main.username
    password = local.db_password
    host     = aws_db_instance.main.address
    port     = aws_db_instance.main.port
    dbname   = aws_db_instance.main.db_name
  })
}

# The application needs one URL, and ECS injects environment values whole, so
# the URL is stored rather than assembled from parts at start-up.
resource "aws_secretsmanager_secret" "database_url" {
  name                    = "crp-${var.environment}-database-url"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  secret_string = format(
    "postgresql+psycopg://%s:%s@%s:%d/%s",
    aws_db_instance.main.username,
    local.db_password,
    aws_db_instance.main.address,
    aws_db_instance.main.port,
    aws_db_instance.main.db_name,
  )
}

# The OpenRouter key is written once by the operator and never read back. It is
# not in Terraform state: a key in state is a key in every plan and every copy
# of the state file.
resource "aws_secretsmanager_secret" "openrouter" {
  name                    = "crp-${var.environment}-openrouter"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret" "api_key" {
  name                    = "crp-${var.environment}-api-key"
  recovery_window_in_days = 7
}

resource "random_password" "api_key" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret_version" "api_key" {
  secret_id     = aws_secretsmanager_secret.api_key.id
  secret_string = random_password.api_key.result
}
