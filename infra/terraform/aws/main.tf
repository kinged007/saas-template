# SaaS template on AWS EKS — reference deployment (same chart works on GKE/AKS).
#
# Usage:
#   terraform init
#   terraform plan -var="domain=saas-template.example.com" -var="secret_key=..." -var="fernet_keys=..."
#   terraform apply
#
# Creates: VPC + EKS cluster + node group, then installs the SaaS template Helm
# chart (API + Web + optional postgres/NATS) behind an ALB ingress.

variable "region" {
  default = "eu-west-1"
}

variable "cluster_name" {
  default = "saas-template"
}

variable "domain" {
  description = "Ingress host, e.g. saas-template.example.com"
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

  name = "${var.cluster_name}-vpc"
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

  cluster_name    = var.cluster_name
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
# SaaS template Helm release
# ----------------------------------------------------------------------------

resource "kubernetes_namespace" "saas_template" {
  metadata {
    name = "saas-template"
  }
}

resource "kubernetes_secret" "saas_template_secrets" {
  metadata {
    name      = "saas-template-secrets"
    namespace = kubernetes_namespace.saas_template.metadata[0].name
  }

  data = {
    SECRET_KEY   = var.secret_key
    FERNET_KEYS  = var.fernet_keys
    DATABASE_URL = "postgresql+asyncpg://saas_template:change-me@saas-template-postgres.saas-template.svc.cluster.local:5432/saas_template"
    NATS_URL     = "nats://saas-template-nats.saas-template.svc.cluster.local:4222"
  }
}

resource "helm_release" "saas_template" {
  name       = "saas-template"
  namespace  = kubernetes_namespace.saas_template.metadata[0].name
  chart      = "../../infra/helm/saas-template"
  depends_on = [kubernetes_secret.saas_template_secrets]

  values = [
    <<-EOT
    image:
      repository: <your-registry>/saas-template
      apiTag: latest
      webTag: latest
    existingSecret: saas-template-secrets
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
    value = var.cluster_name
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

  role_name                              = "saas-template-lb-controller"
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
      args        = ["eks", "get-token", "--cluster-name", var.cluster_name]
    }
  }
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", var.cluster_name]
  }
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "ingress_host" {
  value = var.domain
}
