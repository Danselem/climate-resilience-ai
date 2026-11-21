locals {
  db_password = var.db_password != "" ? var.db_password : random_password.db.result
}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "main" {
  name       = "crp-${var.environment}"
  subnet_ids = aws_subnet.public[*].id

  tags = { Name = "crp-${var.environment}" }
}

# PostGIS and pgvector are both supported by RDS PostgreSQL 16, which is why the
# mart and the document index can share one instance: two logical stores, one
# engine, as in the local Compose stack.
resource "aws_db_instance" "main" {
  identifier             = "crp-${var.environment}"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = var.db_instance_class
  allocated_storage      = 20
  max_allocated_storage  = 100
  storage_type           = "gp3"
  storage_encrypted      = true
  db_name                = "crp"
  username               = "crp"
  password               = local.db_password
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = var.db_publicly_accessible
  multi_az               = false

  # N11 asks for a 24-hour RPO and a 4-hour RTO. Daily automated backups with
  # one day of retention meet the RPO; the RTO is a restore rehearsal that has
  # not been run, and is recorded as such.
  backup_retention_period = 1
  backup_window           = "02:00-03:00"
  maintenance_window      = "sun:03:30-sun:04:30"

  auto_minor_version_upgrade = true
  apply_immediately          = true
  deletion_protection        = false
  skip_final_snapshot        = false
  final_snapshot_identifier  = "crp-${var.environment}-final"

  performance_insights_enabled = false

  tags = { Name = "crp-${var.environment}" }
}
