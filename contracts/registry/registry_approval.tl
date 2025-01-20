#pragma version 10
#tealish version git+https://github.com/Hipo/tealish.git@f1c2b72aaeb586ed082c380a638ed2e7ca47bcae

# Tinyman Order Protocol Registry
# License: https://github.com/tinymanorg/tinyman-order-protocol/blob/main/LICENSE
# Documentation: https://docs.tinyman.org


# Name: e<user_address>
struct Entry:
    app_id: int
end


# Global State

const bytes ORDER_FEE_RATE_KEY = "order_fee_rate"
const bytes ENTRY_COUNT_KEY = "entry_count"
const bytes PROPOSED_MANAGER_KEY = "proposed_manager"
const bytes MANAGER_KEY = "manager"

# TODO
const bytes ORDER_APP_HASH = 0x8e3de033e55ab9b365c62adca97fcae8eb8be3468d79e9fc5ac0920b7695d2a8


router:
    create_application
    update_application
    init
    propose_manager
    accept_manager
    set_order_fee_rate
    create_entry
end


# Permission: anyone
@public(OnCompletion=CreateApplication)
func create_application(manager_address: bytes[32]):
    app_global_put(MANAGER_KEY, manager_address)

    # create_application(manager_address)
    log(ARC28Event("create_application(address)", manager_address))
    return
end


# TODO: Remove function for mainnet
@public(OnCompletion=UpdateApplication)
func update_application():
    assert(Txn.Sender == app_global_get("manager"))
    return
end


# Permission: manager
@public()
func init():
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    log(ARC28Event("init()"))
    return
end


# permission: manager
@public()
func propose_manager(new_manager: bytes[32]):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    app_global_put(PROPOSED_MANAGER_KEY, new_manager)
    log(ARC28Event("propose_manager(address)", new_manager))
    return
end


# The proposed manager must call this function to become the manager.
# permission: proposed_manager
@public()
func accept_manager():
    bytes proposed_manager = app_global_get(PROPOSED_MANAGER_KEY)
    assert(Txn.Sender == proposed_manager)

    app_global_put(MANAGER_KEY, proposed_manager)
    app_global_put(PROPOSED_MANAGER_KEY, "")
    log(ARC28Event("accept_manager(address)", proposed_manager))
    return
end


@public()
func set_order_fee_rate(fee_rate: int):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    app_global_put(ORDER_FEE_RATE_KEY, fee_rate)

    log(ARC28Event("set_order_fee_rate(uint64)", itob(fee_rate)))
    return
end


# Description: Assert that `Txn.GroupIndex - 1` is an app creation transaction and verify approval_program.
# Permission: Anyone
@public()
func create_entry():
    box<Entry> entry = CreateBox(Concat("e", Txn.Sender))

    int app_creation_index = Txn.GroupIndex - 1
    assert(Gtxn[app_creation_index].Sender == Txn.Sender)
    assert(Gtxn[app_creation_index].TypeEnum == Appl)
    assert(Gtxn[app_creation_index].OnCompletion == NoOp)
    assert(Gtxn[app_creation_index].ApplicationArgs[0] == "create_application")
    assert(Gtxn[app_creation_index].ApplicationArgs[1] == itob(Global.CurrentApplicationID))

    bytes approval_hash = sha512_256(Gtxn[app_creation_index].ApprovalProgram)
    assert(approval_hash == ORDER_APP_HASH)

    entry.app_id = Gtxn[app_creation_index].CreatedApplicationID

    int entry_count = app_global_get(ENTRY_COUNT_KEY)
    app_global_put(ENTRY_COUNT_KEY, entry_count + 1)

    # Logs
    log(ARC28Event("entry(address,uint64)", Txn.Sender, itob(entry.app_id)))

    return
end