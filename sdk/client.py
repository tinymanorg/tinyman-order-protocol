from base64 import b64decode, b64encode
from datetime import datetime, timezone
from typing import List

from algosdk.encoding import decode_address
from algosdk import transaction
from algosdk.encoding import decode_address
from algosdk.logic import get_application_address
from tinyman.utils import TransactionGroup, int_to_bytes

from sdk.base_client import BaseClient
from sdk.constants import *
from sdk.structs import Order, Entry
from sdk.utils import int_array

# TODO: Later change these dependencies with the hardcoded ones.
from tests.constants import order_approval_program, order_clear_state_program, order_app_global_schema, order_app_local_schema, order_app_extra_pages


class OrderingClient(BaseClient):
    def __init__(self, algod, registry_app_id, vault_app_id, user_address, user_sk, order_app_id=None) -> None:
        self.algod = algod
        self.registry_app_id = registry_app_id
        self.registry_application_address = get_application_address(registry_app_id)
        self.vault_app_id = vault_app_id
        self.vault_application_address = get_application_address(vault_app_id)
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
                app_args=[b"create_application", self.registry_app_id, self.vault_app_id, decode_address(self.user_address)],
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
    
    def prepare_asset_opt_in_txn(self, asset_ids: List[int], sp):
        asset_ids = int_array(asset_ids, 8, 0)
        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["asset_opt_in", asset_ids],
            )
        ]
        return transactions

    def asset_opt_in(self, asset_ids: List[int]):
        sp = self.get_suggested_params()
        transactions = self.prepare_asset_opt_in_txn(asset_ids, sp)
        transactions.insert(
            0,
            transaction.PaymentTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.application_address,
                amt=self.calculate_min_balance(assets=len(asset_ids))
            ),
        )

        return self._submit(transactions, additional_fees=len(asset_ids))

    def get_order_count(self):
        return self.get_global(TOTAL_ORDER_COUNT_KEY, 0, self.app_id)

    def get_order_box_name(self, id: int):
        return b"o" + int_to_bytes(id)

    def get_recurring_order_box_name(self, id: int):
        return b"r" + int_to_bytes(id)

    def put_order(self, asset_id: int, amount: int, target_asset_id: int, target_amount: int, is_partial_allowed: bool, duration: int=0, order_id: int=None):
        sp = self.get_suggested_params()

        if order_id is None:
            order_id = self.get_order_count()

        order_box_name = self.get_order_box_name(order_id)
        new_boxes = {}
        if not self.box_exists(order_box_name, self.app_id):
            new_boxes[order_box_name] = Order

        assets_to_optin = [asset_id, target_asset_id]
        assets_to_optin = [aid for aid in assets_to_optin if not self.is_opted_in(self.application_address, aid)]

        transactions = [
            transaction.PaymentTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.application_address,
                amt=self.calculate_min_balance(boxes=new_boxes, assets=len(assets_to_optin))
            ) if new_boxes else None,
            self.prepare_asset_opt_in_txn(assets_to_optin, sp) if assets_to_optin else None,
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
                    int_to_bytes(duration)
                ],
                foreign_assets=[target_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.vault_app_id, decode_address(self.user_address))
                ],
            )
        ]

        return self._submit(transactions, additional_fees=1 + len(assets_to_optin))

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

    def prepare_start_execute_order_transaction(self, order_app_id: int, order_id: int, account_address: str, fill_amount: int, index_diff: int, sp) -> transaction.ApplicationCallTxn:
        """
        It is assumed that the caller of this method is a filler.

        Parameters
        ----------
        order_app_id : Id of the account's order app that will be filled.
        account_address : Account whom its order will be filled.
        """

        order_box_name = self.get_order_box_name(order_id)
        order = self.get_box(order_box_name, "Order", app_id=order_app_id)

        txn = transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=order_app_id,
                app_args=[
                    "start_execute_order",
                    int_to_bytes(order_id),
                    int_to_bytes(fill_amount),
                    int_to_bytes(index_diff)
                ],
                boxes=[
                    (0, order_box_name),
                ],
                accounts=[account_address],
                foreign_assets=[order.asset_id]
            )

        return txn

    def prepare_end_execute_order_transaction(self, order_app_id: int, order_id: int, account_address: str, fill_amount: int, index_diff: int, sp) -> transaction.ApplicationCallTxn:
        """
        It is assumed that the caller of this method is a filler.

        Parameters
        ----------
        order_app_id : Id of the account's order app that will be filled.
        account_address : Account whom its order will be filled.
        """

        order_box_name = self.get_order_box_name(order_id)
        order = self.get_box(order_box_name, "Order", app_id=order_app_id)

        txn = transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=order_app_id,
                app_args=[
                    "end_execute_order",
                    int_to_bytes(order_id),
                    int_to_bytes(fill_amount),
                    int_to_bytes(index_diff)
                ],
                boxes=[
                    (0, order_box_name)
                ],
                accounts=[account_address, self.registry_application_address],
                foreign_apps=[self.registry_app_id],
                foreign_assets=[order.target_asset_id]
            )

        return txn

    def collect(self, order_id: int):
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
                    "collect",
                    int_to_bytes(order_id)
                ],
                boxes=[
                    (0, order_box_name),
                ],
                foreign_assets=[order.target_asset_id],
                foreign_apps=[self.registry_app_id]
            )
        ]

        return self._submit(transactions, additional_fees=2)

    def put_recurring_order(self, asset_id: int, amount: int, target_asset_id: int, target_recurrence: int, interval: int, start_timestamp: int, duration: int, order_id: int=None):
        sp = self.get_suggested_params()

        if order_id is None:
            order_id = self.get_order_count()

        order_box_name = self.get_recurring_order_box_name(order_id)
        new_boxes = {}
        if not self.box_exists(order_box_name, self.app_id):
            new_boxes[order_box_name] = Order

        assets_to_optin = [asset_id, target_asset_id]
        assets_to_optin = [aid for aid in assets_to_optin if not self.is_opted_in(self.application_address, aid)]

        transactions = [
            transaction.PaymentTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.application_address,
                amt=self.calculate_min_balance(boxes=new_boxes, assets=len(assets_to_optin))
            ) if new_boxes else None,
            self.prepare_asset_opt_in_txn(assets_to_optin, sp) if assets_to_optin else None,
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
                    "put_recurring_order",
                    int_to_bytes(asset_id),
                    int_to_bytes(amount),
                    int_to_bytes(target_asset_id),
                    int_to_bytes(target_recurrence),
                    int_to_bytes(interval),
                    int_to_bytes(start_timestamp),
                    int_to_bytes(duration)
                ],
                foreign_assets=[target_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.vault_app_id, decode_address(self.user_address))
                ],
            )
        ]

        return self._submit(transactions, additional_fees=1 + len(assets_to_optin))

    def cancel_recurring_order(self, order_id: int):
        sp = self.get_suggested_params()

        order_box_name = self.get_recurring_order_box_name(order_id)
        order = self.get_box(order_box_name, "Order")

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=[
                    "cancel_recurring_order",
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

    def prepare_start_execute_recurring_order_transaction(self, order_app_id: int, order_id: int, account_address: str, fill_amount: int, index_diff: int, sp) -> transaction.ApplicationCallTxn:
        """
        It is assumed that the caller of this method is a filler.

        Parameters
        ----------
        order_app_id : Id of the account's order app that will be filled.
        account_address : Account whom its order will be filled.
        """

        order_box_name = self.get_recurring_order_box_name(order_id)
        order = self.get_box(order_box_name, "Order", app_id=order_app_id)

        txn = transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=order_app_id,
                app_args=[
                    "start_execute_recurring_order",
                    int_to_bytes(order_id),
                    int_to_bytes(fill_amount),
                    int_to_bytes(index_diff)
                ],
                boxes=[
                    (0, order_box_name),
                ],
                accounts=[account_address],
                foreign_assets=[order.asset_id]
            )

        return txn

    def prepare_end_execute_recurring_order_transaction(self, order_app_id: int, order_id: int, account_address: str, fill_amount: int, index_diff: int, sp) -> transaction.ApplicationCallTxn:
        """
        It is assumed that the caller of this method is a filler.

        Parameters
        ----------
        order_app_id : Id of the account's order app that will be filled.
        account_address : Account whom its order will be filled.
        """

        order_box_name = self.get_recurring_order_box_name(order_id)
        order = self.get_box(order_box_name, "Order", app_id=order_app_id)

        txn = transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=order_app_id,
                app_args=[
                    "end_execute_recurring_order",
                    int_to_bytes(order_id),
                    int_to_bytes(fill_amount),
                    int_to_bytes(index_diff)
                ],
                boxes=[
                    (0, order_box_name)
                ],
                accounts=[account_address, self.registry_application_address],
                foreign_apps=[self.registry_app_id],
                foreign_assets=[order.target_asset_id]
            )

        return txn

    def update_ordering_app(self, approval_program, clear_program):
        sp = self.get_suggested_params()

        transactions = [
            transaction.ApplicationUpdateTxn(
                sender=self.user_address,
                sp=sp,
                index=self.app_id,
                app_args=[b"update_application"],
                approval_program=approval_program,
                clear_program=clear_program,
            )
        ]

        return self._submit(transactions)

    def registry_user_opt_in(self):
        sp = self.get_suggested_params()

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.OptInOC,
                sp=sp,
                index=self.registry_app_id,
                app_args=["user_opt_in"]
            )
        ]

        return self._submit(transactions)


