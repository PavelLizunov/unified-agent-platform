output "nodes" {
  description = "Provisioned node summary for inventory generation."
  value = {
    for name, vm in proxmox_virtual_environment_vm.this : name => {
      vm_id        = vm.vm_id
      proxmox_node = vm.node_name
      ipv4_address = var.nodes[name].ipv4_address
      tailnet_ip   = try(var.nodes[name].tailnet_ip, null)
      tailnet_name = try(var.nodes[name].tailnet_name, null)
      k3s_role     = var.nodes[name].k3s_role
      ansible_user = var.admin_user
    }
  }
}
