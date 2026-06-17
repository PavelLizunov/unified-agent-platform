variable "proxmox_endpoint" {
  description = "Proxmox API endpoint."
  type        = string
  default     = "https://192.168.0.169:8006/"
}

variable "proxmox_username" {
  description = "Proxmox username for password auth. Prefer API token for repeatable automation."
  type        = string
  default     = null
}

variable "proxmox_password" {
  description = "Proxmox password for password auth. Keep in local tfvars only."
  type        = string
  sensitive   = true
  default     = null
}

variable "proxmox_api_token" {
  description = "Proxmox API token in provider format. Keep in local tfvars only."
  type        = string
  sensitive   = true
  default     = null
}

variable "proxmox_insecure" {
  description = "Allow self-signed Proxmox certificates."
  type        = bool
  default     = true
}

variable "proxmox_ssh_agent" {
  description = "Use local ssh-agent for Proxmox node SSH when provider operations need it."
  type        = bool
  default     = true
}

variable "proxmox_ssh_username" {
  description = "SSH user for Proxmox node operations."
  type        = string
  default     = "root"
}

variable "proxmox_ssh_password" {
  description = "Optional Proxmox SSH password. Keep in local tfvars only."
  type        = string
  sensitive   = true
  default     = null
}

variable "cloud_image_file_id" {
  description = "Existing Debian 12 cloud image in Proxmox import storage."
  type        = string
  default     = "nfs-share:import/debian-12-genericcloud-amd64.qcow2"
}

variable "dns_servers" {
  description = "DNS servers injected by cloud-init."
  type        = list(string)
  default     = ["192.168.0.1", "1.1.1.1"]
}

variable "dns_domain" {
  description = "DNS search domain injected by cloud-init."
  type        = string
  default     = "local"
}
