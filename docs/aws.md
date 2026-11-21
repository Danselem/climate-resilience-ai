# Deploying to AWS

The pilot runs the same image as local development. Terraform provisions the
environment; the application never branches on where it is running.

**Status: the configuration is written and validates. It has not been applied to
an AWS account, so no smoke test has been run and the cost table is an estimate.**

## What gets created

| Resource | Role in the pilot |
|---|---|
| VPC, two public subnets, IGW | No NAT gateway: see "Choices" below |
| RDS PostgreSQL 16, `db.t4g.micro` | Mart and document index in one instance, two logical stores |
| ECR repository | One image, two entrypoints |
| ECS cluster, Fargate | `api` service behind an ALB, `worker` service draining the queue |
| ALB | Public entry point on port 80, health check `/health` |
| S3 bucket | Raw inputs, processed outputs, manifests, reports (90-day expiry) |
| SQS + DLQ | Report jobs, three attempts before dead-lettering |
| Secrets Manager | Database URL, OpenRouter key, client API key |
| CloudWatch | Log groups, four alarms, SNS topic |
| IAM | Execution role for pulling and logging; task role for its own data |

## Apply

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
terraform init          # local state for the pilot; see versions.tf for the S3 backend
terraform plan -out pilot.tfplan
terraform apply pilot.tfplan
```

Then, before the services can start:

```bash
# 1. The application's model key. Terraform creates the secret empty on purpose:
#    a key in state is a key in every plan.
aws secretsmanager put-secret-value \
  --secret-id "$(terraform output -raw openrouter_secret)" \
  --secret-string "sk-or-..."

# 2. Push the image.
aws ecr get-login-password --region af-south-1 \
  | docker login --username AWS --password-stdin "$(terraform output -raw ecr_repository)"
docker build -t "$(terraform output -raw ecr_repository):0.1.0" .
docker push "$(terraform output -raw ecr_repository):0.1.0"
```

Deploy that tag by setting `image_tag = "0.1.0"` and applying again. The ECS
services roll forward with the circuit breaker enabled, so a task that fails its
health check is rolled back rather than left serving.

## Loading the mart

The image contains code and the catalogue, not datasets — they are never baked
into an image. The database therefore starts empty and the API reports
`mart_rows: 0` until the pipeline has run against it.

The build is deterministic and offline once the raw files exist:

```bash
export CRP_DATABASE_URL="$(aws secretsmanager get-secret-value \
  --secret-id "$(terraform output -raw database_url_secret)" \
  --query SecretString --output text)"

uv run climate-resilience wards
uv run climate-resilience climate
uv run climate-resilience mart
uv run climate-resilience exposure
uv run climate-resilience flood
uv run climate-resilience flood-exposure
uv run climate-resilience documents --rebuild
```

`wards` and `climate` need the raw artifacts, so this runs from a machine that
has them and a route to the database. For the pilot that means one of:

1. `db_publicly_accessible = true` plus your address in `db_ingress_cidrs`,
   load, then set both back to false; or
2. a bastion or VPN, leaving the database unreachable from the internet.

**A fully automated load (raw files in S3, a one-off ECS task) is not built.**
It is the next piece of work if deployments need to be repeatable without a
laptop.

Verify what landed:

```bash
curl "$(terraform output -raw api_url)/health"
# {"status":"ok","mart_rows":1707,"documents":"configured"}
```

## Operational notes

- **The client key.** `POST /ask` and every read route require `X-API-Key` when
  `CRP_API_KEY` is set. Read it with
  `aws secretsmanager get-secret-value --secret-id "$(terraform output -raw api_key_secret)"`.
- **Queue depth.** The worker is what drains it. If the alarm fires and the
  queue keeps growing, the worker is dead rather than slow: check its log group
  first.
- **Backups.** Daily automated backups with one day of retention meet the
  24-hour RPO. The 4-hour RTO is a rehearsal that has not been run — restoring
  into a scratch instance and timing it is the test, and it is outstanding.
- **TLS.** There is none. The listener is HTTP on port 80; a real deployment
  needs an ACM certificate and a 443 listener, plus a redirect.

## Choices worth knowing

**No NAT gateway.** A single NAT costs roughly a third of the monthly budget.
Tasks run in public subnets with public IPs and no inbound rule except the load
balancer's security group; the database accepts connections only from the task
security group. That is a real trade — egress is not private — and it is the
first thing to change if the pilot handles anything sensitive.

**One database, two stores.** The mart (`indicator_value`) and the document
index (`document_chunk`) share the instance but never share a table. PostGIS and
pgvector are both supported on RDS PostgreSQL 16, which is what makes this
possible without a second managed service.

**One image.** `api` runs `serve`, `worker` runs `worker`. The recent commit
SHA of both is the same by construction, which is what makes local/AWS parity a
fact rather than an intention.

## Estimated cost

| Item | Monthly |
|---|---|
| RDS `db.t4g.micro`, 20 GB gp3, 1-day backups | ~$15 |
| Fargate: 2 × API (0.5 vCPU / 2 GB) + 1 × worker | ~$55 |
| ALB + minimal LCU | ~$18 |
| ECR, S3, SQS, CloudWatch, Secrets Manager | ~$5 |
| **Total** | **~$93** |

Inside the $150/month target (N13), with headroom of about $57. The figure is
an estimate from list prices, not a bill.
