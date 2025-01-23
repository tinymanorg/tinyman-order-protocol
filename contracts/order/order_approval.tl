#pragma version 10
#tealish version git+https://github.com/Hipo/tealish.git@f1c2b72aaeb586ed082c380a638ed2e7ca47bcae

# Tinyman Order Protocol
# License: https://github.com/tinymanorg/tinyman-order-protocol/blob/main/LICENSE
# Documentation: https://docs.tinyman.org


# Name: o<id>
struct Order:
    asset_id: int
    amount: int
    target_asset_id: int
    target_amount: int
    # Partial Filling.
    filled_amount: int
    collected_target_amount: int
    is_partial_allowed: int
    creation_timestamp: int
    expiration_timestamp: int
end


# Global State

const bytes REGISTRY_APP_ID_KEY = "registry_app_id"
const bytes REGISTRY_APP_ACCOUNT_ADDRESS_KEY = "registry_app_account_address"
const bytes VAULT_APP_ID_KEY = "vault_app_id"
const bytes ORDER_FEE_RATE_KEY = "order_fee_rate"
const bytes GOVERNOR_ORDER_FEE_RATE_KEY = "governor_order_fee_rate"
const bytes GOVERNOR_FEE_RATE_POWER_THRESHOLD = "governor_fee_rate_power_threshold"

const bytes USER_ADDRESS_KEY = "user_address"
const bytes TOTAL_ORDER_COUNT_KEY = "order_count"

const bytes PROPOSED_MANAGER_KEY = "proposed_manager"
const bytes MANAGER_KEY = "manager"

const bytes ORDER_FEE_RATE_KEY = "order_fee_rate"

# Math Constants

const int RATE_SCALER = 18446744073709551615
const int MAX_UINT64 = 18446744073709551615


router:
    create_application
    update_application
    init
    propose_manager
    accept_manager
    asset_opt_in
    put_order
    cancel_order
    start_execute_order
    end_execute_order
    collect
end


# Permission: anyone
@public(OnCompletion=CreateApplication)
func create_application(registry_app_id: int, vault_app_id: int, manager_address: bytes[32]):
    app_global_put(USER_ADDRESS_KEY, Txn.Sender)
    app_global_put(MANAGER_KEY, manager_address)

    app_global_put(REGISTRY_APP_ID_KEY, registry_app_id)
    bytes registry_app_account_address 
    _, registry_app_account_address = app_params_get(AppAddress, registry_app_id)
    app_global_put(REGISTRY_APP_ACCOUNT_ADDRESS_KEY, registry_app_account_address)
    app_global_put(VAULT_APP_ID_KEY, vault_app_id)

    # create_application(user_address,registry_app_id,vault_app_id,manager_address)
    log(ARC28Event("create_application(address,uint64,uint64,address)", Txn.Sender, itob(registry_app_id), itob(vault_app_id), manager_address))
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
func asset_opt_in(asset_ids: int[8]):
    # Required Algo to cover minimum balance increase must be supplied.
    # It is not checked explicitly.
    # Using extra balance is allowed.
    for i in 0:8:
        opt_in_to_asset_if_needed(asset_ids[i])
    end
    return
end


# Description: Create an order with the monotonically incremented ORDER_COUNT as id.
# Prerequisites: App should be opted into both `asset_id` and `target_asset_id`. Only `target_asset_id` optin checked explicitly.
# Permission: App owner (User)
@public()
func put_order(asset_id: int, amount: int, target_asset_id: int, target_amount: int, is_partial_allowed: int, expiration_timestamp: int):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)

    int total_order_count = app_global_get(TOTAL_ORDER_COUNT_KEY)
    box<Order> order = CreateBox(Concat("o", itob(total_order_count)))

    # Assertions
    assert(amount > 0)
    assert(target_amount > 0)
    assert(asset_id != target_asset_id)
    assert(expiration_timestamp > Global.LatestTimestamp)

    int is_opted_in_to_target
    is_opted_in_to_target, _ = asset_holding_get(AssetBalance, Global.CurrentApplicationAddress, target_asset_id)
    assert(is_opted_in_to_target)

    check_received_asset(Txn.GroupIndex - 1, Global.CurrentApplicationAddress, asset_id, amount)

    order.asset_id = asset_id
    order.amount = amount
    order.target_asset_id = target_asset_id
    order.target_amount = target_amount
    order.is_partial_allowed = is_partial_allowed
    order.filled_amount = 0
    order.creation_timestamp = Global.LatestTimestamp
    order.expiration_timestamp = expiration_timestamp

    app_global_put(TOTAL_ORDER_COUNT_KEY, total_order_count + 1)

    # Logs
    bytes order_data
    _, order_data = box_get(order)
    log(ARC28Event("order(address,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", user_address, itob(total_order_count), order_data))
    log(ARC28Event("put_order(uint64)", itob(total_order_count)))

    return
end


