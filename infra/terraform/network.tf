resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true # CloudFront needs a DNS name for the EC2 origin
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

# One public subnet and no NAT gateway (a NAT costs more than the instance).
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = true
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

# Port 80 from CloudFront only. No SSH (Session Manager instead), and Postgres is never exposed.
resource "aws_security_group" "app" {
  name_prefix = "citeguard-app-"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTP from CloudFront edge servers only"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
