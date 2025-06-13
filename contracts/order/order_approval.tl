#pragma version 10
#tealish version git+https://github.com/tinymanorg/tealish.git@109a2f2e74549307fb002298f4189df3f0ed7c4f

# Tinyman Order Protocol
# License: https://github.com/tinymanorg/tinyman-order-protocol/blob/main/LICENSE
# Documentation: https://docs.tinyman.org


# Name: o<id>
struct TriggerOrder:
    asset_id: int
    amount: int
    target_asset_id: int
    target_amount: int
    filled_amount: int
    collected_target_amount: int
    is_partial_allowed: int
    fee_rate: int
    creation_timestamp: int
    expiration_timestamp: int
end


# Name: r<id>
struct RecurringOrder:
    asset_id: int
    # `amount` is per recurrence
    amount: int
    target_asset_id: int
    collected_target_amount: int
    min_target_amount: int
    max_target_amount: int
    remaining_recurrences: int
    interval: int
    fee_rate: int
    last_fill_timestamp: int
    creation_timestamp: int
end


struct Address:
    address: bytes[32]
end


# Global State

const bytes REGISTRY_APP_ID_KEY = "registry_app_id"
const bytes REGISTRY_APP_ACCOUNT_ADDRESS_KEY = "registry_app_account_address"
const bytes VAULT_APP_ID_KEY = "vault_app_id"
const bytes ROUTER_APP_ID_KEY = "router_app_id"

const bytes USER_ADDRESS_KEY = "user_address"
const bytes TOTAL_ORDER_COUNT_KEY = "order_count"

const bytes ORDER_FEE_RATE_KEY = "order_fee_rate"

const bytes VERSION_KEY = "version"

# Global State External

const bytes ORDER_FEE_RATE_KEY = "order_fee_rate"
const bytes GOVERNOR_ORDER_FEE_RATE_KEY = "governor_order_fee_rate"
const bytes GOVERNOR_FEE_RATE_POWER_THRESHOLD = "governor_fee_rate_power_threshold"

# Local State External

const bytes IS_ENDORSED_KEY = "is_endorsed"

# Math Constants

const int RATE_SCALER = 18446744073709551615
const int MAX_UINT64 = 18446744073709551615
const int MINUTE = 60


# Versioning

# Update this value by one with each new version
const int VERSION = 3


router:
    create_application
    update_application
    post_update
    asset_opt_in
    put_trigger_order
    cancel_trigger_order
    start_execute_trigger_order
    end_execute_trigger_order
    put_recurring_order
    cancel_recurring_order
    execute_recurring_order
    collect
end


# Permission: anyone
@public(OnCompletion=CreateApplication)
func create_application(registry_app_id: int):
    app_global_put(USER_ADDRESS_KEY, Txn.Sender)

    app_global_put(REGISTRY_APP_ID_KEY, registry_app_id)
    bytes registry_app_account_address 
    _, registry_app_account_address = app_params_get(AppAddress, registry_app_id)
    app_global_put(REGISTRY_APP_ACCOUNT_ADDRESS_KEY, registry_app_account_address)

    int vault_app_id
    _, vault_app_id = app_global_get_ex(registry_app_id, VAULT_APP_ID_KEY)
    app_global_put(VAULT_APP_ID_KEY, vault_app_id)

    int router_app_id
    _, router_app_id = app_global_get_ex(registry_app_id, ROUTER_APP_ID_KEY)
    app_global_put(ROUTER_APP_ID_KEY, router_app_id)

    app_global_put(VERSION_KEY, VERSION)

    # create_application(user_address,registry_app_id,vault_app_id)
    log(ARC28Event("create_application(address,uint64,uint64)", Txn.Sender, itob(registry_app_id), itob(vault_app_id)))
    return
end