# Description: Send the `amount` or `amount - filled_amount` if partially filled to the user. Delete the order box.
# Prerequisites: If partial filling is utilized, collect method must be called before.
# Permission: App owner (User)
@public()
func cancel_order(order_id: int):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)

    box<Order> order = OpenBox(Concat("o", itob(order_id)))

    # It is assumed that the order is deleted once it is executed.
    # Send remaining amount back to user.

    int remaining_amount = order.amount
    if order.is_partial_allowed:
        remaining_amount = remaining_amount - order.filled_amount
    end

    assert(!order.collected_target_amount)

    transfer(order.asset_id, remaining_amount, Global.CurrentApplicationAddress, user_address)

    # Logs
    bytes order_data
    _, order_data = box_get(order)
    log(ARC28Event("order(address,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", user_address, itob(order_id), order_data))
    log(ARC28Event("cancel_order(uint64)", itob(order_id)))

    # Delete the box.
    _ = box_del(order)

    return
end


# Description: Method allows an executor (taker) to do arbitrary operations between `Txn.GroupIndex < i < (Txn.GroupIndex + index_diff)`.
# An executor must call `end_execute_order` at the `Txn.GroupIndex + index_diff` for the transaction group to succeed.
# Permission: Everyone
@public()
func start_execute_order(order_id: int, fill_amount: int, index_diff: int):
    box<Order> order = OpenBox(Concat("o", itob(order_id)))

    # Assertions
    assert(index_diff > 2)

    # If partial filling is not allowed, executor should fill the whole order at once. Otherwise smaller amounts are allowed.
    int remaining_amount = order.amount
    if order.is_partial_allowed:
        remaining_amount = remaining_amount - order.filled_amount
        assert(fill_amount <= remaining_amount)
    else:
        assert(fill_amount == remaining_amount)
    end

    assert(Global.LatestTimestamp <= order.expiration_timestamp)

    int end_execute_order_txn_index = Txn.GroupIndex + index_diff
    assert(Gtxn[end_execute_order_txn_index].Sender == Txn.Sender)
    assert(Gtxn[end_execute_order_txn_index].TypeEnum == Appl)
    assert(Gtxn[end_execute_order_txn_index].OnCompletion == NoOp)
    assert(Gtxn[end_execute_order_txn_index].ApplicationID == Global.CurrentApplicationID)
    assert(Gtxn[end_execute_order_txn_index].ApplicationArgs[0] == "end_execute_order")
    # Parameters `fill_amount` and `index_diff` must be the same.
    assert(Gtxn[end_execute_order_txn_index].ApplicationArgs[1] == fill_amount)
    assert(Gtxn[end_execute_order_txn_index].ApplicationArgs[2] == index_diff)

    # Transfer `fill_amount` to executor.
    transfer(order.asset_id, fill_amount, Global.CurrentApplicationAddress, Txn.Sender)

    # Logs
    log(ARC28Event("start_execute_order(uint64,address)", itob(order_id), Txn.Sender))

    return
end


# Description: Method checks the validity of the execution between `start_execute_order` and `end_execute_order`.
# An executor must return the correct amount of `target_asset_id` via an axfer at `Txn.GroupIndex - 1`. Otherwise the transaction group fails.
# Permission: Everyone
@public()
func end_execute_order(order_id: int, fill_amount: int, index_diff: int):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    box<Order> order = OpenBox(Concat("o", itob(order_id)))

    int start_execute_order_txn_index = Txn.GroupIndex - index_diff

    # Assertions
    assert(Gtxn[start_execute_order_txn_index].Sender == Txn.Sender)
    assert(Gtxn[start_execute_order_txn_index].TypeEnum == Appl)
    assert(Gtxn[start_execute_order_txn_index].OnCompletion == NoOp)
    assert(Gtxn[start_execute_order_txn_index].ApplicationID == Global.CurrentApplicationID)
    assert(Gtxn[start_execute_order_txn_index].ApplicationArgs[0] == "start_execute_order")
    # Parameters `fill_amount` and `index_diff` must be the same.
    assert(Gtxn[start_execute_order_txn_index].ApplicationArgs[1] == fill_amount)
    assert(Gtxn[start_execute_order_txn_index].ApplicationArgs[2] == index_diff)

    # Assert that user received the target amount or more.
    # TODO: Review the calculations.
    int minimum_amount
    if !order.is_partial_allowed:
        minimum_amount = order.target_amount
    else:
        minimum_amount = calculate_minimum_amount(order.amount, order.target_amount, fill_amount)
    end

    int received_amount = check_received_target_asset(Txn.GroupIndex - 1, Global.CurrentApplicationAddress, order.target_asset_id, minimum_amount)

    order.filled_amount = order.filled_amount + fill_amount
    order.collected_target_amount = order.collected_target_amount + received_amount

    # Logs
    bytes order_data
    _, order_data = box_get(order)
    log(ARC28Event("order(address,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", user_address, itob(order_id), order_data))
    log(ARC28Event("end_execute_order(uint64,address,uint64,uint64)", itob(order_id), Txn.Sender, itob(fill_amount), itob(received_amount)))

    # If all amount is filled, send the collected_target_amount to user, send the fee_amount to registry app, delete the order.
    # If partial filling is not allowed `collected_target_amount` >= `target_amount` == `received_amount`.
    # If partial filling is allowed, and user has collected partial fills beforehand, `collected_target_amount` < `target_amount`.
    if order.amount == order.filled_amount:
        int fee_amount = calculate_fee_amount(order.collected_target_amount)

        transfer(order.target_asset_id, (order.collected_target_amount - fee_amount), Global.CurrentApplicationAddress, user_address)
        transfer(order.target_asset_id, fee_amount, Global.CurrentApplicationAddress, app_global_get(REGISTRY_APP_ACCOUNT_ADDRESS_KEY))
        _ = box_del(order)
    end

    return
