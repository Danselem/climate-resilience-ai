data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "crp-${var.environment}" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "crp-${var.environment}" }
}

# Two public subnets: the load balancer and the Fargate tasks live here. There
# is no NAT gateway, deliberately. A single NAT costs about a third of the
# monthly budget; the alternative is tasks with public IPs but no inbound
# access except from the load balancer's security group, which is what these
# security groups enforce. Revisit when egress must be private.
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = { Name = "crp-${var.environment}-public-${count.index}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "crp-${var.environment}-public" }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "alb" {
  name        = "crp-${var.environment}-alb"
  description = "Public entry point. The only resource with inbound internet access."
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP. TLS terminates at the load balancer in a real deployment."
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "crp-${var.environment}-alb" }
}

resource "aws_security_group" "tasks" {
  name        = "crp-${var.environment}-tasks"
  description = "API and worker tasks. No inbound except from the load balancer."
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "API port from the load balancer only"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "crp-${var.environment}-tasks" }
}

resource "aws_security_group" "database" {
  name        = "crp-${var.environment}-db"
  description = "Postgres, reachable only from the tasks and any explicit operator CIDRs."
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from API and worker tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.tasks.id]
  }

  dynamic "ingress" {
    for_each = var.db_ingress_cidrs
    content {
      description = "Operator access for loading the mart"
      from_port   = 5432
      to_port     = 5432
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "crp-${var.environment}-db" }
}