# Permission: user
@public(OnCompletion=UpdateApplication)
func update_application(version: int):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)

    # Gtxn +1 must be a call to verify_update on the registry app
    assert(Gtxn[+1].ApplicationID == app_global_get(REGISTRY_APP_ID_KEY))
    assert(Gtxn[+1].ApplicationArgs[0] == "verify_update")
    assert(Gtxn[+1].ApplicationArgs[1] == itob(version))

    # Gtxn +2 must be a call to post_update on this app
    assert(Gtxn[+2].ApplicationID == Global.CurrentApplicationID)
    assert(Gtxn[+2].ApplicationArgs[0] == "post_update")

    log(ARC28Event("update_application(address,uint64)", Txn.Sender, itob(version)))
    return
end


# Permission: user
@public()
func post_update():
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)

    # This will fail the update if the app is already at the same or higher version
    assert(VERSION > app_global_get(VERSION_KEY))

    # Update app ids to match registry
    int registry_app_id = app_global_get(REGISTRY_APP_ID_KEY)

    int vault_app_id
    _, vault_app_id = app_global_get_ex(registry_app_id, VAULT_APP_ID_KEY)
    app_global_put(VAULT_APP_ID_KEY, vault_app_id)

    int router_app_id
    _, router_app_id = app_global_get_ex(registry_app_id, ROUTER_APP_ID_KEY)
    app_global_put(ROUTER_APP_ID_KEY, router_app_id)

    # any version specific 'migrations' can be done here in future versions

    # Always update the version number in global state
    app_global_put(VERSION_KEY, VERSION)
    log(ARC28Event("post_update(uint64)", itob(VERSION)))
    return
end



@public()
func asset_opt_in(asset_ids: int[8]):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)

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
func put_trigger_order(asset_id: int, amount: int, target_asset_id: int, target_amount: int, is_partial_allowed: int, duration: int):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)

    int total_order_count = app_global_get(TOTAL_ORDER_COUNT_KEY)
    box<TriggerOrder> order = CreateBox(Concat("o", itob(total_order_count)))

    # Assertions
    assert(amount > 0)
    assert(target_amount > 0)
    assert(asset_id != target_asset_id)

    int expiration_timestamp
    if !duration:
        expiration_timestamp = MAX_UINT64
    else:
        expiration_timestamp = Global.LatestTimestamp + duration
    end

    if target_asset_id:
        int is_opted_in_to_target
        is_opted_in_to_target, _ = asset_holding_get(AssetBalance, Global.CurrentApplicationAddress, target_asset_id)
        assert(is_opted_in_to_target)
    end

    check_received_asset(Txn.GroupIndex - 1, Global.CurrentApplicationAddress, asset_id, amount)

    int fee_rate = get_fee_rate()

    order.asset_id = asset_id
    order.amount = amount
    order.target_asset_id = target_asset_id
    order.target_amount = target_amount
    order.filled_amount = 0
    order.collected_target_amount = 0
    order.is_partial_allowed = is_partial_allowed
    order.fee_rate = fee_rate
    order.creation_timestamp = Global.LatestTimestamp
    order.expiration_timestamp = expiration_timestamp

    app_global_put(TOTAL_ORDER_COUNT_KEY, total_order_count + 1)

    # Logs
    bytes order_data
    _, order_data = box_get(order)
    registry_emit_event("put_trigger_order", user_address, Concat(itob(total_order_count), order_data))
    log(ARC28Event("trigger_order(address,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", user_address, itob(total_order_count), order_data))
    log(ARC28Event("put_trigger_order(uint64)", itob(total_order_count)))

    return
end


# Description: Send the `amount` or `amount - filled_amount` if partially filled to the user. Delete the order box.
# Prerequisites: If partial filling is utilized, collect method must be called before.
# Permission: App owner (User)
@public()
func cancel_trigger_order(order_id: int):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)

    box<TriggerOrder> order = OpenBox(Concat("o", itob(order_id)))

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
    registry_emit_event("cancel_trigger_order", user_address, itob(order_id))
    log(ARC28Event("trigger_order(address,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", user_address, itob(order_id), order_data))
    log(ARC28Event("cancel_trigger_order(uint64)", itob(order_id)))

    # Delete the box.
    _ = box_del(order)

    return
