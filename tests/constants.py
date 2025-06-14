from algojig import TealishProgram
from algosdk import transaction
from datetime import datetime, timezone

registry_approval_program = TealishProgram('contracts/registry/registry_approval.tl')
registry_clear_state_program = TealishProgram('contracts/registry/registry_clear_state.tl')

order_approval_program = TealishProgram('contracts/order/order_approval.tl')
order_clear_state_program = TealishProgram('contracts/order/order_clear_state.tl')

# Added for test dependency.
vault_approval_program = TealishProgram("tests/vault/vault_approval.tl")
vault_clear_state_program = TealishProgram("tests/vault/vault_clear_state.tl")

router_mock_approval_program = TealishProgram("tests/router_mock/router_approval.tl")
router_clear_state_program = TealishProgram("tests/router_mock/router_clear_state.tl")

# App Creation Config
order_app_global_schema = transaction.StateSchema(num_uints=16, num_byte_slices=16)
order_app_local_schema = transaction.StateSchema(num_uints=0, num_byte_slices=0)
order_app_extra_pages = 3

registry_app_global_schema = transaction.StateSchema(num_uints=16, num_byte_slices=16)
registry_app_local_schema = transaction.StateSchema(num_uints=8, num_byte_slices=8)
registry_app_extra_pages = 3

MAY_1 = int(datetime(2024, 5, 1, tzinfo=timezone.utc).timestamp())

DAY = 86400
WEEK = DAY * 7
MAX_UINT64 = 18446744073709551615

CURRENT_VERSION = 3
