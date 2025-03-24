from datetime import datetime, timezone
from random import randint

from algojig.exceptions import LogicEvalError
from algosdk import transaction
from algosdk.account import generate_account
from algosdk.encoding import decode_address, encode_address
from algosdk.transaction import OnComplete

from tinyman.utils import TransactionGroup

from sdk.constants import *
from sdk.client import OrderingClient
from sdk.event import decode_logs
from sdk.events import ordering_events, registry_events
from sdk.structs import Order

from tests.constants import order_app_extra_pages, order_app_global_schema, order_app_local_schema, WEEK, DAY
from tests.core import OrderProtocolBaseTestCase


class OrderProtocolTests(OrderProtocolBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e14))

    def test_create_order_app(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create Entry
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.create_order_app()

        block = self.ledger.last_block
        block_txns = block[b'txns']
        create_order_app_txn = block_txns[1]
        create_entry_txn = block_txns[2]

        order_app_id = create_order_app_txn[b'apid']

        events = decode_logs(create_entry_txn[b'dt'][b'lg'], registry_events)
        entry_event = events[0]

        self.assertEqual(entry_event['user_address'], self.user_address)
        self.assertEqual(entry_event['app_id'], order_app_id)

        self.assertDictEqual(
            self.ledger.global_states[order_app_id],
            {
                USER_ADDRESS_KEY: decode_address(self.user_address),
                MANAGER_KEY: decode_address(self.user_address),
                REGISTRY_APP_ID_KEY: self.registry_app_id,
                REGISTRY_APP_ACCOUNT_ADDRESS_KEY: decode_address(self.register_application_address),
                VAULT_APP_ID_KEY: self.vault_app_id,
            }
        )


class PutOrderTests(OrderProtocolBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e14))

    def test_put_order_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=False,
            duration=4 * WEEK
        )

        block = self.ledger.last_block
        block_txns = block[b'txns']
        axfer_txn = block_txns[2]
        put_order_txn = block_txns[3]

        events = decode_logs(put_order_txn[b'dt'][b'lg'], ordering_events)
        order_event = events[0]
        put_order_event = events[1]

        self.assertEqual(order_event['user_address'], self.user_address)
        self.assertEqual(order_event['order_id'], 0)
        self.assertEqual(order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(order_event['amount'], 100_000)
        self.assertEqual(order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(order_event['target_amount'], 15_000)
        self.assertEqual(order_event['filled_amount'], 0)
        self.assertEqual(order_event['collected_target_amount'], 0)
        self.assertEqual(order_event['is_partial_allowed'], 0)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(put_order_event['order_id'], 0)

        order = self.ordering_client.get_box(self.ordering_client.get_order_box_name(0), "Order")
        self.assertEqual(order.asset_id, self.talgo_asset_id)
        self.assertEqual(order.amount, 100_000)
        self.assertEqual(order.target_asset_id, self.tiny_asset_id)
        self.assertEqual(order.target_amount, 15_000)
        self.assertEqual(order.filled_amount, 0)
        self.assertEqual(order.collected_target_amount, 0)
        self.assertEqual(order.is_partial_allowed, 0)
        self.assertEqual(order.fee_rate, 30)
        self.assertEqual(order.creation_timestamp, now + DAY)
        self.assertEqual(order.expiration_timestamp, now + DAY + 4 * WEEK)

    def test_put_order_partial_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=True,
            duration=4 * WEEK
        )

        block = self.ledger.last_block
        block_txns = block[b'txns']
        axfer_txn = block_txns[2]
        put_order_txn = block_txns[3]

        events = decode_logs(put_order_txn[b'dt'][b'lg'], ordering_events)
        order_event = events[0]
        put_order_event = events[1]

        self.assertEqual(order_event['user_address'], self.user_address)
        self.assertEqual(order_event['order_id'], 0)
        self.assertEqual(order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(order_event['amount'], 100_000)
        self.assertEqual(order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(order_event['target_amount'], 15_000)
        self.assertEqual(order_event['filled_amount'], 0)
        self.assertEqual(order_event['collected_target_amount'], 0)
        self.assertEqual(order_event['is_partial_allowed'], 1)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(put_order_event['order_id'], 0)

        order = self.ordering_client.get_box(self.ordering_client.get_order_box_name(0), "Order")
        self.assertEqual(order.asset_id, self.talgo_asset_id)
        self.assertEqual(order.amount, 100_000)
        self.assertEqual(order.target_asset_id, self.tiny_asset_id)
        self.assertEqual(order.target_amount, 15_000)
        self.assertEqual(order.filled_amount, 0)
        self.assertEqual(order.collected_target_amount, 0)
        self.assertEqual(order.is_partial_allowed, 1)
        self.assertEqual(order.fee_rate, 30)
        self.assertEqual(order.creation_timestamp, now + DAY)
        self.assertEqual(order.expiration_timestamp, now + DAY + 4 * WEEK)

    def test_put_order_insufficient_axfer(self):
        pass

    def test_put_order_expired_fail(self):
        pass

    def test_put_order_non_user_fail(self):
        pass

    def test_put_order_target_same_fail(self):
        pass

    def test_put_order_zero_amount_fail(self):
        pass

    def test_put_order_zero_target_amount_fail(self):
        pass


class CancelOrderTests(OrderProtocolBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e14))

    def test_cancel_order_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=False,
            duration=4 * WEEK
        )

        # Cancel Order
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.cancel_order(0)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        cancel_order_txn = block_txns[0]

        events = decode_logs(cancel_order_txn[b'dt'][b'lg'], ordering_events)
        order_event = events[0]
        cancel_order_event = events[1]

        self.assertEqual(order_event['user_address'], self.user_address)
        self.assertEqual(order_event['order_id'], 0)
        self.assertEqual(order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(order_event['amount'], 100_000)
        self.assertEqual(order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(order_event['target_amount'], 15_000)
        self.assertEqual(order_event['filled_amount'], 0)
        self.assertEqual(order_event['collected_target_amount'], 0)
        self.assertEqual(order_event['is_partial_allowed'], 0)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(cancel_order_event['order_id'], 0)

        # Inner Transaction Checks
        inner_txns = cancel_order_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 1)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 100_000)

    def test_cancel_order_partial_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=True,
            duration=4 * WEEK
        )

        # Mock partial filling.
        filled_amount = 10_000
        order_box_name = self.ordering_client.get_order_box_name(0)
        order = Order(bytearray(self.ordering_client.get_box(order_box_name, "Order")._data))
        order.filled_amount = filled_amount
        self.ledger.set_box(self.ordering_client.app_id, key=order_box_name, value=order._data)

        # Cancel Order
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.cancel_order(0)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        cancel_order_txn = block_txns[0]

        events = decode_logs(cancel_order_txn[b'dt'][b'lg'], ordering_events)
        order_event = events[0]
        cancel_order_event = events[1]

        self.assertEqual(order_event['user_address'], self.user_address)
        self.assertEqual(order_event['order_id'], 0)
        self.assertEqual(order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(order_event['amount'], 100_000)
        self.assertEqual(order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(order_event['target_amount'], 15_000)
        self.assertEqual(order_event['filled_amount'], 10_000)
        self.assertEqual(order_event['collected_target_amount'], 0)
        self.assertEqual(order_event['is_partial_allowed'], 1)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(cancel_order_event['order_id'], 0)

        # Inner Transaction Checks
        inner_txns = cancel_order_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 1)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 90_000)

    def test_cancel_order_partial_filled_fail(self):
        pass

    def test_cancel_order_non_user_fail(self):
        pass


