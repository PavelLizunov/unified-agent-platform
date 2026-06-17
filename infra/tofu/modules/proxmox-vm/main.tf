resource "proxmox_virtual_environment_vm" "this" {
  for_each = var.nodes

  vm_id       = each.value.vm_id
  name        = each.key
  node_name   = each.value.proxmox_node
  description = "Unified Agent Platform node. Managed by OpenTofu."
  tags        = concat(["uap", "managed-by-opentofu", each.value.k3s_role], each.value.tags)

  on_boot = true
  started = var.start_on_create

  agent {
    enabled = var.qemu_agent_enabled
  }

  cpu {
    cores = each.value.cpu_cores
    type  = var.cpu_type
  }

  memory {
    dedicated = each.value.memory_mb
  }

  disk {
    datastore_id = each.value.disk_datastore_id
    import_from  = var.cloud_image_file_id
    interface    = "virtio0"
    iothread     = true
    discard      = "on"
    size         = each.value.disk_gb
  }

  initialization {
    datastore_id = coalesce(each.value.cloud_init_datastore_id, each.value.disk_datastore_id)

    ip_config {
      ipv4 {
        address = "${each.value.ipv4_address}/${each.value.ipv4_prefix}"
        gateway = each.value.ipv4_gateway
      }
    }

    dynamic "dns" {
      for_each = var.dns_domain != null || length(var.dns_servers) > 0 ? [1] : []
      content {
        domain  = var.dns_domain
        servers = var.dns_servers
      }
    }

    user_account {
      username = var.admin_user
      keys     = var.ssh_authorized_keys
    }
  }

  network_device {
    bridge = each.value.bridge
    model  = "virtio"
  }

  operating_system {
    type = "l26"
  }

  serial_device {}
}
