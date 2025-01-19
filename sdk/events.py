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
        abi.Argument(arg_type="uint64", name="is_partial_allowed"),
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


registry_events = [
    entry_event
]


ordering_events = [
    order_event,
    put_order_event,
    cancel_order_event
]