end


@public()
func collect(order_id: int):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)
    box<Order> order = OpenBox(Concat("o", itob(order_id)))

    assert(order.collected_target_amount)

    int fee_amount = calculate_fee_amount(order.collected_target_amount)
    assert(fee_amount)

    transfer(order.target_asset_id, (order.collected_target_amount - fee_amount), Global.CurrentApplicationAddress, user_address)
    transfer(order.target_asset_id, fee_amount, Global.CurrentApplicationAddress, app_global_get(REGISTRY_APP_ACCOUNT_ADDRESS_KEY))

    int collected_target_amount = order.collected_target_amount
    order.collected_target_amount = 0

    # Logs
    bytes order_data
    _, order_data = box_get(order)
    log(ARC28Event("order(address,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", user_address, itob(order_id), order_data))
    log(ARC28Event("collect(uint64,uint64)", itob(order_id), itob(collected_target_amount)))

    return
end


func calculate_minimum_amount(amount: int, target_amount: int, fill_amount: int) int:
    bytes target_rate = (itob(target_amount) b* itob(RATE_SCALER)) b/ itob(amount)
    int minimum_amount = btoi((itob(fill_amount) b* target_rate) b/ itob(RATE_SCALER))
    return minimum_amount
end


func calculate_fee_amount(target_amount: int) int:
    int fee_rate
    int account_voting_power = get_account_voting_power(UncheckedCast(app_global_get(USER_ADDRESS_KEY), bytes))
    int fee_rate_power_threshold = UncheckedCast(app_global_get_ex(app_global_get(REGISTRY_APP_ID_KEY), GOVERNOR_FEE_RATE_POWER_THRESHOLD), int)

    if account_voting_power > fee_rate_power_threshold:
        fee_rate = UncheckedCast(app_global_get_ex(app_global_get(REGISTRY_APP_ID_KEY), ORDER_FEE_RATE_KEY), int)
    else:
        fee_rate = UncheckedCast(app_global_get_ex(app_global_get(REGISTRY_APP_ID_KEY), GOVERNOR_ORDER_FEE_RATE_KEY), int)
    end

    int fee_amount = (target_amount * fee_rate) / 10000
    return fee_amount
end


func get_account_voting_power(address: bytes) int:
    inner_txn:
        TypeEnum: Appl
        ApplicationID: app_global_get(VAULT_APP_ID_KEY)
        ApplicationArgs[0]: "get_tiny_power_of"
        ApplicationArgs[1]: address
        Fee: 0
    end
    int voting_power = extract_uint64(Itxn.LastLog, 4)
    return voting_power
end


func opt_in_to_asset_if_needed(asset_id: int):
    if asset_id:
        int is_opted_in
        is_opted_in, _ = asset_holding_get(AssetBalance, Global.CurrentApplicationAddress, asset_id)

        if is_opted_in == 0:
            transfer(asset_id, 0, Global.CurrentApplicationAddress, Global.CurrentApplicationAddress)
        end
    end
    return
end


func check_received_asset(txn_index: int, receiver: bytes, asset_id: int, amount: int):
    if !asset_id:
        assert(Gtxn[txn_index].TypeEnum == Pay)
        assert(Gtxn[txn_index].Receiver == receiver)
        assert(Gtxn[txn_index].Amount == amount)
    else:
        assert(Gtxn[txn_index].TypeEnum == Axfer)
        assert(Gtxn[txn_index].AssetReceiver == receiver)
        assert(Gtxn[txn_index].XferAsset == asset_id)
        assert(Gtxn[txn_index].AssetAmount == amount)
    end
    return
end


func check_received_target_asset(txn_index: int, receiver: bytes, asset_id: int, minimum_amount: int) int:
    int received_amount
    if !asset_id:
        assert(Gtxn[txn_index].TypeEnum == Pay)
        assert(Gtxn[txn_index].Receiver == receiver)
        assert(Gtxn[txn_index].Amount >= minimum_amount)

        received_amount = Gtxn[txn_index].Amount
    else:
        assert(Gtxn[txn_index].TypeEnum == Axfer)
        assert(Gtxn[txn_index].AssetReceiver == receiver)
        assert(Gtxn[txn_index].XferAsset == asset_id)
        assert(Gtxn[txn_index].AssetAmount >= minimum_amount)

        received_amount = Gtxn[txn_index].AssetAmount
    end

    return received_amount
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

