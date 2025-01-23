from datetime import datetime, timezone

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
                MANAGER_KEY: decode_address(self.register_application_address),
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
            expiration_timestamp=now + DAY + 4 * WEEK
        )

        block = self.ledger.last_block
        block_txns = block[b'txns']
        axfer_txn = block_txns[1]
        put_order_txn = block_txns[2]

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
            expiration_timestamp=now + DAY + 4 * WEEK
        )

        block = self.ledger.last_block
        block_txns = block[b'txns']
        axfer_txn = block_txns[1]
        put_order_txn = block_txns[2]

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
            expiration_timestamp=now + DAY + 4 * WEEK
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
            expiration_timestamp=now + DAY + 4 * WEEK
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
        pass

    def test_execute_order_partial_successful(self):
        pass

    def test_execute_order_partial_subsequent_successful(self):
        pass
