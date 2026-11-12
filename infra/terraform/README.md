# CiteGuard on AWS

Terraform for the deployment in `Project.txt` section 8.1: one EC2 host running Docker Compose (API, worker, Postgres + pgvector) behind CloudFront, with S3, SQS, Cognito and CloudWatch around it.

```
Browser ── HTTPS ──> CloudFront ──┬─ /*      ──> S3 (React build, private, OAC)
                                  └─ /api/*  ──> EC2 t4g.micro :80 (CloudFront IPs only)
                                                   ├─ api      (FastAPI)
                                                   ├─ worker   (SQS consumer)
                                                   └─ postgres (pgvector, no published port)
Browser ── presigned PUT ──> S3 uploads      EC2 ──> SQS jobs ──(3 failures)──> DLQ ──> alarm email
Browser ── sign-in ──> Cognito               EC2 <── SSM Parameter Store (config and secrets)
GitHub Actions ── OIDC ──> ECR push, S3 sync, SSM Run Command (no stored AWS keys)
```

## What it costs

Rough us-east-1 list prices. This is not a quote: check the [AWS Pricing Calculator](https://calculator.aws/) before you apply.

| Resource | Monthly cost |
| :--- | :--- |
| EC2 t4g.micro | about $0.0084 per hour while running (about $6 if it runs all month) |
| Public IPv4 address | about $0.005 per hour while running (about $3.65 all month); nothing while stopped |
| EBS 10 GB gp3 | about $0.80, also while stopped |
| S3, SQS, CloudFront, CloudWatch, ECR | cents at demo traffic |
| Cognito, SSM parameters, Budgets, EventBridge Scheduler | $0 at this size |
| **Total** | **about $1 a month if it runs about 20 hours for demos; about $11 if it never stops** |

LLM and embedding tokens (Groq, Voyage) are billed by those providers, not AWS.

## Deploy

You need Terraform 1.6 or newer and AWS credentials for an account you may create resources in.

1. Create the resources (about 10 minutes, mostly CloudFront).

   ```bash
   cd infra/terraform
   echo 'alert_email = "you@example.com"' > terraform.tfvars   # git-ignored
   terraform init
   terraform plan     # read it before the next step
   terraform apply
   ```

   AWS emails two confirmation links to that address (SNS alarms and Budgets). Click both.
   If your account already has the GitHub OIDC provider, add `-var create_github_oidc_provider=false`.

2. Set the three secrets. Terraform creates them as `CHANGE_ME` so the real values never reach state or git.

   ```bash
   aws ssm put-parameter --overwrite --type SecureString --name /citeguard/app/GROQ_API_KEY      --value '...'
   aws ssm put-parameter --overwrite --type SecureString --name /citeguard/app/VOYAGE_API_KEY    --value '...'
   aws ssm put-parameter --overwrite --type SecureString --name /citeguard/app/POSTGRES_PASSWORD --value "$(openssl rand -hex 24)"
   ```

   Set the Postgres password once, before the first deploy. The database keeps the password it was first started with.

3. In GitHub, open Settings → Secrets and variables → Actions → Variables and add `AWS_ROLE_ARN` with the `github_deploy_role_arn` output.

4. Run the **Deploy** workflow from the Actions tab. It builds the arm64 image, pushes it to ECR, publishes the web app and restarts the containers.

5. Open the `site_url` output and create an account.

## Operate

```bash
ID=$(terraform output -raw instance_id)
aws ec2 start-instances --instance-ids $ID && aws ec2 wait instance-running --instance-ids $ID
terraform apply                                 # points CloudFront at the instance's new address (a few minutes)
aws ssm start-session --target $ID              # shell on the host, no SSH
aws logs tail /citeguard/app --follow           # api, worker and postgres logs
```

The instance stops itself at midnight IST and nothing restarts it, so the two start commands above are what you run before a demo. The site loads while it is stopped, but every API call fails. Containers come back by themselves after a start.

To keep it up overnight, apply with `-var stop_nightly=false`. If uploads fail for lack of memory, apply with `-var instance_type=t4g.small` (about twice the hourly price).

Sign-up is open by default, so anyone with the URL can use your LLM quota. Apply with `-var allow_signup=false` to create users yourself in the Cognito console.

## Backups

The host dumps the database to `s3://<uploads bucket>/backups/` every day at 18:00 UTC and S3 deletes dumps after 14 days. Prove a restore works once:

```bash
aws ssm start-session --target $ID
sudo -i
aws s3 ls s3://<uploads bucket>/backups/
docker exec citeguard-postgres createdb -U citeguard restore_test
aws s3 cp s3://<uploads bucket>/backups/citeguard-<date>.sql.gz - | gunzip \
  | docker exec -i citeguard-postgres psql -U citeguard -d restore_test
docker exec citeguard-postgres psql -U citeguard -d restore_test -c 'SELECT count(*) FROM chunks'
docker exec citeguard-postgres dropdb -U citeguard restore_test
```

## Tear down

```bash
aws s3 rm s3://$(terraform output -raw uploads_bucket) --recursive   # Terraform will not delete a bucket with files in it
terraform destroy
```

## Known limits

- The instance has no fixed address, to avoid paying for one while it is stopped. Forget the `terraform apply` after a start and the API is unreachable.

- One instance holds the API, the worker and the database. If it fails, the site is down until it restarts, and data since the last nightly dump is lost.
- CloudFront reaches the instance over HTTP. Viewers always get HTTPS, and the security group accepts CloudFront addresses only. Move to an HTTPS origin once the project has its own domain.
- Editing `user_data.sh.tftpl` does not change a running instance (replacing it would wipe the database). Apply such changes by hand through Session Manager.
