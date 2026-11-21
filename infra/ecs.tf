resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/crp-${var.environment}/api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/crp-${var.environment}/worker"
  retention_in_days = 14
}

resource "aws_ecs_cluster" "main" {
  name = "crp-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

locals {
  # One image, two entrypoints. Everything environment-specific arrives as
  # configuration; no application logic branches on where it is running.
  common_environment = [
    { name = "CRP_LOG_LEVEL", value = "INFO" },
    { name = "LLM_MODELS", value = var.llm_models },
    { name = "CRP_MUNICIPALITY", value = "ethekwini" },
  ]

  common_secrets = [
    { name = "CRP_DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn },
    { name = "CRP_DOCUMENTS_DSN", valueFrom = aws_secretsmanager_secret.database_url.arn },
    { name = "OPENROUTER_API_KEY", valueFrom = aws_secretsmanager_secret.openrouter.arn },
    { name = "CRP_API_KEY", valueFrom = aws_secretsmanager_secret.api_key.arn },
  ]
}

resource "aws_ecs_task_definition" "api" {
  family                   = "crp-${var.environment}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
    essential = true
    command   = ["serve", "--host", "0.0.0.0", "--port", "8000"]

    portMappings = [{ containerPort = 8000, protocol = "tcp" }]

    environment = local.common_environment
    secrets     = local.common_secrets

    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "crp-${var.environment}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "worker"
    image     = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
    essential = true
    command   = ["worker"]

    environment = local.common_environment
    secrets     = local.common_secrets

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])
}

resource "aws_lb" "api" {
  name               = "crp-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  idle_timeout = 120
}

resource "aws_lb_target_group" "api" {
  name        = "crp-${var.environment}-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # /ask holds a connection for 2-4 s; a 5 s default would cut it off.
  deregistration_delay = 30
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_ecs_service" "api" {
  name            = "crp-${var.environment}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle { ignore_changes = [desired_count] }
}

resource "aws_ecs_service" "worker" {
  name            = "crp-${var.environment}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

# --- alarms ---------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "target_5xx" {
  alarm_name          = "crp-${var.environment}-api-5xx"
  alarm_description   = "The API is returning server errors."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.api.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  alarm_name          = "crp-${var.environment}-api-unhealthy"
  alarm_description   = "No healthy API target. The pilot is down."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.api.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "queue_depth" {
  alarm_name          = "crp-${var.environment}-reports-backlog"
  alarm_description   = "Report jobs are queueing faster than the worker drains them."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = { QueueName = aws_sqs_queue.reports.name }

  alarm_actions = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "worker_cpu" {
  alarm_name          = "crp-${var.environment}-worker-cpu"
  alarm_description   = "Report rendering is saturating the worker."
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 85
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.worker.name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
}
