from base64 import b64decode, b64encode
from datetime import datetime, timezone

from algosdk.encoding import decode_address
from tinyman.utils import TransactionGroup, int_to_bytes
from algosdk import transaction
from algosdk.encoding import decode_address
from algosdk.logic import get_application_address

from sdk.base_client import BaseClient
from sdk.constants import *
from sdk.structs import Order, Entry

# TODO: Later change these dependencies with the hardcoded ones.
from tests.constants import order_approval_program, order_clear_state_program, order_app_global_schema, order_app_local_schema, order_app_extra_pages


class OrderingClient(BaseClient):
    def __init__(self, algod, registry_app_id, user_address, user_sk, order_app_id=None) -> None:
        self.algod = algod
        self.registry_app_id = registry_app_id
        self.registry_application_address = get_application_address(registry_app_id)
        self.app_id = order_app_id
        self.application_address = get_application_address(self.app_id) if self.app_id else None
        self.user_address = user_address
        self.keys = {}
        self.add_key(user_address, user_sk)
        self.current_timestamp = None
        self.simulate = False

    def get_registry_entry_box_name(self, user_address: str) -> bytes:
        return b"e" + decode_address(user_address)

    def create_order_app(self):
        sp = self.get_suggested_params()

        entry_box_name = self.get_registry_entry_box_name(self.user_address)
        new_boxes = {}
        if not self.box_exists(entry_box_name, self.registry_app_id):
            new_boxes[entry_box_name] = Entry

        transactions = [
            transaction.PaymentTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.registry_application_address,
                amt=self.calculate_min_balance(boxes=new_boxes)
            ) if new_boxes else None,
            transaction.ApplicationCreateTxn(
                sender=self.user_address,
                sp=sp,
                on_complete=transaction.OnComplete.NoOpOC,
                app_args=[b"create_application", self.registry_app_id, decode_address(self.registry_application_address)],
                approval_program=order_approval_program.bytecode,
                clear_program=order_clear_state_program.bytecode,
                global_schema=order_app_global_schema,
                local_schema=order_app_local_schema,
                extra_pages=order_app_extra_pages,
            ),
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.registry_app_id,
                app_args=["create_entry"],
                boxes=[
                    (0, entry_box_name),
                ],
            )
        ]

        return self._submit(transactions, additional_fees=0)

    def get_order_count(self):
        return self.get_global(TOTAL_ORDER_COUNT_KEY, 0, self.app_id)
    
    def get_order_box_name(self, id: int):
        return b"o" + int_to_bytes(id)

    def put_order(self, asset_id: int, amount: int, target_asset_id: int, target_amount: int, is_partial_allowed: bool, expiration_timestamp: int, order_id: int=None):
        sp = self.get_suggested_params()

        if order_id is None:
            order_id = self.get_order_count()

        order_box_name = self.get_order_box_name(order_id)
        new_boxes = {}
        if not self.box_exists(order_box_name, self.app_id):
            new_boxes[order_box_name] = Order

        transactions = [
            transaction.PaymentTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.application_address,
                amt=self.calculate_min_balance(boxes=new_boxes, assets=1)
            ) if new_boxes else None,
            # Asset Transfer
            transaction.PaymentTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.application_address,
                amt=amount
            ) if asset_id == 0 else
            transaction.AssetTransferTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.application_address,
                index=asset_id,
                amt=amount,
            ),
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=[
                    "put_order",
                    int_to_bytes(asset_id),
                    int_to_bytes(amount),
                    int_to_bytes(target_asset_id),
                    int_to_bytes(target_amount),
                    int_to_bytes(int(is_partial_allowed)),
                    int_to_bytes(expiration_timestamp)
                ],
                boxes=[
                    (0, order_box_name),
                ],
            )
        ]

        return self._submit(transactions, additional_fees=0)

    def cancel_order(self, order_id: int):
        sp = self.get_suggested_params()

        order_box_name = self.get_order_box_name(order_id)
        order = self.get_box(order_box_name, "Order")

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=[
                    "cancel_order",
                    int_to_bytes(order_id)
                ],
                boxes=[
                    (0, order_box_name),
                ],
                foreign_assets=[order.asset_id],
                foreign_apps=[self.registry_app_id]
            )
        ]

        return self._submit(transactions, additional_fees=1)

    def prepare_start_execute_order_transaction(self, order_id: int, fill_amount: int, index_diff: int, sp, account_address: str=None):
        order_box_name = self.get_order_box_name(order_id)
        order = self.get_box(order_box_name, "Order")

        txn = transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=[
                    "start_execute_order",
                    int_to_bytes(order_id),
                    int_to_bytes(fill_amount),
                    int_to_bytes(index_diff)
                ],
                boxes=[
                    (0, order_box_name),
                ],
                foreign_assets=[order.target_asset_id]
            )

        return txn

    def prepare_end_execute_order_transaction(self, order_id: int, fill_amount: int, index_diff: int, sp, account_address: str=None):
        order_box_name = self.get_order_box_name(order_id)
        order = self.get_box(order_box_name, "Order")

        txn = transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=[
                    "end_execute_order",
                    int_to_bytes(order_id),
                    int_to_bytes(fill_amount),
                    int_to_bytes(index_diff)
                ],
                boxes=[
                    (0, order_box_name),
                ],
                foreign_apps=[self.registry_app_id],
                foreign_assets=[order.asset_id]
            )

        return txn
