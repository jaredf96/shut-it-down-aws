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

Attach `app_policy_json` to whatever role runs the backend.

## 2. Run the backend

The backend is a standard FastAPI app — deploy it either way:

### Option A — Container (ECS / App Runner / Fargate)

Build and push [backend/Dockerfile](../backend/Dockerfile) to ECR, then run it
with these env vars set:

- `DYNAMODB_TABLE_NAME` (from the Terraform output)
- `AUTH_REQUIRED=true` (SaaS mode)
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID` (for billing)
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

## 3. Stripe billing setup

> **This is a prototype, not a billing system.** It creates Checkout sessions,
> verifies webhook signatures and keeps plan state server-side, but it has no
> webhook idempotency or replay handling, no payment-failure states and no
> customer portal. Note also that `billing_enabled()` only checks for
> `STRIPE_SECRET_KEY`, so setting that without `STRIPE_PRICE_ID` and
> `STRIPE_WEBHOOK_SECRET` leaves it half-configured. Set all three or none.

1. Create a Product + recurring Price in Stripe; set `STRIPE_PRICE_ID`.
2. Add a webhook endpoint pointing at `POST /billing/webhook`; set
   `STRIPE_WEBHOOK_SECRET`.
3. With `STRIPE_SECRET_KEY` set, the app routes upgrades through Stripe Checkout
   (`POST /billing/checkout`) and applies `checkout.session.completed` /
   `customer.subscription.deleted` webhooks to the tenant's plan.

Without Stripe configured, the app runs in local mode where an admin sets the
plan directly via `POST /billing/plan` (handy for development).

## 4. Frontend

Build the static site (`cd frontend && npm run build`) and host `dist/` on S3 +
CloudFront (or any static host). Set `VITE_API_BASE_URL` to the deployed API and
`VITE_API_KEY` if you want a baked-in key.