class RegistryClient(BaseClient):
    def __init__(self, algod, registry_app_id, vault_app_id, user_address, user_sk) -> None:
        self.algod = algod
        self.app_id = registry_app_id
        self.application_address = get_application_address(registry_app_id)
        self.vault_app_id = vault_app_id
        self.vault_application_address = get_application_address(vault_app_id)
        self.user_address = user_address
        self.keys = {}
        self.add_key(user_address, user_sk)
        self.current_timestamp = None
        self.simulate = False

    def get_registry_entry_box_name(self, user_address: str) -> bytes:
        return b"e" + decode_address(user_address)

    def propose_manager(self, new_manager_address):
        sp = self.get_suggested_params()

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["propose_manager", decode_address(new_manager_address)],
            )
        ]

        return self._submit(transactions)

    def accept_manager(self):
        sp = self.get_suggested_params()

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["accept_manager"],
            )
        ]

        return self._submit(transactions)

    def asset_opt_in(self, asset_id: int):
        sp = self.get_suggested_params()

        transactions = [
            transaction.PaymentTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.application_address,
                amt=self.calculate_min_balance(assets=1)
            ),
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["asset_opt_in", asset_id],
                foreign_assets=[asset_id]
            )
        ]

        return self._submit(transactions, additional_fees=1)
    
    def set_order_fee_rate(self, fee_rate: int):
        sp = self.get_suggested_params()

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["set_order_fee_rate", fee_rate],
            )
        ]

        return self._submit(transactions)
    
    def set_governor_order_fee_rate(self, fee_rate: int):
        sp = self.get_suggested_params()

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["set_governor_order_fee_rate", fee_rate],
            )
        ]

        return self._submit(transactions)

    def set_governor_fee_rate_power_threshold(self, threshold: int):
        sp = self.get_suggested_params()

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["set_governor_fee_rate_power_threshold", threshold],
            )
        ]

        return self._submit(transactions)

    def claim_fees(self, asset_id: int):
        sp = self.get_suggested_params()

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["claim_fees", asset_id],
                foreign_assets=[asset_id]
            )
        ]

        return self._submit(transactions, additional_fees=1)

    def endorse(self, user_address: str):
        sp = self.get_suggested_params()

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["endorse", decode_address(user_address)],
                accounts=[user_address]
            )
        ]

        return self._submit(transactions)

    def deendorse(self, user_address: str):
        sp = self.get_suggested_params()

        transactions = [
            transaction.ApplicationCallTxn(
                sender=self.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=["deendorse", decode_address(user_address)],
                accounts=[user_address]
            )
        ]

        return self._submit(transactions)
