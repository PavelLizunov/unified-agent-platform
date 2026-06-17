output "nodes" {
  description = "Node data that can be mirrored into Ansible inventory."
  value       = module.nodes.nodes
}

output "ansible_inventory_hint" {
  description = "Inventory file that represents this environment today."
  value       = "../../../ansible/inventories/local.yml"
}
