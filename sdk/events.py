from algosdk import abi

from sdk.event import Event  # TODO: This dependency is copied from sdk.


# Registry Events
entry_event = Event(
    name="entry",
    args=[
        abi.Argument(arg_type="address", name="user_address"),
        abi.Argument(arg_type="uint64", name="app_id")
    ]
)

set_order_fee_rate_event = Event(
    name="set_order_fee_rate",
    args=[
        abi.Argument(arg_type="uint64", name="fee_rate")
    ]
)

set_governor_order_fee_rate_event = Event(
    name="set_governor_order_fee_rate",
    args=[
        abi.Argument(arg_type="uint64", name="fee_rate")
    ]
)

set_governor_fee_rate_power_threshold_event = Event(
    name="set_governor_fee_rate_power_threshold",
    args=[
        abi.Argument(arg_type="uint64", name="threshold")
    ]
)

claim_fees = Event(
    name="claim_fees",
    args=[
        abi.Argument(arg_type="uint64", name="asset_id"),
        abi.Argument(arg_type="uint64", name="amount")
    ]
)

# Order Events
order_event = Event(
    name="order",
    args=[
        abi.Argument(arg_type="address", name="user_address"),
        abi.Argument(arg_type="uint64", name="order_id"),
        abi.Argument(arg_type="uint64", name="asset_id"),
        abi.Argument(arg_type="uint64", name="amount"),
        abi.Argument(arg_type="uint64", name="target_asset_id"),
        abi.Argument(arg_type="uint64", name="target_amount"),
        abi.Argument(arg_type="uint64", name="filled_amount"),
        abi.Argument(arg_type="uint64", name="collected_target_amount"),
        abi.Argument(arg_type="uint64", name="is_partial_allowed"),
        abi.Argument(arg_type="uint64", name="fee_rate"),
        abi.Argument(arg_type="uint64", name="creation_timestamp"),
        abi.Argument(arg_type="uint64", name="expiration_timestamp")
    ]
)


put_order_event = Event(
    name="put_order",
    args=[
        abi.Argument(arg_type="uint64", name="order_id"),
    ]
)


cancel_order_event = Event(
    name="cancel_order",
    args=[
        abi.Argument(arg_type="uint64", name="order_id"),
    ]
)


start_execute_order_event = Event(
    name="start_execute_order",
    args=[
        abi.Argument(arg_type="address", name="user_address"),
        abi.Argument(arg_type="uint64", name="order_id"),
        abi.Argument(arg_type="address", name="filler_address"),
    ]
)


end_execute_order_event = Event(
    name="end_execute_order",
    args=[
        abi.Argument(arg_type="address", name="user_address"),
        abi.Argument(arg_type="uint64", name="order_id"),
        abi.Argument(arg_type="address", name="filler_address"),
        abi.Argument(arg_type="uint64", name="fill_amount"),
        abi.Argument(arg_type="uint64", name="bought_amount"),
    ]
)


registry_events = [
    entry_event
]


ordering_events = [
    order_event,
    put_order_event,
    cancel_order_event,
    start_execute_order_event,
    end_execute_order_event
]