# Deployment

This is a **starting-point skeleton**, not a turnkey production deploy. It
provisions the DynamoDB table and documents the two supported runtime shapes.

## 1. Provision the table (Terraform)

```bash
cd deploy/terraform
terraform init
terraform apply -var table_name=cloud-lab-scans
# -> outputs: table_name, table_arn, app_policy_json
```

Attach `app_policy_json` to whatever role runs the backend — on ECS that is the
task role, on Lambda the execution role. Both already exist by the time you get
here, which is why neither needs the template below.

**Running it yourself, with no such role?** `deploy/cloudformation/platform-role.yaml`
creates one, with the same policy, plus a trust policy naming you. That role's
ARN is what every onboarded account trusts (`docs/SECURITY.md` § Onboarding an
account, step 0), so it has to exist before any account can be onboarded — and
it must not be deleted and recreated afterwards, which strands every target that
trusts it. The template deliberately does **not** trust `ecs-tasks.amazonaws.com`
or `lambda.amazonaws.com`: a service principal alone would make it look like a
working hosted runtime role while it still lacked the service-specific
permissions those runtimes need (CloudWatch Logs for Lambda; ECS separates the
task role from the task execution role).

## 2. Run the backend

The backend is a standard FastAPI app — deploy it either way:

### Option A — Container (ECS / App Runner / Fargate)

Build and push [backend/Dockerfile](../backend/Dockerfile) to ECR, then run it
with these env vars set:

- `DYNAMODB_TABLE_NAME` (from the Terraform output)
- `AUTH_REQUIRED=true` (require an API key on every request)
- optionally `ENABLE_LIVE_PRICING=true`, `ENABLE_CLEANUP_ACTIONS=true`

The container's task role should have the `app_policy_json` permissions. No
mounted credentials needed — it uses the role.

### Option B — AWS Lambda + API Gateway

The same image runs on Lambda via the Mangum adapter
([backend/app/lambda_handler.py](../backend/app/lambda_handler.py)):

- Lambda handler: `app.lambda_handler.handler`
- Front it with API Gateway (HTTP API) or a Lambda Function URL.
- Same env vars + IAM as Option A.

> Extend `terraform/main.tf` with the `aws_lambda_function` (package_type =
> "Image"), the IAM role, and the API Gateway — left out here to keep the
> skeleton small.

## 3. Lab fixtures — the one billable artifact here

Everything above provisions the tool. `cloudformation/lab-fixtures.yaml` is the
opposite: it creates the *leftovers* the tool is supposed to find, in a target
account, so `docs/DEMO.md`'s walkthrough has something real to discover.

```bash
deploy/lab-fixtures.sh up     target      # deploy, then stop the instance
deploy/lab-fixtures.sh status target      # what is standing, and its rate
deploy/lab-fixtures.sh down   target      # delete, then verify nothing survived
```

Two things about it are load-bearing:

**It is separate from `cloudformation/scanner-role.yaml`, permanently.** That
template is what a student runs in their own account, and it must never create
anything that costs money. This one exists to cost money. Do not merge them, and
do not add a fixture to the onboarding template —
`backend/tests/test_lab_fixtures_template.py` fails if this stack grows an IAM
principal, which is the other half of the same separation.

**It is ephemeral.** The canonical state between walkthroughs is that the stack
does not exist. `down` deletes it and then re-checks by tag, exiting non-zero and
naming survivors, because a project about resources left running cannot leave its
own fixtures running. The expensive fixtures — NAT Gateway, load balancer, RDS —
are off unless you pass `--nat`, `--alb` or `--rds`.

## 4. Frontend

Build the static site (`cd frontend && npm run build`) and host `dist/` on S3 +
CloudFront (or any static host). Set `VITE_API_BASE_URL` to the deployed API and
`VITE_API_KEY` if you want a baked-in key.