end


func check_execute_order_txn(txn_index: int, method_name: bytes, order_id: int, fill_amount: int, index_diff: int):
    assert(Gtxn[txn_index].Sender == Txn.Sender)
    assert(Gtxn[txn_index].TypeEnum == Appl)
    assert(Gtxn[txn_index].OnCompletion == NoOp)
    assert(Gtxn[txn_index].ApplicationID == Global.CurrentApplicationID)
    assert(Gtxn[txn_index].ApplicationArgs[0] == method_name)
    assert(Gtxn[txn_index].ApplicationArgs[1] == itob(order_id))
    assert(Gtxn[txn_index].ApplicationArgs[2] == itob(fill_amount))
    assert(Gtxn[txn_index].ApplicationArgs[3] == itob(index_diff))
    return
end


# Description: Method allows an executor (taker) to do arbitrary operations between `Txn.GroupIndex < i < (Txn.GroupIndex + index_diff)`.
# An executor must call `end_execute_trigger_order` at the `Txn.GroupIndex + index_diff` for the transaction group to succeed.
# Permission: Everyone
@public()
func start_execute_trigger_order(order_id: int, fill_amount: int, index_diff: int):
    box<TriggerOrder> order = OpenBox(Concat("o", itob(order_id)))

    # Assertions
    assert(index_diff >= 2)

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
    check_execute_order_txn(end_execute_order_txn_index, "end_execute_trigger_order", order_id, fill_amount, index_diff)

    # Transfer `fill_amount` to executor.
    transfer(order.asset_id, fill_amount, Global.CurrentApplicationAddress, Txn.Sender)

    # Logs
    log(ARC28Event("start_execute_trigger_order(address,uint64,address)", app_global_get(USER_ADDRESS_KEY), itob(order_id), Txn.Sender))

    return
end


# Description: Method checks the validity of the execution between `start_execute_trigger_order` and `end_execute_trigger_order`.
# An executor must return the correct amount of `target_asset_id` via an axfer at `Txn.GroupIndex - 1`. Otherwise the transaction group fails.
# Permission: Everyone
@public()
func end_execute_trigger_order(order_id: int, fill_amount: int, index_diff: int):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    box<TriggerOrder> order = OpenBox(Concat("o", itob(order_id)))

    int start_execute_order_txn_index = Txn.GroupIndex - index_diff
    check_execute_order_txn(start_execute_order_txn_index, "start_execute_trigger_order", order_id, fill_amount, index_diff)

    # Assert that user received the target amount or more.
    int minimum_amount
    if !order.is_partial_allowed:
        minimum_amount = order.target_amount
    else:
        minimum_amount = calculate_minimum_amount(order.amount, order.target_amount, fill_amount)
    end

    int received_amount = check_received_target_asset(Txn.GroupIndex - 1, Global.CurrentApplicationAddress, order.target_asset_id, minimum_amount)

    order.filled_amount = order.filled_amount + fill_amount

    # Calculate the amount after feeing.
    int fee_amount = calculate_fee_amount(received_amount, order.fee_rate)
    assert(fee_amount)

    order.collected_target_amount = order.collected_target_amount + (received_amount - fee_amount)

    # Logs
    bytes order_data
    _, order_data = box_get(order)
    registry_emit_event("update_trigger_order", user_address, Concat(itob(order_id), order_data))
    log(ARC28Event("trigger_order(address,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", user_address, itob(order_id), order_data))
    log(ARC28Event("end_execute_trigger_order(address,uint64,address,uint64,uint64)", app_global_get(USER_ADDRESS_KEY), itob(order_id), Txn.Sender, itob(fill_amount), itob(received_amount)))

    # Transfers
    transfer(order.target_asset_id, fee_amount, Global.CurrentApplicationAddress, app_global_get(REGISTRY_APP_ACCOUNT_ADDRESS_KEY))

    int is_opted_in_to_target = 1
    if order.target_asset_id:
        is_opted_in_to_target, _ = asset_holding_get(AssetBalance, user_address, order.target_asset_id)
    end

    if (order.amount == order.filled_amount) && is_opted_in_to_target:
        transfer(order.target_asset_id, order.collected_target_amount, Global.CurrentApplicationAddress, user_address)
        _ = box_del(order)
    end

    return
