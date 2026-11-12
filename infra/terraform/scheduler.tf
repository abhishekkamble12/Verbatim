# Stops the instance at midnight IST; overnight you pay only for the disk and the address.
# Nothing starts it again: run `aws ec2 start-instances` (see README.md) before a demo.
resource "aws_iam_role" "scheduler" {
  count = var.stop_nightly ? 1 : 0
  name  = "citeguard-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  count = var.stop_nightly ? 1 : 0
  name  = "stop-instance"
  role  = aws_iam_role.scheduler[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "ec2:StopInstances"
      Resource = aws_instance.app.arn
    }]
  })
}

resource "aws_scheduler_schedule" "stop_nightly" {
  count                        = var.stop_nightly ? 1 : 0
  name                         = "citeguard-stop-nightly"
  schedule_expression          = "cron(0 0 * * ? *)"
  schedule_expression_timezone = "Asia/Kolkata"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ec2:stopInstances"
    role_arn = aws_iam_role.scheduler[0].arn
    input    = jsonencode({ InstanceIds = [aws_instance.app.id] })
  }
}
