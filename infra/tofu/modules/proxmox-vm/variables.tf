variable "nodes" {
  description = "VM definitions keyed by hostname."
  type = map(object({
    vm_id                   = number
    proxmox_node            = string
    cpu_cores               = number
    memory_mb               = number
    disk_gb                 = number
    disk_datastore_id       = string
    cloud_init_datastore_id = optional(string)
    bridge                  = string
    ipv4_address            = string
    ipv4_prefix             = number
    ipv4_gateway            = string
    k3s_role                = string
    tailnet_ip              = optional(string)
    tailnet_name            = optional(string)
    tags                    = optional(list(string), [])
  }))
}

variable "cloud_image_file_id" {
  description = "Existing Proxmox cloud image file id, for example nfs-share:import/debian-12-genericcloud-amd64.qcow2."
  type        = string
}

variable "admin_user" {
  description = "Bootstrap SSH user created by cloud-init."
  type        = string
  default     = "uap"
}

variable "ssh_authorized_keys" {
  description = "Public SSH keys injected into the bootstrap user."
  type        = list(string)
}

variable "dns_domain" {
  description = "DNS search domain for cloud-init."
  type        = string
  default     = null
}

variable "dns_servers" {
  description = "DNS servers for cloud-init."
  type        = list(string)
  default     = []
}

variable "cpu_type" {
  description = "Proxmox CPU type."
  type        = string
  default     = "host"
}

variable "start_on_create" {
  description = "Start VMs after provisioning."
  type        = bool
  default     = true
}

variable "qemu_agent_enabled" {
  description = "Enable QEMU guest agent integration in Proxmox VM config."
  type        = bool
  default     = true
}