end


# Description: Collect the accumulated amount for an order
# Permission: App owner (User)
@public()
func collect(order_id: int, order_type: bytes[1]):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)

    int target_asset_id
    int collected_target_amount

    if order_type == "o":
        box<TriggerOrder> order = OpenBox(Concat("o", itob(order_id)))
        target_asset_id = order.target_asset_id
        collected_target_amount = order.collected_target_amount

        order.collected_target_amount = 0

        bytes order_data
        _, order_data = box_get(order)
        log(ARC28Event("trigger_order(address,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", user_address, itob(order_id), order_data))

    elif order_type == "r":
        box<RecurringOrder> recurring_order = OpenBox(Concat("r", itob(order_id)))
        target_asset_id = recurring_order.target_asset_id
        collected_target_amount = recurring_order.collected_target_amount

        recurring_order.collected_target_amount = 0

        bytes recurring_order_data
        _, recurring_order_data = box_get(recurring_order)
        log(ARC28Event("recurring_order(address,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", user_address, itob(order_id), recurring_order_data))
    else:
        exit(1)
    end

    assert(collected_target_amount)

    transfer(target_asset_id, collected_target_amount, Global.CurrentApplicationAddress, user_address)

    # Logs
    log(ARC28Event("collect(uint64,uint64)", itob(order_id), itob(collected_target_amount)))

    return
end


# Description: Create a recurring order with the monotonically incremented ORDER_COUNT as id.
# Prerequisites: App should be opted into both `asset_id` and `target_asset_id`. Only `target_asset_id` optin checked explicitly.
# Permission: App owner (User)
@public()
func put_recurring_order(asset_id: int, amount: int, target_asset_id: int, min_target_amount: int, max_target_amount: int, target_recurrence: int, interval: int):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)

    int total_order_count = app_global_get(TOTAL_ORDER_COUNT_KEY)
    box<RecurringOrder> order = CreateBox(Concat("r", itob(total_order_count)))

    # Assertions
    assert(amount > 0)
    assert(asset_id != target_asset_id)
    assert(target_recurrence > 0)
    assert(interval >= MINUTE)
    # `interval` must be divisible by minute
    assert(!(interval % MINUTE))

    if !max_target_amount:
        max_target_amount = MAX_UINT64
    end
    assert(min_target_amount <= max_target_amount)

    # Optin to target asset if necessary
    if target_asset_id:
        int is_opted_in_to_target
        is_opted_in_to_target, _ = asset_holding_get(AssetBalance, Global.CurrentApplicationAddress, target_asset_id)
        assert(is_opted_in_to_target)
    end

    check_received_asset(Txn.GroupIndex - 1, Global.CurrentApplicationAddress, asset_id, (amount * target_recurrence))

    int fee_rate = get_fee_rate()

    order.asset_id = asset_id
    order.amount = amount
    order.target_asset_id = target_asset_id
    order.collected_target_amount = 0
    order.min_target_amount = min_target_amount
    order.max_target_amount = max_target_amount
    order.remaining_recurrences = target_recurrence
    order.interval = interval
    order.fee_rate = fee_rate
    order.last_fill_timestamp = 0
    order.creation_timestamp = Global.LatestTimestamp

    app_global_put(TOTAL_ORDER_COUNT_KEY, total_order_count + 1)

    # Logs
    bytes order_data
    _, order_data = box_get(order)
    registry_emit_event("put_recurring_order", user_address, Concat(itob(total_order_count), order_data))
    log(ARC28Event("recurring_order(address,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", user_address, itob(total_order_count), order_data))
    log(ARC28Event("put_recurring_order(uint64)", itob(total_order_count)))

    return