class ExecuteOrderTests(OrderProtocolBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e14))

    def test_execute_order_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=False,
            duration=4 * WEEK
        )

        # Execute Order
        # Simulate Swap by sending the `target_amount` from filler account.
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=100_000,
                index_diff=2,
                sp=sp
            ),
            transaction.AssetTransferTxn(
                sender=filler_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=15_000,
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=100_000,
                index_diff=2,
                sp=sp
            ),
        ]

        self.ledger.next_timestamp = now + DAY + 1
        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.
        filler_client._submit(transactions, additional_fees=3)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        start_execute_txn = block_txns[0]
        end_execute_txn = block_txns[2]

        events = decode_logs(start_execute_txn[b'dt'][b'lg'], ordering_events)
        self.assertEqual(len(events), 1)
        start_execute_order_event = events[0]

        self.assertEqual(start_execute_order_event['order_id'], 0)
        self.assertEqual(start_execute_order_event['filler_address'], filler_client.user_address)

        events = decode_logs(end_execute_txn[b'dt'][b'lg'], ordering_events)
        self.assertEqual(len(events), 2)
        order_event = events[0]
        end_execute_order_event = events[1]

        self.assertEqual(order_event['user_address'], self.user_address)
        self.assertEqual(order_event['order_id'], 0)
        self.assertEqual(order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(order_event['amount'], 100_000)
        self.assertEqual(order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(order_event['target_amount'], 15_000)
        self.assertEqual(order_event['filled_amount'], 100_000)
        self.assertEqual(order_event['collected_target_amount'], 15_000)
        self.assertEqual(order_event['is_partial_allowed'], 0)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(end_execute_order_event['user_address'], self.user_address)
        self.assertEqual(end_execute_order_event['order_id'], 0)
        self.assertEqual(end_execute_order_event['filler_address'], filler_client.user_address)
        self.assertEqual(end_execute_order_event['fill_amount'], 100_000)
        self.assertEqual(end_execute_order_event['bought_amount'], 15_000)

        inner_txns = start_execute_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 1)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(filler_client.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 100_000)

        inner_txns = end_execute_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 2)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 15_000 - ((15_000 * 30) // 10_000))

        self.assertEqual(inner_txns[1][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[1][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[1][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'arcv'], decode_address(self.ordering_client.registry_application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'aamt'], ((15_000 * 30) // 10_000))

    def test_execute_order_partial_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=True,
            duration=4 * WEEK
        )

        # Execute Order
        # Simulate Swap by sending the `target_amount` from filler account.
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        fill_amount = 50_000
        bought_target_amount = (15_000 // 2)
        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
            transaction.AssetTransferTxn(
                sender=filler_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=bought_target_amount,
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
        ]

        self.ledger.next_timestamp = now + DAY + 1
        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.
        filler_client._submit(transactions, additional_fees=3)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        start_execute_txn = block_txns[0]
        end_execute_txn = block_txns[2]

        events = decode_logs(start_execute_txn[b'dt'][b'lg'], ordering_events)
        self.assertEqual(len(events), 1)
        start_execute_order_event = events[0]

        self.assertEqual(start_execute_order_event['order_id'], 0)
        self.assertEqual(start_execute_order_event['filler_address'], filler_client.user_address)

        events = decode_logs(end_execute_txn[b'dt'][b'lg'], ordering_events)
        self.assertEqual(len(events), 2)
        order_event = events[0]
        end_execute_order_event = events[1]

        self.assertEqual(order_event['user_address'], self.user_address)
        self.assertEqual(order_event['order_id'], 0)
        self.assertEqual(order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(order_event['amount'], 100_000)
        self.assertEqual(order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(order_event['target_amount'], 15_000)
        self.assertEqual(order_event['filled_amount'], fill_amount)
        self.assertEqual(order_event['collected_target_amount'], bought_target_amount)
        self.assertEqual(order_event['is_partial_allowed'], 1)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(end_execute_order_event['user_address'], self.user_address)
        self.assertEqual(end_execute_order_event['order_id'], 0)
        self.assertEqual(end_execute_order_event['filler_address'], filler_client.user_address)
        self.assertEqual(end_execute_order_event['fill_amount'], fill_amount)
        self.assertEqual(end_execute_order_event['bought_amount'], bought_target_amount)

        order = self.ordering_client.get_box(self.ordering_client.get_order_box_name(0), "Order")
        self.assertEqual(order.asset_id, self.talgo_asset_id)
        self.assertEqual(order.amount, 100_000)
        self.assertEqual(order.target_asset_id, self.tiny_asset_id)
        self.assertEqual(order.target_amount, 15_000)
        self.assertEqual(order.filled_amount, fill_amount)
        self.assertEqual(order.collected_target_amount, bought_target_amount)
        self.assertEqual(order.is_partial_allowed, 1)
        self.assertEqual(order.fee_rate, 30)
        self.assertEqual(order.creation_timestamp, now + DAY)
        self.assertEqual(order.expiration_timestamp, now + DAY + 4 * WEEK)

        inner_txns = start_execute_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 1)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(filler_client.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], fill_amount)

        # Since all amount is not filled,
        self.assertIsNone(end_execute_txn[b'dt'].get(b'itx'))

    def test_execute_order_partial_subsequent_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=True,
            duration=4 * WEEK
        )

        # Modify the order as if it is partially filled before.
        order_box_name = self.ordering_client.get_order_box_name(0)
        order = Order(bytearray(self.ordering_client.get_box(order_box_name, "Order")._data))
        order.filled_amount = 50_000
        order.collected_target_amount = (15_000 // 2)
        self.ledger.set_box(self.ordering_client.app_id, key=order_box_name, value=order._data)

        # Modify the order app balance.
        self.ledger.set_account_balance(self.ordering_client.application_address, 50_000, self.talgo_asset_id)
        self.ledger.set_account_balance(self.ordering_client.application_address, (15_000 // 2), self.tiny_asset_id)

        # Execute Order
        # Simulate Swap by sending the `target_amount` from filler account.
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        fill_amount = 50_000
        bought_target_amount = (15_000 // 2)
        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
            transaction.AssetTransferTxn(
                sender=filler_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=bought_target_amount,
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
        ]

        self.ledger.next_timestamp = now + DAY + 1
        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.
        filler_client._submit(transactions, additional_fees=3)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        start_execute_txn = block_txns[0]
        end_execute_txn = block_txns[2]

        events = decode_logs(start_execute_txn[b'dt'][b'lg'], ordering_events)
        self.assertEqual(len(events), 1)
        start_execute_order_event = events[0]

        self.assertEqual(start_execute_order_event['order_id'], 0)
        self.assertEqual(start_execute_order_event['filler_address'], filler_client.user_address)

        events = decode_logs(end_execute_txn[b'dt'][b'lg'], ordering_events)
        self.assertEqual(len(events), 2)
        order_event = events[0]
        end_execute_order_event = events[1]

        self.assertEqual(order_event['user_address'], self.user_address)
        self.assertEqual(order_event['order_id'], 0)
        self.assertEqual(order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(order_event['amount'], 100_000)
        self.assertEqual(order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(order_event['target_amount'], 15_000)
        self.assertEqual(order_event['filled_amount'], 100_000)
        self.assertEqual(order_event['collected_target_amount'], 15_000)
        self.assertEqual(order_event['is_partial_allowed'], 1)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(end_execute_order_event['user_address'], self.user_address)
        self.assertEqual(end_execute_order_event['order_id'], 0)
        self.assertEqual(end_execute_order_event['filler_address'], filler_client.user_address)
        self.assertEqual(end_execute_order_event['fill_amount'], fill_amount)
        self.assertEqual(end_execute_order_event['bought_amount'], bought_target_amount)

        inner_txns = start_execute_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 1)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(filler_client.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], fill_amount)

        # Since all amount is filled, target_amount must be sent to user and fee amount must be sent to registry.
        inner_txns = end_execute_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 2)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 15_000 - ((15_000 * 30) // 10_000))

        self.assertEqual(inner_txns[1][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[1][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[1][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'arcv'], decode_address(self.ordering_client.registry_application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'aamt'], ((15_000 * 30) // 10_000))


class PutRecurringOrderTests(OrderProtocolBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e14))

    def test_put_recurring_order_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            interval=interval,
            start_timestamp=0,
            duration=4 * WEEK
        )

        block = self.ledger.last_block
        block_txns = block[b'txns']
        axfer_txn = block_txns[2]
        put_recurring_order_txn = block_txns[3]

        events = decode_logs(put_recurring_order_txn[b'dt'][b'lg'], ordering_events)
        recurring_order_event = events[0]
        put_recurring_order_event = events[1]

        self.assertEqual(recurring_order_event['user_address'], self.user_address)
        self.assertEqual(recurring_order_event['order_id'], 0)
        self.assertEqual(recurring_order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(recurring_order_event['amount'], 100_000)
        self.assertEqual(recurring_order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(recurring_order_event['filled_amount'], 0)
        self.assertEqual(recurring_order_event['collected_target_amount'], 0)
        self.assertEqual(recurring_order_event['target_recurrence'], target_recurrence)
        self.assertEqual(recurring_order_event['filled_recurrence'], 0)
        self.assertEqual(recurring_order_event['interval'], interval)
        self.assertEqual(recurring_order_event['fee_rate'], 30)
        self.assertEqual(recurring_order_event['start_timestamp'], now + DAY)
        self.assertEqual(recurring_order_event['creation_timestamp'], now + DAY)
        self.assertEqual(recurring_order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(put_recurring_order_event['order_id'], 0)

        recurring_order = self.ordering_client.get_box(self.ordering_client.get_recurring_order_box_name(0), "RecurringOrder")
        self.assertEqual(recurring_order.asset_id, self.talgo_asset_id)
        self.assertEqual(recurring_order.amount, 100_000)
        self.assertEqual(recurring_order.target_asset_id, self.tiny_asset_id)
        self.assertEqual(recurring_order.filled_amount, 0)
        self.assertEqual(recurring_order.collected_target_amount, 0)
        self.assertEqual(recurring_order.target_recurrence, target_recurrence)
        self.assertEqual(recurring_order.filled_recurrence, 0)
        self.assertEqual(recurring_order.interval, interval)
        self.assertEqual(recurring_order.fee_rate, 30)
        self.assertEqual(recurring_order.start_timestamp, now + DAY)
        self.assertEqual(recurring_order.creation_timestamp, now + DAY)
        self.assertEqual(recurring_order.expiration_timestamp, now + DAY + 4 * WEEK)


class CancelRecurringOrderTests(OrderProtocolBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e14))

    def test_cancel_order_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            interval=interval,
            start_timestamp=0,
            duration=4 * WEEK
        )

        # Cancel Order
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.cancel_recurring_order(0)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        cancel_recurring_order_txn = block_txns[0]

        events = decode_logs(cancel_recurring_order_txn[b'dt'][b'lg'], ordering_events)
        recurring_order_event = events[0]
        cancel_recurring_order_event = events[1]

        self.assertEqual(recurring_order_event['user_address'], self.user_address)
        self.assertEqual(recurring_order_event['order_id'], 0)
        self.assertEqual(recurring_order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(recurring_order_event['amount'], 100_000)
        self.assertEqual(recurring_order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(recurring_order_event['filled_amount'], 0)
        self.assertEqual(recurring_order_event['collected_target_amount'], 0)
        self.assertEqual(recurring_order_event['target_recurrence'], target_recurrence)
        self.assertEqual(recurring_order_event['filled_recurrence'], 0)
        self.assertEqual(recurring_order_event['interval'], interval)
        self.assertEqual(recurring_order_event['fee_rate'], 30)
        self.assertEqual(recurring_order_event['start_timestamp'], now + DAY)
        self.assertEqual(recurring_order_event['creation_timestamp'], now + DAY)
        self.assertEqual(recurring_order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(cancel_recurring_order_event['order_id'], 0)

        # Inner Transaction Checks
        inner_txns = cancel_recurring_order_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 1)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 100_000)


class ExecuteRecurringOrderTests(OrderProtocolBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e14))

    def test_execute_order_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)
        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            interval=interval,
            start_timestamp=0,
            duration=4 * WEEK
        )

        # Execute Recurring Order
        # Simulate Swap by sending the `target_amount` from filler account.
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        self.ledger.next_timestamp = now + DAY + 1
        filler_client.registry_user_opt_in()

        self.ledger.next_timestamp = now + DAY + 2
        self.manager_client.endorse(filler_client.user_address)

        fill_amount = 100_000 // target_recurrence
        bought_target_amount = 15_000
        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_recurring_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
            transaction.AssetTransferTxn(
                sender=filler_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=bought_target_amount,
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_recurring_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
        ]

        self.ledger.next_timestamp = now + DAY + DAY
        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.
        filler_client._submit(transactions, additional_fees=3)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        start_execute_txn = block_txns[0]
        end_execute_txn = block_txns[2]

        events = decode_logs(start_execute_txn[b'dt'][b'lg'], ordering_events)

        self.assertEqual(len(events), 1)
        start_execute_order_event = events[0]

        self.assertEqual(start_execute_order_event['order_id'], 0)
        self.assertEqual(start_execute_order_event['filler_address'], filler_client.user_address)

        events = decode_logs(end_execute_txn[b'dt'][b'lg'], ordering_events)
        self.assertEqual(len(events), 2)
        recurring_order_event = events[0]
        end_execute_order_event = events[1]

        self.assertEqual(recurring_order_event['user_address'], self.user_address)
        self.assertEqual(recurring_order_event['order_id'], 0)
        self.assertEqual(recurring_order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(recurring_order_event['amount'], 100_000)
        self.assertEqual(recurring_order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(recurring_order_event['filled_amount'], fill_amount)
        self.assertEqual(recurring_order_event['collected_target_amount'], bought_target_amount)
        self.assertEqual(recurring_order_event['target_recurrence'], target_recurrence)
        self.assertEqual(recurring_order_event['filled_recurrence'], 1)
        self.assertEqual(recurring_order_event['interval'], interval)
        self.assertEqual(recurring_order_event['fee_rate'], 30)
        self.assertEqual(recurring_order_event['start_timestamp'], now + DAY)
        self.assertEqual(recurring_order_event['creation_timestamp'], now + DAY)
        self.assertEqual(recurring_order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(end_execute_order_event['user_address'], self.user_address)
        self.assertEqual(end_execute_order_event['order_id'], 0)
        self.assertEqual(end_execute_order_event['filler_address'], filler_client.user_address)
        self.assertEqual(end_execute_order_event['fill_amount'], fill_amount)
        self.assertEqual(end_execute_order_event['bought_amount'], bought_target_amount)

        recurring_order = self.ordering_client.get_box(self.ordering_client.get_recurring_order_box_name(0), "RecurringOrder")
        self.assertEqual(recurring_order.asset_id, self.talgo_asset_id)
        self.assertEqual(recurring_order.amount, 100_000)
        self.assertEqual(recurring_order.target_asset_id, self.tiny_asset_id)
        self.assertEqual(recurring_order.filled_amount, fill_amount)
        self.assertEqual(recurring_order.collected_target_amount, bought_target_amount)
        self.assertEqual(recurring_order.target_recurrence, target_recurrence)
        self.assertEqual(recurring_order.filled_recurrence, 1)
        self.assertEqual(recurring_order.interval, interval)
        self.assertEqual(recurring_order.fee_rate, 30)
        self.assertEqual(recurring_order.start_timestamp, now + DAY)
        self.assertEqual(recurring_order.creation_timestamp, now + DAY)
        self.assertEqual(recurring_order.expiration_timestamp, now + DAY + 4 * WEEK)

    def test_execute_recurring_order_noendorse_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)
        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            interval=interval,
            start_timestamp=0,
            duration=4 * WEEK
        )

        # Execute Recurring Order
        # Simulate Swap by sending the `target_amount` from filler account.
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        fill_amount = 100_000 // target_recurrence
        bought_target_amount = 15_000
        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_recurring_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
            transaction.AssetTransferTxn(
                sender=filler_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=bought_target_amount,
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_recurring_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
        ]

        self.ledger.next_timestamp = now + DAY + DAY
        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.

        with self.assertRaises(LogicEvalError) as e:
            filler_client._submit(transactions, additional_fees=3)
        self.assertEqual(e.exception.source['line'], 'exists, is_endorsed_bytes = app_local_get_ex(user_address, app_global_get(REGISTRY_APP_ID_KEY), IS_ENDORSED_KEY)')

    def test_subsequent_fill_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)
        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            interval=interval,
            start_timestamp=0,
            duration=4 * WEEK
        )

        # Execute Recurring Order
        # Simulate Swap by sending the `target_amount` from filler account.
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 1_000_000, self.tiny_asset_id)

        self.ledger.next_timestamp = now + DAY + 1
        filler_client.registry_user_opt_in()

        self.ledger.next_timestamp = now + DAY + 2
        self.manager_client.endorse(filler_client.user_address)

        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.

        amount = 100_000
        filled_amount = 0
        collected_target_amount = 0
        for current_recurrence in range(target_recurrence):
            if (current_recurrence + 1) == target_recurrence:
                fill_amount = amount - filled_amount
            else:
                fill_amount = 100_000 // target_recurrence

            bought_target_amount = 15_000 + randint(0, 1000)

            sp = filler_client.get_suggested_params()
            transactions = [
                filler_client.prepare_start_execute_recurring_order_transaction(
                    order_app_id=self.ordering_client.app_id,
                    order_id=0,
                    account_address=self.ordering_client.user_address,
                    fill_amount=fill_amount,
                    index_diff=2,
                    sp=sp
                ),
                transaction.AssetTransferTxn(
                    sender=filler_client.user_address,
                    sp=sp,
                    receiver=self.ordering_client.application_address,
                    amt=bought_target_amount,
                    index=self.tiny_asset_id
                ),
                filler_client.prepare_end_execute_recurring_order_transaction(
                    order_app_id=self.ordering_client.app_id,
                    order_id=0,
                    account_address=self.ordering_client.user_address,
                    fill_amount=fill_amount,
                    index_diff=2,
                    sp=sp
                ),
            ]

            self.ledger.next_timestamp = now + DAY + DAY * (current_recurrence + 1)
            filler_client._submit(transactions, additional_fees=3)

            filled_amount += fill_amount
            collected_target_amount += bought_target_amount

            # Box is deleted.
            if (current_recurrence + 1) == target_recurrence:
                continue

            recurring_order = self.ordering_client.get_box(self.ordering_client.get_recurring_order_box_name(0), "RecurringOrder")
            self.assertEqual(recurring_order.asset_id, self.talgo_asset_id)
            self.assertEqual(recurring_order.amount, 100_000)
            self.assertEqual(recurring_order.target_asset_id, self.tiny_asset_id)
            self.assertEqual(recurring_order.filled_amount, filled_amount)
            self.assertEqual(recurring_order.collected_target_amount, collected_target_amount)
            self.assertEqual(recurring_order.target_recurrence, target_recurrence)
            self.assertEqual(recurring_order.filled_recurrence, (current_recurrence + 1))
            self.assertEqual(recurring_order.interval, interval)
            self.assertEqual(recurring_order.fee_rate, 30)
            self.assertEqual(recurring_order.start_timestamp, now + DAY)
            self.assertEqual(recurring_order.creation_timestamp, now + DAY)
            self.assertEqual(recurring_order.expiration_timestamp, now + DAY + 4 * WEEK)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        start_execute_txn = block_txns[0]
        end_execute_txn = block_txns[2]

        events = decode_logs(start_execute_txn[b'dt'][b'lg'], ordering_events)

        self.assertEqual(len(events), 1)
        start_execute_order_event = events[0]

        self.assertEqual(start_execute_order_event['order_id'], 0)
        self.assertEqual(start_execute_order_event['filler_address'], filler_client.user_address)

        events = decode_logs(end_execute_txn[b'dt'][b'lg'], ordering_events)
        self.assertEqual(len(events), 2)
        recurring_order_event = events[0]
        end_execute_order_event = events[1]

        self.assertEqual(recurring_order_event['user_address'], self.user_address)
        self.assertEqual(recurring_order_event['order_id'], 0)
        self.assertEqual(recurring_order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(recurring_order_event['amount'], 100_000)
        self.assertEqual(recurring_order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(recurring_order_event['filled_amount'], filled_amount)
        self.assertEqual(recurring_order_event['collected_target_amount'], collected_target_amount)
        self.assertEqual(recurring_order_event['target_recurrence'], target_recurrence)
        self.assertEqual(recurring_order_event['filled_recurrence'], target_recurrence)
        self.assertEqual(recurring_order_event['interval'], interval)
        self.assertEqual(recurring_order_event['fee_rate'], 30)
        self.assertEqual(recurring_order_event['start_timestamp'], now + DAY)
        self.assertEqual(recurring_order_event['creation_timestamp'], now + DAY)
        self.assertEqual(recurring_order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(end_execute_order_event['user_address'], self.user_address)
        self.assertEqual(end_execute_order_event['order_id'], 0)
        self.assertEqual(end_execute_order_event['filler_address'], filler_client.user_address)
        self.assertEqual(end_execute_order_event['fill_amount'], fill_amount)
        self.assertEqual(end_execute_order_event['bought_amount'], bought_target_amount)


class CollectTests(OrderProtocolBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e14))

    def test_collect_recurring_order_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)
        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            interval=interval,
            start_timestamp=0,
            duration=4 * WEEK
        )

        # Execute Recurring Order
        # Simulate Swap by sending the `target_amount` from filler account.
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        self.ledger.next_timestamp = now + DAY + 1
        filler_client.registry_user_opt_in()

        self.ledger.next_timestamp = now + DAY + 2
        self.manager_client.endorse(filler_client.user_address)

        fill_amount = 100_000 // target_recurrence
        bought_target_amount = 15_000
        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_recurring_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
            transaction.AssetTransferTxn(
                sender=filler_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=bought_target_amount,
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_recurring_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
        ]

        self.ledger.next_timestamp = now + DAY + DAY
        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.
        filler_client._submit(transactions, additional_fees=3)

        # Collect
        self.ledger.next_timestamp = now + 2 * DAY + 1
        self.ordering_client.collect(order_id=0, order_type="r")

        block = self.ledger.last_block
        block_txns = block[b'txns']
        collect_txn = block_txns[0]

        events = decode_logs(collect_txn[b'dt'][b'lg'], ordering_events)

        self.assertEqual(len(events), 2)
        recurring_order_event = events[0]
        collect_event = events[1]

        self.assertEqual(recurring_order_event['user_address'], self.user_address)
        self.assertEqual(recurring_order_event['order_id'], 0)
        self.assertEqual(recurring_order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(recurring_order_event['amount'], 100_000)
        self.assertEqual(recurring_order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(recurring_order_event['filled_amount'], fill_amount)
        self.assertEqual(recurring_order_event['collected_target_amount'], 0)
        self.assertEqual(recurring_order_event['target_recurrence'], target_recurrence)
        self.assertEqual(recurring_order_event['filled_recurrence'], 1)
        self.assertEqual(recurring_order_event['interval'], interval)
        self.assertEqual(recurring_order_event['fee_rate'], 30)
        self.assertEqual(recurring_order_event['start_timestamp'], now + DAY)
        self.assertEqual(recurring_order_event['creation_timestamp'], now + DAY)
        self.assertEqual(recurring_order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(collect_event["order_id"], 0)
        self.assertEqual(collect_event["collected_target_amount"], bought_target_amount)

        recurring_order = self.ordering_client.get_box(self.ordering_client.get_recurring_order_box_name(0), "RecurringOrder")
        self.assertEqual(recurring_order.asset_id, self.talgo_asset_id)
        self.assertEqual(recurring_order.amount, 100_000)
        self.assertEqual(recurring_order.target_asset_id, self.tiny_asset_id)
        self.assertEqual(recurring_order.filled_amount, fill_amount)
        self.assertEqual(recurring_order.collected_target_amount, 0)
        self.assertEqual(recurring_order.target_recurrence, target_recurrence)
        self.assertEqual(recurring_order.filled_recurrence, 1)
        self.assertEqual(recurring_order.interval, interval)
        self.assertEqual(recurring_order.fee_rate, 30)
        self.assertEqual(recurring_order.start_timestamp, now + DAY)
        self.assertEqual(recurring_order.creation_timestamp, now + DAY)
        self.assertEqual(recurring_order.expiration_timestamp, now + DAY + 4 * WEEK)

        inner_txns = collect_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 2)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 15_000 - ((15_000 * 30) // 10_000))

        self.assertEqual(inner_txns[1][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[1][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[1][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'arcv'], decode_address(self.ordering_client.registry_application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'aamt'], ((15_000 * 30) // 10_000))

    def test_collect_trigger_order_partial_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=True,
            duration=4 * WEEK
        )

        # Execute Order
        # Simulate Swap by sending the `target_amount` from filler account.
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        fill_amount = 50_000
        bought_target_amount = (15_000 // 2)
        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
            transaction.AssetTransferTxn(
                sender=filler_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=bought_target_amount,
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
        ]

        self.ledger.next_timestamp = now + DAY + 1
        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.
        filler_client._submit(transactions, additional_fees=3)

        # Collect
        self.ledger.next_timestamp = now + 2 * DAY + 1
        self.ordering_client.collect(order_id=0, order_type="o")

        block = self.ledger.last_block
        block_txns = block[b'txns']
        collect_txn = block_txns[0]

        events = decode_logs(collect_txn[b'dt'][b'lg'], ordering_events)

        self.assertEqual(len(events), 2)
        order_event = events[0]
        collect_event = events[1]

        self.assertEqual(order_event['user_address'], self.user_address)
        self.assertEqual(order_event['order_id'], 0)
        self.assertEqual(order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(order_event['amount'], 100_000)
        self.assertEqual(order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(order_event['target_amount'], 15_000)
        self.assertEqual(order_event['filled_amount'], fill_amount)
        self.assertEqual(order_event['collected_target_amount'], 0)
        self.assertEqual(order_event['is_partial_allowed'], 1)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(collect_event["order_id"], 0)
        self.assertEqual(collect_event["collected_target_amount"], bought_target_amount)

        order = self.ordering_client.get_box(self.ordering_client.get_order_box_name(0), "Order")
        self.assertEqual(order.asset_id, self.talgo_asset_id)
        self.assertEqual(order.amount, 100_000)
        self.assertEqual(order.target_asset_id, self.tiny_asset_id)
        self.assertEqual(order.target_amount, 15_000)
        self.assertEqual(order.filled_amount, fill_amount)
        self.assertEqual(order.collected_target_amount, 0)
        self.assertEqual(order.is_partial_allowed, 1)
        self.assertEqual(order.fee_rate, 30)
        self.assertEqual(order.creation_timestamp, now + DAY)
        self.assertEqual(order.expiration_timestamp, now + DAY + 4 * WEEK)
