#pragma version 10
#tealish version git+https://github.com/tinymanorg/tealish.git@d7441973671cf6b79dd55843016892f4b86ceeba

# Tinyman Order Protocol Registry
# License: https://github.com/tinymanorg/tinyman-order-protocol/blob/main/LICENSE
# Documentation: https://docs.tinyman.org


# Name: e<user_address>
struct Entry:
    app_id: int
end

# Name: v<version>
struct AppVersion:
    approval_hash: bytes[32]
    unused: bytes[950]
end


# Global State

const bytes VAULT_APP_ID_KEY = "vault_app_id"
const bytes ROUTER_APP_ID_KEY = "router_app_id"
const bytes ORDER_FEE_RATE_KEY = "order_fee_rate"
const bytes GOVERNOR_ORDER_FEE_RATE_KEY = "governor_order_fee_rate"
const bytes GOVERNOR_FEE_RATE_POWER_THRESHOLD = "governor_fee_rate_power_threshold"
const bytes ENTRY_COUNT_KEY = "entry_count"
const bytes PROPOSED_MANAGER_KEY = "proposed_manager"
const bytes MANAGER_KEY = "manager"
const bytes LATEST_VERSION_KEY = "latest_version"

# Local State

const bytes IS_ENDORSED_KEY = "is_endorsed"


router:
    create_application
    update_application
    init
    propose_manager
    accept_manager
    asset_opt_in
    set_order_fee_rate
    set_governor_order_fee_rate
    set_governor_fee_rate_power_threshold
    claim_fees
    endorse
    deendorse
    user_opt_in
    create_entry
    emit_event
    verify_update
    approve_version
end


# Permission: anyone
@public(OnCompletion=CreateApplication)
func create_application(vault_app_id: int, router_app_id: int, manager_address: bytes[32]):
    app_global_put(MANAGER_KEY, manager_address)
    app_global_put(VAULT_APP_ID_KEY, vault_app_id)
    app_global_put(ROUTER_APP_ID_KEY, router_app_id)
    app_global_put(ORDER_FEE_RATE_KEY, 30)
    app_global_put(GOVERNOR_ORDER_FEE_RATE_KEY, 15)
    app_global_put(GOVERNOR_FEE_RATE_POWER_THRESHOLD, 500_000_000)

    # create_application(vault_app_id,router_app_id,manager_address)
    log(ARC28Event("create_application(uint64,uint64,address)", itob(vault_app_id), itob(router_app_id), manager_address))
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


# Prerequisites: Required Algo to cover minimum balance increase must be supplied in previous Gtxn.
@public()
func asset_opt_in(asset_id: int):
    int is_opted_in = opt_in_to_asset_if_needed(asset_id)

    if is_opted_in:
        assert(Gtxn[-1].TypeEnum == Pay)
        assert(Gtxn[-1].Receiver == Global.CurrentApplicationAddress)
        # TODO: replace the hardcoded value with Global.AssetOptInMinBalance.
        assert(Gtxn[-1].Amount >= 100000)
    end

    return
end


@public()
func set_order_fee_rate(fee_rate: int):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    app_global_put(ORDER_FEE_RATE_KEY, fee_rate)

    log(ARC28Event("set_order_fee_rate(uint64)", itob(fee_rate)))
    return
end


@public()
func set_governor_order_fee_rate(fee_rate: int):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    app_global_put(GOVERNOR_ORDER_FEE_RATE_KEY, fee_rate)

    log(ARC28Event("set_governor_order_fee_rate(uint64)", itob(fee_rate)))
    return
end


@public()
func set_governor_fee_rate_power_threshold(threshold: int):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    app_global_put(GOVERNOR_FEE_RATE_POWER_THRESHOLD, threshold)

    log(ARC28Event("set_governor_fee_rate_power_threshold(uint64)", itob(threshold)))
    return
end


@public()
func claim_fees(asset_id: int):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    int opted_in
    int asset_balance

    if asset_id:
        opted_in, asset_balance = asset_holding_get(AssetBalance, Global.CurrentApplicationAddress, asset_id)
        assert(opted_in)
    else:
        asset_balance = balance(Global.CurrentApplicationAddress)

        int minimum_balance = min_balance(Global.CurrentApplicationAddress)
        asset_balance = asset_balance - minimum_balance
    end

    assert(asset_balance)
    transfer(asset_id, asset_balance, Global.CurrentApplicationAddress, app_global_get(MANAGER_KEY))

    log(ARC28Event("claim_fees(uint64,uint64)", itob(asset_id), itob(asset_balance)))
    return
end


