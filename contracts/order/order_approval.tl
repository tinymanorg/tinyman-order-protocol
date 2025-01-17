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
    target_rate: int
    # Filling fields.
    filled_amount: int
    is_partial_allowed: int
    creation_timestamp: int
    expiration_timestamp: int
end


# Global State

const bytes USER_ADDRESS_KEY = "user_address"
const bytes TOTAL_ORDER_COUNT_KEY = "order_count"
const bytes PROPOSED_MANAGER_KEY = "proposed_manager"
const bytes MANAGER_KEY = "manager"

# Math Constants

const int RATE_SCALER = 1000000000
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
end


# Permission: anyone
@public(OnCompletion=CreateApplication)
func create_application(manager_address: bytes[32]):
    app_global_put(USER_ADDRESS_KEY, Txn.Sender)
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
func put_order(asset_id: int, amount: int, target_asset_id: int, target_rate: int, is_partial_allowed: int, expiration_timestamp: int):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)

    int total_order_count = app_global_get(TOTAL_ORDER_COUNT_KEY)
    box<Order> order = CreateBox(itob(total_order_count))

    # Assertions
    assert(amount > 0)
    assert(target_rate > 0)
    assert(asset_id != target_asset_id)
    assert(expiration_timestamp > Global.LatestTimestamp)

    # TODO: Should app receive the asset?
    int is_opted_in_to_target
    is_opted_in_to_target, _ = asset_holding_get(AssetBalance, Global.CurrentApplicationAddress, target_asset_id)
    assert(is_opted_in_to_target)

    check_received_asset(Txn.GroupIndex - 1, Global.CurrentApplicationAddress, asset_id, amount)

    order.asset_id = asset_id
    order.amount = amount
    order.target_asset_id = target_asset_id
    order.target_rate = target_rate
    order.is_partial_allowed = is_partial_allowed
    order.filled_amount = 0
    order.creation_timestamp = Global.LatestTimestamp
    order.expiration_timestamp = expiration_timestamp

    app_global_put(TOTAL_ORDER_COUNT_KEY, total_order_count + 1)

    # Logs
    log(ARC28Event("order(address,int,int,int,int,int,int,int,int)", user_address, itob(total_order_count), order))
    log(ARC28Event("put_order(int)", itob(total_order_count)))

    return
end


# Description: Send the `amount` or `amount - filled_amount` if partially filled to the user. Delete the order box.
# Permission: App owner (User)
@public()
func cancel_order(order_id: int):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)

    box<Order> order = OpenBox(itob(order_id))

    # It is assumed that the order is deleted once it is executed.
    # Send remaining amount back to user.

    int remaining_amount = order.amount
    if order.is_partial_allowed:
        remaining_amount = remaining_amount - order.filled_amount
    end

    transfer(order.asset_id, remaining_amount, Global.CurrentApplicationAddress, user_address)

    # Logs
    log(ARC28Event("order(address,int,int,int,int,int,int,int,int)", user_address, itob(order_id), order))
    log(ARC28Event("cancel_order(int)", itob(order_id)))

    # Delete the box.
    _ = box_del(order)

    return
end


# Description: Method allows an executor (taker) to do arbitrary operations between `Txn.GroupIndex < i < (Txn.GroupIndex + index_diff)`.
# An executor must call `end_execute_order` at the `Txn.GroupIndex + index_diff` for the transaction group to succeed.
# Permission: Everyone
@public()
func start_execute_order(order_id: int, fill_amount: int, index_diff: int):
    box<Order> order = OpenBox(itob(order_id))

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
    log(ARC28Event("start_execute_order(int,address)", itob(order_id), Txn.Sender))

    return
end


# Description: Method checks the validity of the execution between `start_execute_order` and `end_execute_order`.
# An executor must return the correct amount of `target_asset_id` via an axfer at `Txn.GroupIndex - 1`. Otherwise the transaction group fails.
# Permission: Everyone
@public()
func end_execute_order(order_id: int, fill_amount: int, index_diff: int):
    box<Order> order = OpenBox(itob(order_id))

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
    # TODO: Update the calculation with BigInt.
    int minimum_amount = btoi((itob(fill_amount) b* itob(order.target_rate)) b/ itob(RATE_SCALER))
    check_received_target_asset(Txn.GroupIndex - 1, app_global_get(USER_ADDRESS_KEY), order.target_asset_id, minimum_amount)

    order.filled_amount = order.filled_amount + fill_amount

    # Logs
    log(ARC28Event("order(address,int,int,int,int,int,int,int,int)", app_global_get(USER_ADDRESS_KEY), itob(order_id), order))
    log(ARC28Event("end_execute_order(int,address)", itob(order_id), Txn.Sender))

    # If all amount is filled, delete the order.
    if order.amount == order.filled_amount:
        _ = box_del(order)
    end

    return
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


func check_received_target_asset(txn_index: int, receiver: bytes, asset_id: int, minimum_amount: int):
    if !asset_id:
        assert(Gtxn[txn_index].TypeEnum == Pay)
        assert(Gtxn[txn_index].Receiver == receiver)
        assert(Gtxn[txn_index].Amount >= minimum_amount)
    else:
        assert(Gtxn[txn_index].TypeEnum == Axfer)
        assert(Gtxn[txn_index].AssetReceiver == receiver)
        assert(Gtxn[txn_index].XferAsset == asset_id)
        assert(Gtxn[txn_index].AssetAmount >= minimum_amount)
    end
    return
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

