#!/bin/sh
# Runs inside LocalStack once it is ready: creates the bucket and queue the app expects.
set -e
awslocal s3 mb s3://citeguard-uploads || true
awslocal s3api put-bucket-cors --bucket citeguard-uploads --cors-configuration '{"CORSRules":[{"AllowedOrigins":["http://localhost:5173","http://127.0.0.1:5173"],"AllowedMethods":["GET","PUT"],"AllowedHeaders":["*"]}]}'
awslocal sqs create-queue --queue-name citeguard-jobs