end


# Description: Send the `amount` (or `amount - filled_amount` if partially filled) to the user. Delete the order box.
# Prerequisites: If the order is partially filled, the collect method must be called before cancelling.
# Permission: App owner (User)
@public()
func cancel_recurring_order(order_id: int):
    bytes user_address = app_global_get(USER_ADDRESS_KEY)
    assert(Txn.Sender == user_address)

    box<RecurringOrder> order = OpenBox(Concat("r", itob(order_id)))

    # Ensure there is no remaining amount to be collected
    assert(!order.collected_target_amount)

    # It is assumed that the order is deleted once it is executed
    # Send remaining amount back to user
    int remaining_amount = order.amount * order.remaining_recurrences

    transfer(order.asset_id, remaining_amount, Global.CurrentApplicationAddress, user_address)

    # Logs
    bytes order_data
    _, order_data = box_get(order)
    registry_emit_event("cancel_recurring_order", user_address, itob(order_id))
    log(ARC28Event("recurring_order(address,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", user_address, itob(order_id), order_data))
    log(ARC28Event("cancel_recurring_order(uint64)", itob(order_id)))

    # Delete the box
    _ = box_del(order)

    return
end


# Description: Method allows an authorised filler to execute a recurring order using the Tinyman Router
# Permission: Filler
@public()
func execute_recurring_order(order_id: int, route: int[8], pools: Address[8], swaps: int):
    box<RecurringOrder> order = OpenBox(Concat("r", itob(order_id)))
    bytes user_address = app_global_get(USER_ADDRESS_KEY)

    # Assert this txn is not in an atomic sandwich
    assert(Txn.GroupIndex == 0)
    assert(Global.CallerApplicationID == 0)

    # Assert that Txn.Sender is allowed to fill recurring orders.
    check_is_endorsed(Txn.Sender)

    assert(Global.LatestTimestamp >= (order.last_fill_timestamp + order.interval))

    # Validate the supplied route
    assert(route[0] == order.asset_id)
    assert(route[swaps] == order.target_asset_id)

    # Swap through the Tinyman Router using the supplied route
    int received_amount = do_router_swap(order.amount, order.min_target_amount, route, pools, swaps)

    # Assert that the received amount is within expected range.
    assert((received_amount >= order.min_target_amount) && (received_amount <= order.max_target_amount))

    # Calculate the amount after fees.
    int fee_amount = calculate_fee_amount(received_amount, order.fee_rate)
    assert(fee_amount)

    # Update order
    order.remaining_recurrences = order.remaining_recurrences - 1
    order.last_fill_timestamp = Global.LatestTimestamp
    order.collected_target_amount = order.collected_target_amount + (received_amount - fee_amount)

    # Logs
    bytes order_data
    _, order_data = box_get(order)
    registry_emit_event("update_recurring_order", user_address, Concat(itob(order_id), order_data))
    log(ARC28Event("recurring_order(address,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64)", user_address, itob(order_id), order_data))
    log(ARC28Event("execute_recurring_order(address,uint64,address,uint64,uint64)", user_address, itob(order_id), Txn.Sender, itob(order.amount), itob(received_amount)))

    # Transfer fee to registry app account
    transfer(order.target_asset_id, fee_amount, Global.CurrentApplicationAddress, app_global_get(REGISTRY_APP_ACCOUNT_ADDRESS_KEY))

    int is_opted_in_to_target = 1
    if order.target_asset_id:
        is_opted_in_to_target, _ = asset_holding_get(AssetBalance, user_address, order.target_asset_id)
    end

    # If no more recurrences, transfer accumulated amount to the user address and close the order
    if !order.remaining_recurrences && is_opted_in_to_target:
        transfer(order.target_asset_id, order.collected_target_amount, Global.CurrentApplicationAddress, user_address)
        _ = box_del(order)
    end

    return
