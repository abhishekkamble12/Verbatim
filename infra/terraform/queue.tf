resource "aws_sqs_queue" "dlq" {
  name                      = "citeguard-jobs-dlq"
  message_retention_seconds = 1209600 # 14 days to look at a failed job
}

resource "aws_sqs_queue" "jobs" {
  name                       = "citeguard-jobs"
  visibility_timeout_seconds = 300 # same as the worker's receive call
  receive_wait_time_seconds  = 20
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3 # = MAX_RETRIES in services/worker/main.py
  })
}
