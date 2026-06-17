locals {
  ssh_authorized_keys = [
    for key in split("\n", file("${path.module}/../../../ssh/agent-authorized-keys.pub")) :
    trimspace(key)
    if trimspace(key) != ""
  ]

  nodes = {
    uap-home-1 = {
      vm_id             = 201
      proxmox_node      = "pve-ninitux"
      cpu_cores         = 4
      memory_mb         = 8192
      disk_gb           = 80
      disk_datastore_id = "nfs-share"
      bridge            = "vmbr0"
      ipv4_address      = "192.168.0.201"
      ipv4_prefix       = 24
      ipv4_gateway      = "192.168.0.1"
      k3s_role          = "server"
      tailnet_ip        = "100.106.223.120"
      tailnet_name      = "uap-home-1.tail9fd337.ts.net"
    }

    uap-home-2 = {
      vm_id             = 202
      proxmox_node      = "pve-ninitux3"
      cpu_cores         = 2
      memory_mb         = 4096
      disk_gb           = 32
      disk_datastore_id = "nfs-share"
      bridge            = "vmbr0"
      ipv4_address      = "192.168.0.202"
      ipv4_prefix       = 24
      ipv4_gateway      = "192.168.0.1"
      k3s_role          = "agent"
      tailnet_ip        = "100.94.228.67"
      tailnet_name      = "uap-home-2.tail9fd337.ts.net"
    }

    uap-ops-1 = {
      vm_id             = 203
      proxmox_node      = "pve-ninitux"
      cpu_cores         = 2
      memory_mb         = 2048
      disk_gb           = 30
      disk_datastore_id = "nfs-share"
      bridge            = "vmbr0"
      ipv4_address      = "192.168.0.203"
      ipv4_prefix       = 24
      ipv4_gateway      = "192.168.0.1"
      k3s_role          = "ops"
      tailnet_ip        = null
      tailnet_name      = null
      tags              = ["deploy"]
    }
  }
}

module "nodes" {
  source = "../../modules/proxmox-vm"

  nodes               = local.nodes
  cloud_image_file_id = var.cloud_image_file_id
  ssh_authorized_keys = local.ssh_authorized_keys
  dns_domain          = var.dns_domain
  dns_servers         = var.dns_servers
}
