# Reference AWS EKS deployment (the same chart works on GKE/AKS).
#
# Usage:
#   terraform init
#   terraform plan -var="app_name=My Product" -var="app_slug=my-product" \
#     -var="domain=my-product.example.com" -var="secret_key=..." -var="fernet_keys=..."
#   terraform apply
#
# Creates: VPC + EKS cluster + node group, then installs the application Helm
# chart (API + Web + optional postgres/NATS) behind an ALB ingress.

variable "region" {
  default = "eu-west-1"
}

variable "app_name" {
  description = "Human-facing application name"
  default     = "Application"
}

variable "app_slug" {
  description = "Lowercase DNS-style application identifier"
  default     = "app"

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.app_slug))
    error_message = "app_slug must be a lowercase DNS-style identifier."
  }
}

variable "domain" {
  description = "Ingress host, e.g. app.example.com"
}

variable "secret_key" {
  description = "JWT signing key (generate: openssl rand -hex 32)"
}

variable "fernet_keys" {
  description = "Fernet encryption key (generate: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
}

variable "eks_version" {
  default = "1.30"
}

variable "instance_types" {
  default = ["t3.medium"]
}

variable "node_count" {
  default = 2
}

provider "aws" {
  region = var.region
}

data "aws_availability_zones" "available" {}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.8.1"

  name = "${var.app_slug}-vpc"
  cidr = "10.0.0.0/16"

  azs             = data.aws_availability_zones.available.names
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

  enable_nat_gateway   = true
  enable_vpn_gateway   = false
  enable_dns_hostnames = true
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "20.8.5"

  cluster_name    = var.app_slug
  cluster_version = var.eks_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  eks_managed_node_groups = {
    main = {
      desired_size   = var.node_count
      min_size       = 1
      max_size       = 5
      instance_types = var.instance_types
    }
  }
}

# ----------------------------------------------------------------------------
# Application Helm release
# ----------------------------------------------------------------------------

resource "kubernetes_namespace" "app" {
  metadata {
    name = var.app_slug
  }
}

resource "kubernetes_secret" "app" {
  metadata {
    name      = "${var.app_slug}-secrets"
    namespace = kubernetes_namespace.app.metadata[0].name
  }

  data = {
    SECRET_KEY   = var.secret_key
    FERNET_KEYS  = var.fernet_keys
    DATABASE_URL = "postgresql+asyncpg://app:change-me@${var.app_slug}-postgres.${var.app_slug}.svc.cluster.local:5432/app"
    NATS_URL     = "nats://${var.app_slug}-nats.${var.app_slug}.svc.cluster.local:4222"
  }
}

resource "helm_release" "app" {
  name       = var.app_slug
  namespace  = kubernetes_namespace.app.metadata[0].name
  chart      = "../../infra/helm/app"
  depends_on = [kubernetes_secret.app]

  values = [
    <<-EOT
    appName: ${jsonencode(var.app_name)}
    appSlug: "${var.app_slug}"
    nameOverride: "${var.app_slug}"
    image:
      repository: <your-registry>/${var.app_slug}
      apiTag: latest
      webTag: latest
    existingSecret: ${var.app_slug}-secrets
    corsOrigins: "https://${var.domain}"
    frontendUrl: "https://${var.domain}"
    ingress:
      enabled: true
      className: alb
      host: ${var.domain}
      tls:
        enabled: false  # TLS terminated at ALB via ACM certificate
    EOT
  ]
}

# ----------------------------------------------------------------------------
# AWS Load Balancer Controller (for ALB ingress)
# ----------------------------------------------------------------------------

resource "helm_release" "aws_lb_controller" {
  name       = "aws-load-balancer-controller"
  namespace  = "kube-system"
  chart      = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  version    = "1.8.1"

  set {
    name  = "clusterName"
    value = var.app_slug
  }

  set {
    name  = "serviceAccount.name"
    value = "aws-load-balancer-controller"
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = module.aws_lb_iam_role.iam_role_arn
  }

  depends_on = [module.eks]
}

module "aws_lb_iam_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "5.39.0"

  role_name                              = "${var.app_slug}-lb-controller"
  attach_load_balancer_controller_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:aws-load-balancer-controller"]
    }
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", var.app_slug]
    }
  }
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", var.app_slug]
  }
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "ingress_host" {
  value = var.domain
}