@public()
func endorse(user_address: bytes[32]):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    int is_endorsed
    is_endorsed = app_local_get(user_address, IS_ENDORSED_KEY)

    assert(!is_endorsed)
    app_local_put(user_address, IS_ENDORSED_KEY, 1)

    log(ARC28Event("endorse(address)", user_address))
    return
end


@public()
func deendorse(user_address: bytes[32]):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    int is_endorsed
    is_endorsed = app_local_get(user_address, IS_ENDORSED_KEY)

    assert(is_endorsed)
    app_local_del(user_address, IS_ENDORSED_KEY)

    log(ARC28Event("deendorse(address)", user_address))
    return
end


@public(OnCompletion=OptIn)
func user_opt_in():
    log(ARC28Event("user_opt_in(address)", Txn.Sender))
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

    verify_approval_program(app_creation_index, app_global_get(LATEST_VERSION_KEY))

    entry.app_id = Gtxn[app_creation_index].CreatedApplicationID

    int entry_count = app_global_get(ENTRY_COUNT_KEY)
    app_global_put(ENTRY_COUNT_KEY, entry_count + 1)

    # Logs
    log(ARC28Event("entry(address,uint64)", Txn.Sender, itob(entry.app_id)))

    return
end


@public()
func emit_event(event_name: bytes, user_address: bytes, data: bytes):
    box<Entry> entry = OpenBox(Concat("e", user_address))
    int app_id = Global.CallerApplicationID
    assert(app_id == entry.app_id)

    bytes event
    if event_name == "put_trigger_order":
        event = ARC28Event("put_trigger_order(uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", itob(app_id), data)
    elif event_name == "update_trigger_order":
        event = ARC28Event("update_trigger_order(uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", itob(app_id), data)
    elif event_name == "cancel_trigger_order":
        event = ARC28Event("cancel_trigger_order(uint64,uint64)", itob(app_id), data)
    elif event_name == "put_recurring_order":
        event = ARC28Event("put_recurring_order(uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", itob(app_id), data)
    elif event_name == "update_recurring_order":
        event = ARC28Event("update_recurring_order(uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", itob(app_id), data)
    elif event_name == "cancel_recurring_order":
        event = ARC28Event("cancel_recurring_order(uint64,uint64)", itob(app_id), data)
    end
    log(event)
    return
end


# Description: Assert that `Txn.GroupIndex - 1` is an app update transaction and verify approval_program.
# Permission: Anyone
@public()
func verify_update(version: int):

    int app_update_index = Txn.GroupIndex - 1
    assert(Gtxn[app_update_index].ApplicationArgs[0] == "update_application")
    assert(Gtxn[app_update_index].ApplicationArgs[1] == itob(version))

    verify_approval_program(app_update_index, version)

    return
end


# Permission: Manager
@public()
func approve_version(version: int, approval_hash: bytes[32]):
    assert(Txn.Sender == app_global_get(MANAGER_KEY))

    # the hash can be updated for the current version or a new version but not a past version
    assert(version >= app_global_get(LATEST_VERSION_KEY))
    app_global_put(LATEST_VERSION_KEY, version)

    # approval_hash must be computed using the same algorithm as used in verify_update
    box<AppVersion> version_box = CreateBox(concat("v", itob(version)))
    version_box.approval_hash = approval_hash

    return
end


func verify_approval_program(gtxn_index: int, version: int):
    box<AppVersion> version_box = OpenBox(concat("v", itob(version)))

    # 'page' here refers to chunks of size 4096. They are not the same as 'ExtraProgramPages' which are 2048 sized pages.
    int last_page = Gtxn[gtxn_index].NumApprovalProgramPages
    bytes chunk_hashes = ""
    for i in 0:last_page:
        chunk_hashes = concat(chunk_hashes, sha256(Gtxn[gtxn_index].ApprovalProgramPages[i]))
    end
    bytes approval_hash = sha256(chunk_hashes)
    assert(approval_hash == version_box.approval_hash)
    return
end


func opt_in_to_asset_if_needed(asset_id: int) int:
    int is_opted_in

    if asset_id:
        is_opted_in, _ = asset_holding_get(AssetBalance, Global.CurrentApplicationAddress, asset_id)

        if is_opted_in == 0:
            transfer(asset_id, 0, Global.CurrentApplicationAddress, Global.CurrentApplicationAddress)
        end
    end
    return !is_opted_in
end


func transfer(asset_id: int, amount: int, sender: bytes, receiver: bytes):
    if !asset_id:
        inner_txn:
            TypeEnum: Pay
            Sender: sender
            Receiver: receiver
            Amount: amount
            Fee: 0
        end
    else:
        inner_txn:
            TypeEnum: Axfer
            Sender: sender
            AssetReceiver: receiver
            AssetAmount: amount
            XferAsset: asset_id
            Fee: 0
        end
    end
    return
end