end


func do_router_swap(input_amount: int, output_amount: int, route: int[8], pools: Address[8], swaps: int) int:
    bytes router_app_address
    _, router_app_address = app_params_get(AppAddress, app_global_get(ROUTER_APP_ID_KEY))
    int output_asset_id = route[swaps]
    int initial_balance = get_balance(Global.CurrentApplicationAddress, output_asset_id)
    inner_group:
        transfer(route[0], input_amount, Global.CurrentApplicationAddress, router_app_address)
        inner_txn:
            TypeEnum: Appl
            Fee: 0
            ApplicationID: app_global_get(ROUTER_APP_ID_KEY)
            ApplicationArgs[0]: "swap"
            ApplicationArgs[1]: itob(input_amount)
            ApplicationArgs[2]: itob(output_amount)
            ApplicationArgs[3]: route
            ApplicationArgs[4]: pools
            ApplicationArgs[5]: itob(swaps)
        end
    end
    int received_amount = get_balance(Global.CurrentApplicationAddress, output_asset_id) - initial_balance
    return received_amount
end


func check_is_endorsed(user_address: bytes[32]):
    int is_endorsed

    _, is_endorsed = app_local_get_ex(user_address, app_global_get(REGISTRY_APP_ID_KEY), IS_ENDORSED_KEY)
    assert(is_endorsed)

    return
end


func calculate_minimum_amount(amount: int, target_amount: int, fill_amount: int) int:
    bytes target_rate = (itob(target_amount) b* itob(RATE_SCALER)) b/ itob(amount)
    int minimum_amount = btoi((itob(fill_amount) b* target_rate) b/ itob(RATE_SCALER))
    return minimum_amount
end


func calculate_fee_amount(target_amount: int, fee_rate: int) int:
    int fee_amount = btoi((itob(target_amount) b* itob(fee_rate)) b/ itob(10000))
    return fee_amount
end


func get_fee_rate() int:
    bytes threshold_bytes
    bytes fee_rate_bytes
    int fee_rate

    int account_voting_power = get_account_voting_power(UncheckedCast(app_global_get(USER_ADDRESS_KEY), bytes))
    _, threshold_bytes = app_global_get_ex(app_global_get(REGISTRY_APP_ID_KEY), GOVERNOR_FEE_RATE_POWER_THRESHOLD)
    int fee_rate_power_threshold = UncheckedCast(threshold_bytes, int)

    if account_voting_power > fee_rate_power_threshold:
        _, fee_rate_bytes = app_global_get_ex(app_global_get(REGISTRY_APP_ID_KEY), GOVERNOR_ORDER_FEE_RATE_KEY)
    else:
        _, fee_rate_bytes = app_global_get_ex(app_global_get(REGISTRY_APP_ID_KEY), ORDER_FEE_RATE_KEY)
    end

    fee_rate = UncheckedCast(fee_rate_bytes, int)
    return fee_rate
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


func registry_emit_event(event_name: bytes, user_address: bytes, data: bytes):
    inner_txn:
        TypeEnum: Appl
        Fee: 0
        ApplicationID: app_global_get(REGISTRY_APP_ID_KEY)
        ApplicationArgs[0]: "emit_event"
        ApplicationArgs[1]: event_name
        ApplicationArgs[2]: user_address
        ApplicationArgs[3]: data
    end
    return
end


func get_balance(account_address: bytes, asset_id: int) int:
    int balance = 0
    if !asset_id:
        balance = balance(account_address) - min_balance(account_address)
    else:
        _, balance = asset_holding_get(AssetBalance, account_address, asset_id)
    end
    return balance
end
