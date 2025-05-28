from datetime import datetime, timezone

from algojig.exceptions import LogicEvalError
from algojig import TealishProgram

from algosdk import transaction
from algosdk.encoding import decode_address

from tinyman.swap_router.utils import encode_router_args
from tinyman.utils import int_to_bytes

from sdk.constants import *
from sdk.event import decode_logs
from sdk.events import ordering_events, registry_events
from sdk.structs import AppVersion, RecurringOrder, TriggerOrder
from sdk.utils import calculate_approval_hash
from tests.constants import order_approval_program, WEEK, DAY, MAX_UINT64
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

        version = 2
        key = b"v" + version.to_bytes(8, "big")
        approval_hash = calculate_approval_hash(order_approval_program.bytecode)
        struct = AppVersion()
        struct.approval_hash = approval_hash
        self.ledger.set_box(self.registry_app_id, key, struct._data)
        self.ledger.global_states[self.registry_app_id][b"latest_version"] = version

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
                REGISTRY_APP_ID_KEY: self.registry_app_id,
                REGISTRY_APP_ACCOUNT_ADDRESS_KEY: decode_address(self.register_application_address),
                VAULT_APP_ID_KEY: self.vault_app_id,
                ROUTER_APP_ID_KEY: self.router_app_id,
                VERSION_KEY: version,
            }
        )

    def test_update_order_app(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        self.assertEqual(self.ledger.get_global_state(self.app_id)[b"version"], 1)

        # Mock Approve a version
        approval_program = TealishProgram('contracts/order/order_approval.tl')
        approval_program.tealish_source = approval_program.tealish_source.replace("VERSION = 1", "VERSION = 2")
        approval_program.compile()
        update_bytecode = approval_program.bytecode

        version = 2
        key = b"v" + version.to_bytes(8, "big")
        approval_hash = calculate_approval_hash(update_bytecode)
        struct = AppVersion()
        struct.approval_hash = approval_hash
        self.ledger.set_box(self.registry_app_id, key, struct._data)
        self.ledger.global_states[self.registry_app_id][b"latest_version"] = version

        # Update Ordering App
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.update_ordering_app(version, update_bytecode)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        update_application_txn = block_txns[0]
        verify_update_txn = block_txns[1]

        events = decode_logs(update_application_txn[b'dt'][b'lg'], ordering_events)
        update_application_event = events[0]

        self.assertEqual(update_application_event["user_address"], self.user_address)
        self.assertEqual(update_application_event["version"], 2)

        events = decode_logs(verify_update_txn[b'dt'][b'lg'], registry_events)
        emited_event = events[0]

        self.assertEqual(emited_event['event_name'], 'update_ordering_application')
        self.assertEqual(emited_event['order_app_id'], self.app_id)
        self.assertEqual(emited_event['version'], 2)

        self.assertEqual(self.ledger.get_global_state(self.app_id)[b"version"], 2)


class PutTriggerOrderTests(OrderProtocolBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e14))

    def test_put_trigger_order_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Trigger Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_trigger_order(
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

        order = self.ordering_client.get_box(self.ordering_client.get_order_box_name(0), "TriggerOrder")
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

    def test_put_trigger_order_partial_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Trigger Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_trigger_order(
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

        order = self.ordering_client.get_box(self.ordering_client.get_order_box_name(0), "TriggerOrder")
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

    def test_put_trigger_order_insufficient_axfer(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()
        order_box_name = self.ordering_client.get_order_box_name(0)

        new_boxes = {}
        new_boxes[order_box_name] = TriggerOrder
        transactions = [
            transaction.PaymentTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=self.ordering_client.calculate_min_balance(boxes=new_boxes)
            ),
            transaction.AssetTransferTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                index=self.talgo_asset_id,
                amt=(100_000 - 1),  # 1 less than said amount in appcall.
            ),
            transaction.ApplicationCallTxn(
                sender=self.ordering_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.ordering_client.app_id,
                app_args=[
                    "put_trigger_order",
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(100_000),
                    int_to_bytes(self.tiny_asset_id),
                    int_to_bytes(15_000),
                    int_to_bytes(int(False)),
                    int_to_bytes(4 * WEEK)
                ],
                foreign_assets=[self.tiny_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.ordering_client.vault_app_id, decode_address(self.ordering_client.user_address)),
                    (self.ordering_client.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
            )
        ]

        # Put Trigger Order
        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            self.ordering_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(Gtxn[txn_index].AssetAmount == amount)')

    def test_put_order_zero_amount_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()
        order_box_name = self.ordering_client.get_order_box_name(0)

        new_boxes = {}
        new_boxes[order_box_name] = TriggerOrder
        transactions = [
            transaction.PaymentTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=self.ordering_client.calculate_min_balance(boxes=new_boxes)
            ),
            transaction.AssetTransferTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                index=self.talgo_asset_id,
                amt=100_000,
            ),
            transaction.ApplicationCallTxn(
                sender=self.ordering_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.ordering_client.app_id,
                app_args=[
                    "put_trigger_order",
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(0),
                    int_to_bytes(self.tiny_asset_id),
                    int_to_bytes(15_000),
                    int_to_bytes(int(False)),
                    int_to_bytes(4 * WEEK)
                ],
                foreign_assets=[self.tiny_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.ordering_client.vault_app_id, decode_address(self.ordering_client.user_address)),
                    (self.ordering_client.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
            )
        ]

        # Put Trigger Order
        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            self.ordering_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(amount > 0)')

    def test_put_order_zero_target_amount_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()
        order_box_name = self.ordering_client.get_order_box_name(0)

        new_boxes = {}
        new_boxes[order_box_name] = TriggerOrder
        transactions = [
            transaction.PaymentTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=self.ordering_client.calculate_min_balance(boxes=new_boxes)
            ),
            transaction.AssetTransferTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                index=self.talgo_asset_id,
                amt=100_000,
            ),
            transaction.ApplicationCallTxn(
                sender=self.ordering_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.ordering_client.app_id,
                app_args=[
                    "put_trigger_order",
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(100_000),
                    int_to_bytes(self.tiny_asset_id),
                    int_to_bytes(0),
                    int_to_bytes(int(False)),
                    int_to_bytes(4 * WEEK)
                ],
                foreign_assets=[self.tiny_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.ordering_client.vault_app_id, decode_address(self.ordering_client.user_address)),
                    (self.ordering_client.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
            )
        ]

        # Put Trigger Order
        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            self.ordering_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(target_amount > 0)')

    def test_put_order_non_user_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()
        order_box_name = self.ordering_client.get_order_box_name(0)

        new_client = self.get_new_user_client()
        self.ledger.opt_in_asset(new_client.user_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(new_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(new_client.user_address, 100_000, self.talgo_asset_id)

        new_boxes = {}
        new_boxes[order_box_name] = TriggerOrder
        transactions = [
            transaction.PaymentTxn(
                sender=new_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=self.ordering_client.calculate_min_balance(boxes=new_boxes)
            ),
            transaction.AssetTransferTxn(
                sender=new_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                index=self.talgo_asset_id,
                amt=100_000,
            ),
            transaction.ApplicationCallTxn(
                sender=new_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.ordering_client.app_id,
                app_args=[
                    "put_trigger_order",
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(100_000),
                    int_to_bytes(self.tiny_asset_id),
                    int_to_bytes(0),
                    int_to_bytes(int(False)),
                    int_to_bytes(0)
                ],
                foreign_assets=[self.tiny_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.ordering_client.vault_app_id, decode_address(self.ordering_client.user_address)),
                    (self.ordering_client.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
            )
        ]

        # Put Trigger Order
        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            new_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(Txn.Sender == user_address)')

    def test_put_order_target_same_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()
        order_box_name = self.ordering_client.get_order_box_name(0)

        new_boxes = {}
        new_boxes[order_box_name] = TriggerOrder
        transactions = [
            transaction.PaymentTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=self.ordering_client.calculate_min_balance(boxes=new_boxes)
            ),
            transaction.AssetTransferTxn(
                sender=self.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                index=self.talgo_asset_id,
                amt=100_000,
            ),
            transaction.ApplicationCallTxn(
                sender=self.ordering_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.ordering_client.app_id,
                app_args=[
                    "put_trigger_order",
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(100_000),
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(15_000),
                    int_to_bytes(int(False)),
                    int_to_bytes(4 * WEEK)
                ],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.ordering_client.vault_app_id, decode_address(self.ordering_client.user_address)),
                    (self.ordering_client.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
            )
        ]

        # Put Trigger Order
        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            self.ordering_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(asset_id != target_asset_id)')


class CancelTriggerOrderTests(OrderProtocolBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e14))

    def test_cancel_trigger_order_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Trigger Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_trigger_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=False,
            duration=4 * WEEK
        )

        # Cancel Trigger Order
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.cancel_trigger_order(0)

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

        # registry events
        events = decode_logs(cancel_order_txn[b'dt'][b'itx'][-1][b'dt'][b'lg'], registry_events)
        cancel_order_event = events[0]
        self.assertEqual(cancel_order_event['order_app_id'], self.ordering_client.app_id)
        self.assertEqual(cancel_order_event['order_id'], 0)

        # Inner Transaction Checks
        inner_txns = cancel_order_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 2)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 100_000)

    def test_cancel_trigger_order_partial_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Trigger Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_trigger_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=True,
            duration=4 * WEEK
        )

        # Mock partial filling. Amount is already collected.
        filled_amount = 10_000
        order_box_name = self.ordering_client.get_order_box_name(0)
        order = TriggerOrder(bytearray(self.ordering_client.get_box(order_box_name, "TriggerOrder")._data))
        order.filled_amount = filled_amount
        self.ledger.set_box(self.ordering_client.app_id, key=order_box_name, value=order._data)

        # Cancel Trigger Order
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.cancel_trigger_order(0)

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

        self.assertEqual(len(inner_txns), 2)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 90_000)

    def test_cancel_order_partial_filled_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Trigger Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_trigger_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=True,
            duration=4 * WEEK
        )

        # Mock partial filling.
        filled_amount = 10_000
        collected_target_amount = 1500
        order_box_name = self.ordering_client.get_order_box_name(0)
        order = TriggerOrder(bytearray(self.ordering_client.get_box(order_box_name, "TriggerOrder")._data))
        order.filled_amount = filled_amount
        order.collected_target_amount = collected_target_amount
        self.ledger.set_box(self.ordering_client.app_id, key=order_box_name, value=order._data)

        # Cancel Trigger Order
        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            self.ordering_client.cancel_trigger_order(0)
        self.assertEqual(e.exception.source['line'], 'assert(!order.collected_target_amount)')

    def test_cancel_order_non_user_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Trigger Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_trigger_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=False,
            duration=4 * WEEK
        )

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()
        order_box_name = self.ordering_client.get_order_box_name(0)

        new_client = self.get_new_user_client()
        self.ledger.opt_in_asset(new_client.user_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(new_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(new_client.user_address, 100_000, self.talgo_asset_id)

        transactions = [
            transaction.ApplicationCallTxn(
                sender=new_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.ordering_client.app_id,
                app_args=[
                    "cancel_trigger_order",
                    int_to_bytes(0)
                ],
                boxes=[
                    (0, order_box_name),
                    (self.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
                foreign_assets=[self.talgo_asset_id],
                foreign_apps=[self.registry_app_id]
            )
        ]

        # Cancel Trigger Order
        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            new_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(Txn.Sender == user_address)')


class ExecuteTriggerOrderTests(OrderProtocolBaseTestCase):
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

        # Put Trigger Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_trigger_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=False,
            duration=4 * WEEK
        )

        # Execute Trigger Order
        # Simulate Swap by sending the `target_amount` from filler account.
        fill_amount = 100_000
        bought_amount = 15_000
        fee_rate = 30
        fee_amount = int((bought_amount * fee_rate) / 10_000)
        collected_target_amount = bought_amount - fee_amount
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_trigger_order_transaction(
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
                amt=bought_amount,
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_trigger_order_transaction(
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
        filler_client._submit(transactions, additional_fees=4)

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
        self.assertEqual(order_event['collected_target_amount'], collected_target_amount)
        self.assertEqual(order_event['is_partial_allowed'], 0)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(end_execute_order_event['user_address'], self.user_address)
        self.assertEqual(end_execute_order_event['order_id'], 0)
        self.assertEqual(end_execute_order_event['filler_address'], filler_client.user_address)
        self.assertEqual(end_execute_order_event['fill_amount'], fill_amount)
        self.assertEqual(end_execute_order_event['bought_amount'], bought_amount)

        inner_txns = start_execute_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 1)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(filler_client.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], fill_amount)

        inner_txns = end_execute_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 3)
        self.assertEqual(inner_txns[1][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[1][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[1][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'arcv'], decode_address(self.ordering_client.registry_application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'aamt'], fee_amount)

        self.assertEqual(inner_txns[2][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[2][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[2][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[2][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[2][b'txn'][b'aamt'], collected_target_amount)

        events = decode_logs(inner_txns[0][b'dt'][b'lg'], registry_events)
        self.assertEqual(len(events), 1)
        order_event = events[0]
        self.assertEqual(order_event['order_app_id'], self.ordering_client.app_id)
        self.assertEqual(order_event['order_id'], 0)
        self.assertEqual(order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(order_event['amount'], 100_000)
        self.assertEqual(order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(order_event['target_amount'], 15_000)
        self.assertEqual(order_event['filled_amount'], 100_000)
        self.assertEqual(order_event['collected_target_amount'], collected_target_amount)
        self.assertEqual(order_event['is_partial_allowed'], 0)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

    def test_execute_order_partial_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Trigger Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_trigger_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=True,
            duration=4 * WEEK
        )

        # Execute Trigger Order
        # Simulate Swap by sending the `target_amount` from filler account.
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        fill_amount = 50_000
        bought_amount = (15_000 // 2)
        fee_rate = 30
        fee_amount = int((bought_amount * fee_rate) / 10_000)
        collected_target_amount = bought_amount - fee_amount
        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_trigger_order_transaction(
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
                amt=bought_amount,
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_trigger_order_transaction(
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
        filler_client._submit(transactions, additional_fees=4)

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
        self.assertEqual(order_event['collected_target_amount'], collected_target_amount)
        self.assertEqual(order_event['is_partial_allowed'], 1)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(end_execute_order_event['user_address'], self.user_address)
        self.assertEqual(end_execute_order_event['order_id'], 0)
        self.assertEqual(end_execute_order_event['filler_address'], filler_client.user_address)
        self.assertEqual(end_execute_order_event['fill_amount'], fill_amount)
        self.assertEqual(end_execute_order_event['bought_amount'], bought_amount)

        order = self.ordering_client.get_box(self.ordering_client.get_order_box_name(0), "TriggerOrder")
        self.assertEqual(order.asset_id, self.talgo_asset_id)
        self.assertEqual(order.amount, 100_000)
        self.assertEqual(order.target_asset_id, self.tiny_asset_id)
        self.assertEqual(order.target_amount, 15_000)
        self.assertEqual(order.filled_amount, fill_amount)
        self.assertEqual(order.collected_target_amount, collected_target_amount)
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

        inner_txns = end_execute_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 2)
        self.assertEqual(inner_txns[1][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[1][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[1][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'arcv'], decode_address(self.ordering_client.registry_application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'aamt'], fee_amount)

        events = decode_logs(inner_txns[0][b'dt'][b'lg'], registry_events)
        self.assertEqual(len(events), 1)
        order_event = events[0]
        self.assertEqual(order_event['order_app_id'], self.ordering_client.app_id)
        self.assertEqual(order_event['order_id'], 0)
        self.assertEqual(order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(order_event['amount'], 100_000)
        self.assertEqual(order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(order_event['target_amount'], 15_000)
        self.assertEqual(order_event['filled_amount'], fill_amount)
        self.assertEqual(order_event['collected_target_amount'], collected_target_amount)
        self.assertEqual(order_event['is_partial_allowed'], 1)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

    def test_execute_order_partial_subsequent_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Trigger Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_trigger_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=True,
            duration=4 * WEEK
        )

        # Modify the order as if it is partially filled before.
        order_box_name = self.ordering_client.get_order_box_name(0)
        order = TriggerOrder(bytearray(self.ordering_client.get_box(order_box_name, "TriggerOrder")._data))
        order.filled_amount = 50_000
        order.collected_target_amount = (15_000 // 2)
        self.ledger.set_box(self.ordering_client.app_id, key=order_box_name, value=order._data)

        # Modify the order app balance.
        self.ledger.set_account_balance(self.ordering_client.application_address, 50_000, self.talgo_asset_id)
        self.ledger.set_account_balance(self.ordering_client.application_address, (15_000 // 2), self.tiny_asset_id)

        # Execute Trigger Order
        # Simulate Swap by sending the `target_amount` from filler account.
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        fill_amount = 50_000
        bought_amount = (15_000 // 2)
        fee_rate = 30
        fee_amount = int((bought_amount * fee_rate) / 10_000)
        collected_target_amount = (15_000 // 2) + (bought_amount - fee_amount)
        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_trigger_order_transaction(
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
                amt=bought_amount,
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_trigger_order_transaction(
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
        filler_client._submit(transactions, additional_fees=4)

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
        self.assertEqual(order_event['collected_target_amount'], collected_target_amount)
        self.assertEqual(order_event['is_partial_allowed'], 1)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)

        self.assertEqual(end_execute_order_event['user_address'], self.user_address)
        self.assertEqual(end_execute_order_event['order_id'], 0)
        self.assertEqual(end_execute_order_event['filler_address'], filler_client.user_address)
        self.assertEqual(end_execute_order_event['fill_amount'], fill_amount)
        self.assertEqual(end_execute_order_event['bought_amount'], bought_amount)

        inner_txns = start_execute_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 1)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(filler_client.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], fill_amount)

        inner_txns = end_execute_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 3)
        self.assertEqual(inner_txns[1][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[1][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[1][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'arcv'], decode_address(self.ordering_client.registry_application_address))
        self.assertEqual(inner_txns[1][b'txn'][b'aamt'], fee_amount)

        self.assertEqual(inner_txns[2][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[2][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[2][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[2][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[2][b'txn'][b'aamt'], collected_target_amount)

        events = decode_logs(inner_txns[0][b'dt'][b'lg'], registry_events)
        self.assertEqual(len(events), 1)
        order_event = events[0]
        self.assertEqual(order_event['order_app_id'], self.ordering_client.app_id)
        self.assertEqual(order_event['order_id'], 0)
        self.assertEqual(order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(order_event['amount'], 100_000)
        self.assertEqual(order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(order_event['target_amount'], 15_000)
        self.assertEqual(order_event['filled_amount'], 100_000)
        self.assertEqual(order_event['collected_target_amount'], collected_target_amount)
        self.assertEqual(order_event['is_partial_allowed'], 1)
        self.assertEqual(order_event['fee_rate'], 30)
        self.assertEqual(order_event['creation_timestamp'], now + DAY)
        self.assertEqual(order_event['expiration_timestamp'], now + DAY + 4 * WEEK)
    
    def test_filler_insufficent_amt_returns_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Trigger Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_trigger_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=True,
            duration=4 * WEEK
        )

        # Execute Trigger Order
        # Fail `end_execute_trigger_order` at received_amount check.
        # Simulate Swap by sending the `target_amount` from filler account.
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        fill_amount = 50_000
        bought_amount = (15_000 // 2)
        fee_rate = 30
        fee_amount = int((bought_amount * fee_rate) / 10_000)
        collected_target_amount = bought_amount - fee_amount
        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_trigger_order_transaction(
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
                amt=bought_amount - 2,  # Less than required price.
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_trigger_order_transaction(
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

        with self.assertRaises(LogicEvalError) as e:
            filler_client._submit(transactions, additional_fees=4)
        self.assertEqual(e.exception.source['line'], 'assert(Gtxn[txn_index].AssetAmount >= minimum_amount)')

    def test_expired_trigger_order_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Trigger Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 100_000, self.talgo_asset_id)

        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_trigger_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_amount=15_000,
            is_partial_allowed=False,
            duration=4 * WEEK
        )

        # Execute Trigger Order
        # Fail `start_execute_trigger_order` at Global.LatestTimestamp check.
        # Simulate Swap by sending the `target_amount` from filler account.
        fill_amount = 100_000
        bought_amount = 15_000
        fee_rate = 30
        fee_amount = int((bought_amount * fee_rate) / 10_000)
        collected_target_amount = bought_amount - fee_amount
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_trigger_order_transaction(
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
                amt=bought_amount,
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_trigger_order_transaction(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                account_address=self.ordering_client.user_address,
                fill_amount=fill_amount,
                index_diff=2,
                sp=sp
            ),
        ]

        self.ledger.next_timestamp = now + DAY + now + DAY + 1
        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.
        with self.assertRaises(LogicEvalError) as e:
            filler_client._submit(transactions, additional_fees=4)
        self.assertEqual(e.exception.source['line'], 'assert(Global.LatestTimestamp <= order.expiration_timestamp)')


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

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            min_target_amount=0,
            max_target_amount=0,
            interval=interval,
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
        self.assertEqual(recurring_order_event['collected_target_amount'], 0)
        self.assertEqual(recurring_order_event['remaining_recurrences'], target_recurrence)
        self.assertEqual(recurring_order_event['min_target_amount'], 0)
        self.assertEqual(recurring_order_event['max_target_amount'], MAX_UINT64)
        self.assertEqual(recurring_order_event['interval'], interval)
        self.assertEqual(recurring_order_event['fee_rate'], 30)
        self.assertEqual(recurring_order_event['last_fill_timestamp'], 0)
        self.assertEqual(recurring_order_event['creation_timestamp'], now + DAY)

        self.assertEqual(put_recurring_order_event['order_id'], 0)

        # registry events
        events = decode_logs(put_recurring_order_txn[b'dt'][b'itx'][-1][b'dt'][b'lg'], registry_events)
        put_recurring_order_event = events[0]
        self.assertEqual(put_recurring_order_event['order_app_id'], self.ordering_client.app_id)
        self.assertEqual(put_recurring_order_event['order_id'], 0)
        self.assertEqual(put_recurring_order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(put_recurring_order_event['amount'], 100_000)
        self.assertEqual(put_recurring_order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(put_recurring_order_event['collected_target_amount'], 0)
        self.assertEqual(put_recurring_order_event['remaining_recurrences'], target_recurrence)
        self.assertEqual(put_recurring_order_event['min_target_amount'], 0)
        self.assertEqual(put_recurring_order_event['max_target_amount'], MAX_UINT64)
        self.assertEqual(put_recurring_order_event['interval'], interval)
        self.assertEqual(put_recurring_order_event['fee_rate'], 30)
        self.assertEqual(put_recurring_order_event['last_fill_timestamp'], 0)
        self.assertEqual(put_recurring_order_event['creation_timestamp'], now + DAY)

        recurring_order = self.ordering_client.get_box(self.ordering_client.get_recurring_order_box_name(0), "RecurringOrder")
        self.assertEqual(recurring_order.asset_id, self.talgo_asset_id)
        self.assertEqual(recurring_order.amount, 100_000)
        self.assertEqual(recurring_order.target_asset_id, self.tiny_asset_id)
        self.assertEqual(recurring_order.collected_target_amount, 0)
        self.assertEqual(recurring_order.remaining_recurrences, target_recurrence)
        self.assertEqual(recurring_order.min_target_amount, 0)
        self.assertEqual(recurring_order.max_target_amount, MAX_UINT64)
        self.assertEqual(recurring_order.interval, interval)
        self.assertEqual(recurring_order.fee_rate, 30)
        self.assertEqual(recurring_order.last_fill_timestamp, 0)
        self.assertEqual(recurring_order.creation_timestamp, now + DAY)

    def test_put_recurring_order_zero_amount_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()

        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        new_boxes = {}
        new_boxes[order_box_name] = TriggerOrder

        amount = 100_000
        target_recurrence = 7
        interval = DAY
        total_amount = amount * target_recurrence
        transactions = [
            transaction.PaymentTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=self.ordering_client.calculate_min_balance(boxes=new_boxes)
            ) if new_boxes else None,
            transaction.AssetTransferTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                index=self.talgo_asset_id,
                amt=total_amount,
            ),
            transaction.ApplicationCallTxn(
                sender=self.ordering_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=[
                    "put_recurring_order",
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(0),
                    int_to_bytes(self.tiny_asset_id),
                    int_to_bytes(0),
                    int_to_bytes(0),
                    int_to_bytes(target_recurrence),
                    int_to_bytes(interval),
                ],
                foreign_assets=[self.tiny_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.vault_app_id, decode_address(self.user_address)),
                    (self.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
            )
        ]

        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            self.ordering_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(amount > 0)')

    def test_put_recurring_order_target_same_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()

        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        new_boxes = {}
        new_boxes[order_box_name] = TriggerOrder

        amount = 100_000
        target_recurrence = 7
        interval = DAY
        total_amount = amount * target_recurrence
        transactions = [
            transaction.PaymentTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=self.ordering_client.calculate_min_balance(boxes=new_boxes)
            ) if new_boxes else None,
            transaction.AssetTransferTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                index=self.talgo_asset_id,
                amt=total_amount,
            ),
            transaction.ApplicationCallTxn(
                sender=self.ordering_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=[
                    "put_recurring_order",
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(amount),
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(0),
                    int_to_bytes(0),
                    int_to_bytes(target_recurrence),
                    int_to_bytes(interval),
                ],
                foreign_assets=[self.tiny_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.vault_app_id, decode_address(self.user_address)),
                    (self.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
            )
        ]

        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            self.ordering_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(asset_id != target_asset_id)')

    def test_put_recurring_order_zero_target_recurrence_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()

        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        new_boxes = {}
        new_boxes[order_box_name] = TriggerOrder

        amount = 100_000
        target_recurrence = 7
        interval = DAY
        total_amount = amount * target_recurrence
        transactions = [
            transaction.PaymentTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=self.ordering_client.calculate_min_balance(boxes=new_boxes)
            ) if new_boxes else None,
            transaction.AssetTransferTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                index=self.talgo_asset_id,
                amt=total_amount,
            ),
            transaction.ApplicationCallTxn(
                sender=self.ordering_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=[
                    "put_recurring_order",
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(amount),
                    int_to_bytes(self.tiny_asset_id),
                    int_to_bytes(0),
                    int_to_bytes(0),
                    int_to_bytes(0),
                    int_to_bytes(interval),
                ],
                foreign_assets=[self.tiny_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.vault_app_id, decode_address(self.user_address)),
                    (self.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
            )
        ]

        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            self.ordering_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(target_recurrence > 0)')


    def test_put_recurring_order_incorrect_interval_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()

        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        new_boxes = {}
        new_boxes[order_box_name] = TriggerOrder

        amount = 100_000
        target_recurrence = 7
        interval = DAY
        total_amount = amount * target_recurrence
        transactions = [
            transaction.PaymentTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=self.ordering_client.calculate_min_balance(boxes=new_boxes)
            ) if new_boxes else None,
            transaction.AssetTransferTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                index=self.talgo_asset_id,
                amt=total_amount,
            ),
            transaction.ApplicationCallTxn(
                sender=self.ordering_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=[
                    "put_recurring_order",
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(amount),
                    int_to_bytes(self.tiny_asset_id),
                    int_to_bytes(0),
                    int_to_bytes(0),
                    int_to_bytes(target_recurrence),
                    int_to_bytes(60 + 1),
                ],
                foreign_assets=[self.tiny_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.vault_app_id, decode_address(self.user_address)),
                    (self.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
            )
        ]

        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            self.ordering_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(!(interval % MINUTE))')

    def test_app_not_opted_into_target_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()

        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        new_boxes = {}
        new_boxes[order_box_name] = TriggerOrder

        amount = 100_000
        target_recurrence = 7
        interval = DAY
        total_amount = amount * target_recurrence
        transactions = [
            transaction.PaymentTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=self.ordering_client.calculate_min_balance(boxes=new_boxes)
            ) if new_boxes else None,
            transaction.AssetTransferTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                index=self.talgo_asset_id,
                amt=total_amount,
            ),
            transaction.ApplicationCallTxn(
                sender=self.ordering_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=[
                    "put_recurring_order",
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(amount),
                    int_to_bytes(self.tiny_asset_id),
                    int_to_bytes(0),
                    int_to_bytes(0),
                    int_to_bytes(target_recurrence),
                    int_to_bytes(interval),
                ],
                foreign_assets=[self.tiny_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.vault_app_id, decode_address(self.user_address)),
                    (self.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
            )
        ]

        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            self.ordering_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(is_opted_in_to_target)')

    def test_put_recurring_order_insufficient_axfer_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()

        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        new_boxes = {}
        new_boxes[order_box_name] = TriggerOrder

        amount = 100_000
        target_recurrence = 7
        interval = DAY
        total_amount = amount * target_recurrence
        transactions = [
            transaction.PaymentTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=self.ordering_client.calculate_min_balance(boxes=new_boxes)
            ) if new_boxes else None,
            transaction.AssetTransferTxn(
                sender=self.ordering_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                index=self.talgo_asset_id,
                amt=total_amount - 1,  # Less than required.
            ),
            transaction.ApplicationCallTxn(
                sender=self.ordering_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.app_id,
                app_args=[
                    "put_recurring_order",
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(amount),
                    int_to_bytes(self.tiny_asset_id),
                    int_to_bytes(0),
                    int_to_bytes(0),
                    int_to_bytes(target_recurrence),
                    int_to_bytes(interval),
                ],
                foreign_assets=[self.tiny_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.vault_app_id, decode_address(self.user_address)),
                    (self.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
            )
        ]

        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            self.ordering_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(Gtxn[txn_index].AssetAmount == amount)')

    def test_put_recurring_order_non_user_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        new_client = self.get_new_user_client()
        self.ledger.set_account_balance(new_client.user_address, 700_000, self.talgo_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()

        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        new_boxes = {}
        new_boxes[order_box_name] = TriggerOrder

        amount = 100_000
        target_recurrence = 7
        interval = DAY
        total_amount = amount * target_recurrence
        transactions = [
            transaction.PaymentTxn(
                sender=new_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                amt=self.ordering_client.calculate_min_balance(boxes=new_boxes)
            ) if new_boxes else None,
            transaction.AssetTransferTxn(
                sender=new_client.user_address,
                sp=sp,
                receiver=self.ordering_client.application_address,
                index=self.talgo_asset_id,
                amt=total_amount - 1,  # Less than required.
            ),
            transaction.ApplicationCallTxn(
                sender=new_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.ordering_client.app_id,
                app_args=[
                    "put_recurring_order",
                    int_to_bytes(self.talgo_asset_id),
                    int_to_bytes(amount),
                    int_to_bytes(self.tiny_asset_id),
                    int_to_bytes(0),
                    int_to_bytes(0),
                    int_to_bytes(target_recurrence),
                    int_to_bytes(interval),
                ],
                accounts=[self.ordering_client.user_address],
                foreign_assets=[self.tiny_asset_id],
                foreign_apps=[self.registry_app_id, self.vault_app_id],
                boxes=[
                    (0, order_box_name),
                    (self.vault_app_id, decode_address(self.user_address)),
                    (self.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
            )
        ]

        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            new_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(Txn.Sender == user_address)')


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

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            min_target_amount=0,
            max_target_amount=0,
            interval=interval,
        )

        # Cancel Recurring Order
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
        self.assertEqual(recurring_order_event['collected_target_amount'], 0)
        self.assertEqual(recurring_order_event['remaining_recurrences'], target_recurrence)
        self.assertEqual(recurring_order_event['min_target_amount'], 0)
        self.assertEqual(recurring_order_event['max_target_amount'], MAX_UINT64)
        self.assertEqual(recurring_order_event['interval'], interval)
        self.assertEqual(recurring_order_event['fee_rate'], 30)
        self.assertEqual(recurring_order_event['last_fill_timestamp'], 0)
        self.assertEqual(recurring_order_event['creation_timestamp'], now + DAY)

        self.assertEqual(cancel_recurring_order_event['order_id'], 0)

        # registry events
        events = decode_logs(cancel_recurring_order_txn[b'dt'][b'itx'][-1][b'dt'][b'lg'], registry_events)
        cancel_recurring_order_event = events[0]
        self.assertEqual(cancel_recurring_order_event['order_app_id'], self.ordering_client.app_id)
        self.assertEqual(cancel_recurring_order_event['order_id'], 0)

        # Inner Transaction Checks
        inner_txns = cancel_recurring_order_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 2)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.talgo_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 700_000)

    def test_non_zero_collected_target_amount_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            min_target_amount=0,
            max_target_amount=0,
            interval=interval,
        )

        # Mock partial filling.
        remaining_recurrences = target_recurrence - 1
        collected_target_amount = 1500
        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        order = RecurringOrder(bytearray(self.ordering_client.get_box(order_box_name, "RecurringOrder")._data))
        order.remaining_recurrences = remaining_recurrences
        order.collected_target_amount = collected_target_amount
        order.last_fill_timestamp = now + DAY + interval
        self.ledger.set_box(self.ordering_client.app_id, key=order_box_name, value=order._data)

        # Cancel Recurring Order
        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            self.ordering_client.cancel_recurring_order(0)
        self.assertEqual(e.exception.source['line'], 'assert(!order.collected_target_amount)')

    def test_non_user_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            min_target_amount=0,
            max_target_amount=0,
            interval=interval,
        )

        # Prepare transactions.
        new_client = self.get_new_user_client()
        sp = self.ordering_client.get_suggested_params()

        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        transactions = [
            transaction.ApplicationCallTxn(
                sender=new_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.ordering_client.app_id,
                app_args=[
                    "cancel_recurring_order",
                    int_to_bytes(0)
                ],
                boxes=[
                    (0, order_box_name),
                    (self.ordering_client.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.user_address)),
                ],
                foreign_assets=[self.tiny_asset_id],
                foreign_apps=[self.registry_app_id]
            )
        ]

        # Cancel Recurring Order
        self.ledger.next_timestamp = now + DAY
        with self.assertRaises(LogicEvalError) as e:
            new_client._submit(transactions, additional_fees=2)
        self.assertEqual(e.exception.source['line'], 'assert(Txn.Sender == user_address)')


class ExecuteRecurringOrderTests(OrderProtocolBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e14))

    def test_execute_recurring_order_successful(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)
        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            min_target_amount=0,
            max_target_amount=0,
            interval=interval,
        )

        # Execute Recurring Order
        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        self.ledger.next_timestamp = now + DAY + 1
        filler_client.registry_user_opt_in()

        self.ledger.next_timestamp = now + DAY + 2
        self.manager_client.endorse(filler_client.user_address)

        fill_amount = 100_000
        bought_amount = 50_000
        fee_rate = 30
        fee_amount = int((bought_amount * fee_rate) / 10_000)
        collected_target_amount = bought_amount - fee_amount

        self.ledger.next_timestamp = now + DAY + DAY
        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.

        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.talgo_asset_id)

        self.ledger.set_account_balance(self.ordering_client.router_application_address, 100_000, self.tiny_asset_id)

        route_arg, pools_arg = encode_router_args(route=[self.talgo_asset_id, self.tiny_asset_id], pools=[])

        filler_client.execute_recurring_order(
            order_app_id=self.ordering_client.app_id,
            order_id=0,
            route_bytes=route_arg,
            pools_bytes=pools_arg,
            num_swaps=1,
            grouped_references=[
                {
                    "assets": [self.talgo_asset_id, self.tiny_asset_id],
                    "accounts": [],
                    "apps": [],
                }
            ],
        )

        block = self.ledger.last_block
        block_txns = block[b'txns']
        execute_txn = block_txns[0]

        events = decode_logs(execute_txn[b'dt'][b'lg'], ordering_events)

        self.assertEqual(len(events), 2)
        recurring_order = events[0]
        execute_order_event = events[1]

        self.assertEqual(execute_order_event['order_id'], 0)
        self.assertEqual(execute_order_event['filler_address'], filler_client.user_address)
        self.assertEqual(execute_order_event['fill_amount'], fill_amount)
        self.assertEqual(execute_order_event['bought_amount'], bought_amount)

        self.assertEqual(recurring_order['user_address'], self.user_address)
        self.assertEqual(recurring_order['order_id'], 0)
        self.assertEqual(recurring_order['asset_id'], self.talgo_asset_id)
        self.assertEqual(recurring_order['amount'], 100_000)
        self.assertEqual(recurring_order['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(recurring_order['collected_target_amount'], collected_target_amount)
        self.assertEqual(recurring_order['remaining_recurrences'], target_recurrence - 1)
        self.assertEqual(recurring_order['interval'], interval)
        self.assertEqual(recurring_order['fee_rate'], 30)
        self.assertEqual(recurring_order['last_fill_timestamp'], now + DAY + DAY)
        self.assertEqual(recurring_order['creation_timestamp'], now + DAY)

        recurring_order = self.ordering_client.get_box(self.ordering_client.get_recurring_order_box_name(0), "RecurringOrder")
        self.assertEqual(recurring_order.asset_id, self.talgo_asset_id)
        self.assertEqual(recurring_order.amount, 100_000)
        self.assertEqual(recurring_order.target_asset_id, self.tiny_asset_id)
        self.assertEqual(recurring_order.collected_target_amount, collected_target_amount)
        self.assertEqual(recurring_order.remaining_recurrences, target_recurrence - 1)
        self.assertEqual(recurring_order.interval, interval)
        self.assertEqual(recurring_order.fee_rate, 30)
        self.assertEqual(recurring_order.last_fill_timestamp, now + DAY + DAY)
        self.assertEqual(recurring_order.creation_timestamp, now + DAY)

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
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            min_target_amount=0,
            max_target_amount=0,
            interval=interval,
        )

        # Execute Recurring Order
        filler_client = self.get_new_user_client()

        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.talgo_asset_id)

        self.ledger.set_account_balance(self.ordering_client.router_application_address, 100_000, self.tiny_asset_id)

        route_arg, pools_arg = encode_router_args(route=[self.talgo_asset_id, self.tiny_asset_id], pools=[])

        with self.assertRaises(LogicEvalError) as e:
            filler_client.execute_recurring_order(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                route_bytes=route_arg,
                pools_bytes=pools_arg,
                num_swaps=1,
                grouped_references=[
                    {
                        "assets": [self.talgo_asset_id, self.tiny_asset_id],
                        "accounts": [],
                        "apps": [],
                    }
                ],
            )
        self.assertEqual(e.exception.source['line'], '_, is_endorsed = app_local_get_ex(user_address, app_global_get(REGISTRY_APP_ID_KEY), IS_ENDORSED_KEY)')

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
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            interval=interval
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

        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.talgo_asset_id)

        self.ledger.set_account_balance(self.ordering_client.router_application_address, 1_000_000, self.tiny_asset_id)

        filled_amount = 0
        fill_amount = 100_000
        collected_target_amount = 0
        for current_recurrence in range(target_recurrence):
            bought_amount = 50_000

            route_arg, pools_arg = encode_router_args(route=[self.talgo_asset_id, self.tiny_asset_id], pools=[])

            self.ledger.next_timestamp = now + DAY + DAY * (current_recurrence + 1)
            filler_client.execute_recurring_order(
                order_app_id=self.ordering_client.app_id,
                order_id=0,
                route_bytes=route_arg,
                pools_bytes=pools_arg,
                num_swaps=1,
                grouped_references=[
                    {
                        "assets": [self.talgo_asset_id, self.tiny_asset_id],
                        "accounts": [self.user_address],
                        "apps": [],
                    }
                ],
                extra_txns=1,
            )

            filled_amount += fill_amount

            fee_rate = 30
            fee_amount = int((bought_amount * fee_rate) / 10_000)
            collected_target_amount += (bought_amount - fee_amount)

            # Box is deleted.
            if (current_recurrence + 1) == target_recurrence:
                continue

            recurring_order = self.ordering_client.get_box(self.ordering_client.get_recurring_order_box_name(0), "RecurringOrder")
            self.assertEqual(recurring_order.asset_id, self.talgo_asset_id)
            self.assertEqual(recurring_order.amount, 100_000)
            self.assertEqual(recurring_order.target_asset_id, self.tiny_asset_id)
            self.assertEqual(recurring_order.collected_target_amount, collected_target_amount)
            self.assertEqual(recurring_order.remaining_recurrences, target_recurrence - (current_recurrence + 1))
            self.assertEqual(recurring_order.interval, interval)
            self.assertEqual(recurring_order.fee_rate, 30)
            self.assertEqual(recurring_order.last_fill_timestamp, now + DAY + DAY * (current_recurrence + 1))
            self.assertEqual(recurring_order.creation_timestamp, now + DAY)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        execute_txn = block_txns[0]

        events = decode_logs(execute_txn[b'dt'][b'lg'], ordering_events)

        self.assertEqual(len(events), 2)
        recurring_order_event = events[0] 
        execute_order_event = events[1]

        self.assertEqual(recurring_order_event['user_address'], self.user_address)
        self.assertEqual(recurring_order_event['order_id'], 0)
        self.assertEqual(recurring_order_event['asset_id'], self.talgo_asset_id)
        self.assertEqual(recurring_order_event['amount'], 100_000)
        self.assertEqual(recurring_order_event['target_asset_id'], self.tiny_asset_id)
        self.assertEqual(recurring_order_event['collected_target_amount'], collected_target_amount)
        self.assertEqual(recurring_order_event['remaining_recurrences'], 0)
        self.assertEqual(recurring_order_event['interval'], interval)
        self.assertEqual(recurring_order_event['fee_rate'], 30)
        self.assertEqual(recurring_order_event['last_fill_timestamp'], now + DAY + DAY * (current_recurrence + 1))
        self.assertEqual(recurring_order_event['creation_timestamp'], now + DAY)

        self.assertEqual(execute_order_event['user_address'], self.user_address)
        self.assertEqual(execute_order_event['order_id'], 0)
        self.assertEqual(execute_order_event['filler_address'], filler_client.user_address)
        self.assertEqual(execute_order_event['fill_amount'], fill_amount)
        self.assertEqual(execute_order_event['bought_amount'], bought_amount)

    def test_recurrence_time_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)
        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            min_target_amount=0,
            max_target_amount=0,
            interval=interval,
        )

        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        self.ledger.next_timestamp = now + DAY + 1
        filler_client.registry_user_opt_in()

        self.ledger.next_timestamp = now + DAY + 2
        self.manager_client.endorse(filler_client.user_address)

        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.

        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.talgo_asset_id)

        self.ledger.set_account_balance(self.ordering_client.router_application_address, 100_000, self.tiny_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()

        route_arg, pools_arg = encode_router_args(route=[self.talgo_asset_id, self.tiny_asset_id], pools=[])
        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        transactions = [
            transaction.ApplicationCallTxn(
                sender=filler_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.ordering_client.app_id,
                app_args=[
                    "execute_recurring_order",
                    0,
                    route_arg,
                    pools_arg,
                    1,
                ],
                boxes=[
                    (0, order_box_name),
                    (self.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.ordering_client.user_address)),
                ],
                accounts=[self.ordering_client.registry_application_address, self.ordering_client.user_address],
                foreign_assets=[self.talgo_asset_id, self.tiny_asset_id],
                foreign_apps=[self.ordering_client.registry_app_id, self.ordering_client.router_app_id],
            )
        ]

        # Execute Recurring Order
        # Mock the filling.
        order = RecurringOrder(bytearray(self.ordering_client.get_box(order_box_name, "RecurringOrder")._data))
        order.last_fill_timestamp = now + DAY + DAY
        order.remaining_recurrences = order.remaining_recurrences - 1
        self.ledger.set_box(self.ordering_client.app_id, key=order_box_name, value=order._data)

        self.ledger.next_timestamp = now + DAY + 2 * DAY - 1
        with self.assertRaises(LogicEvalError) as e:
            filler_client._submit(transactions, additional_fees=5)
        self.assertEqual(e.exception.source['line'], 'assert(Global.LatestTimestamp >= (order.last_fill_timestamp + order.interval))')

    def test_insufficient_received_amount_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)
        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            min_target_amount=50_001,
            max_target_amount=0,
            interval=interval,
        )

        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        self.ledger.next_timestamp = now + DAY + 1
        filler_client.registry_user_opt_in()

        self.ledger.next_timestamp = now + DAY + 2
        self.manager_client.endorse(filler_client.user_address)

        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.

        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.talgo_asset_id)

        self.ledger.set_account_balance(self.ordering_client.router_application_address, 100_000, self.tiny_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()

        route_arg, pools_arg = encode_router_args(route=[self.talgo_asset_id, self.tiny_asset_id], pools=[])
        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        transactions = [
            transaction.ApplicationCallTxn(
                sender=filler_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.ordering_client.app_id,
                app_args=[
                    "execute_recurring_order",
                    0,
                    route_arg,
                    pools_arg,
                    1,
                ],
                boxes=[
                    (0, order_box_name),
                    (self.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.ordering_client.user_address)),
                ],
                accounts=[self.ordering_client.registry_application_address, self.ordering_client.user_address],
                foreign_assets=[self.talgo_asset_id, self.tiny_asset_id],
                foreign_apps=[self.ordering_client.registry_app_id, self.ordering_client.router_app_id],
            )
        ]

        # Execute Recurring Order
        self.ledger.next_timestamp = now + DAY + DAY
        with self.assertRaises(LogicEvalError) as e:
            filler_client._submit(transactions, additional_fees=5)
        self.assertEqual(e.exception.source['line'], 'assert((received_amount >= order.min_target_amount) && (received_amount <= order.max_target_amount))')

    def test_incorrect_route_target_asset_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)
        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            min_target_amount=0,
            max_target_amount=0,
            interval=interval,
        )

        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        self.ledger.next_timestamp = now + DAY + 1
        filler_client.registry_user_opt_in()

        self.ledger.next_timestamp = now + DAY + 2
        self.manager_client.endorse(filler_client.user_address)

        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.

        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.talgo_asset_id)

        self.ledger.set_account_balance(self.ordering_client.router_application_address, 100_000, self.tiny_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()

        route_arg, pools_arg = encode_router_args(route=[self.talgo_asset_id, 0], pools=[])
        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        transactions = [
            transaction.ApplicationCallTxn(
                sender=filler_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.ordering_client.app_id,
                app_args=[
                    "execute_recurring_order",
                    0,
                    route_arg,
                    pools_arg,
                    1,
                ],
                boxes=[
                    (0, order_box_name),
                    (self.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.ordering_client.user_address)),
                ],
                accounts=[self.ordering_client.registry_application_address, self.ordering_client.user_address],
                foreign_assets=[self.talgo_asset_id, self.tiny_asset_id],
                foreign_apps=[self.ordering_client.registry_app_id, self.ordering_client.router_app_id],
            )
        ]

        # Execute Recurring Order
        self.ledger.next_timestamp = now + DAY + DAY
        with self.assertRaises(LogicEvalError) as e:
            filler_client._submit(transactions, additional_fees=5)
        self.assertEqual(e.exception.source['line'], 'assert(route[swaps] == order.target_asset_id)')


    def test_incorrect_route_asset_fail(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)
        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Create order app for user.
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            min_target_amount=0,
            max_target_amount=0,
            interval=interval,
        )

        filler_client = self.get_new_user_client()
        self.ledger.opt_in_asset(filler_client.user_address, self.talgo_asset_id)
        self.ledger.set_account_balance(filler_client.user_address, 15_000, self.tiny_asset_id)

        self.ledger.next_timestamp = now + DAY + 1
        filler_client.registry_user_opt_in()

        self.ledger.next_timestamp = now + DAY + 2
        self.manager_client.endorse(filler_client.user_address)

        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.

        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.talgo_asset_id)

        self.ledger.set_account_balance(self.ordering_client.router_application_address, 100_000, self.tiny_asset_id)

        # Prepare transactions.
        sp = self.ordering_client.get_suggested_params()

        route_arg, pools_arg = encode_router_args(route=[0, self.tiny_asset_id], pools=[])
        order_box_name = self.ordering_client.get_recurring_order_box_name(0)
        transactions = [
            transaction.ApplicationCallTxn(
                sender=filler_client.user_address,
                on_complete=transaction.OnComplete.NoOpOC,
                sp=sp,
                index=self.ordering_client.app_id,
                app_args=[
                    "execute_recurring_order",
                    0,
                    route_arg,
                    pools_arg,
                    1,
                ],
                boxes=[
                    (0, order_box_name),
                    (self.registry_app_id, self.ordering_client.get_registry_entry_box_name(self.ordering_client.user_address)),
                ],
                accounts=[self.ordering_client.registry_application_address, self.ordering_client.user_address],
                foreign_assets=[self.talgo_asset_id, self.tiny_asset_id],
                foreign_apps=[self.ordering_client.registry_app_id, self.ordering_client.router_app_id],
            )
        ]

        # Execute Recurring Order
        self.ledger.next_timestamp = now + DAY + DAY
        with self.assertRaises(LogicEvalError) as e:
            filler_client._submit(transactions, additional_fees=5)
        self.assertEqual(e.exception.source['line'], 'assert(route[0] == order.asset_id)')


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
        self.ordering_client = self.create_order_app(self.app_id, self.user_address)
        self.ledger.set_account_balance(self.ordering_client.application_address, 10_000_000)

        # Put Recurring Order
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.application_address, self.talgo_asset_id)
        self.ledger.set_account_balance(self.user_address, 700_000, self.talgo_asset_id)

        target_recurrence = 7
        interval = DAY
        self.ledger.next_timestamp = now + DAY
        self.ordering_client.put_recurring_order(
            asset_id=self.talgo_asset_id,
            amount=100_000,
            target_asset_id=self.tiny_asset_id,
            target_recurrence=target_recurrence,
            min_target_amount=0,
            max_target_amount=0,
            interval=interval,
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

        fill_amount = 100_000
        bought_amount = 50_000
        fee_rate = 30
        fee_amount = int((bought_amount * fee_rate) / 10_000)
        collected_target_amount = bought_amount - fee_amount

        self.ledger.next_timestamp = now + DAY + DAY
        self.ledger.opt_in_asset(self.ordering_client.registry_application_address, self.tiny_asset_id)  # TODO: Move this optin to client.
        self.ledger.opt_in_asset(self.ordering_client.user_address, self.tiny_asset_id)  # TODO: Also add this to client.

        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.tiny_asset_id)
        self.ledger.opt_in_asset(self.ordering_client.router_application_address, self.talgo_asset_id)

        self.ledger.set_account_balance(self.ordering_client.router_application_address, 100_000, self.tiny_asset_id)

        route_arg, pools_arg = encode_router_args(route=[self.talgo_asset_id, self.tiny_asset_id], pools=[])

        filler_client.execute_recurring_order(
            order_app_id=self.ordering_client.app_id,
            order_id=0,
            route_bytes=route_arg,
            pools_bytes=pools_arg,
            num_swaps=1,
            grouped_references=[
                {
                    "assets": [self.talgo_asset_id, self.tiny_asset_id],
                    "accounts": [],
                    "apps": [],
                }
            ],
        )

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
        self.assertEqual(recurring_order_event['collected_target_amount'], 0)
        self.assertEqual(recurring_order_event['remaining_recurrences'], target_recurrence - 1)
        self.assertEqual(recurring_order_event['interval'], interval)
        self.assertEqual(recurring_order_event['fee_rate'], 30)
        self.assertEqual(recurring_order_event['last_fill_timestamp'], now + DAY + DAY)
        self.assertEqual(recurring_order_event['creation_timestamp'], now + DAY)

        self.assertEqual(collect_event["order_id"], 0)
        self.assertEqual(collect_event["collected_target_amount"], collected_target_amount)

        recurring_order = self.ordering_client.get_box(self.ordering_client.get_recurring_order_box_name(0), "RecurringOrder")
        self.assertEqual(recurring_order.asset_id, self.talgo_asset_id)
        self.assertEqual(recurring_order.amount, 100_000)
        self.assertEqual(recurring_order.target_asset_id, self.tiny_asset_id)
        self.assertEqual(recurring_order.collected_target_amount, 0)
        self.assertEqual(recurring_order.remaining_recurrences, target_recurrence - 1)
        self.assertEqual(recurring_order.interval, interval)
        self.assertEqual(recurring_order.fee_rate, 30)
        self.assertEqual(recurring_order.last_fill_timestamp, now + DAY + DAY)
        self.assertEqual(recurring_order.creation_timestamp, now + DAY)

        inner_txns = collect_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 1)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], collected_target_amount)

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
        self.ordering_client.put_trigger_order(
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
        bought_amount = (15_000 // 2)
        fee_rate = 30
        fee_amount = int((bought_amount * fee_rate) / 10_000)
        collected_target_amount = bought_amount - fee_amount
        sp = filler_client.get_suggested_params()
        transactions = [
            filler_client.prepare_start_execute_trigger_order_transaction(
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
                amt=bought_amount,
                index=self.tiny_asset_id
            ),
            filler_client.prepare_end_execute_trigger_order_transaction(
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
        filler_client._submit(transactions, additional_fees=4)

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
        self.assertEqual(collect_event["collected_target_amount"], collected_target_amount)

        order = self.ordering_client.get_box(self.ordering_client.get_order_box_name(0), "TriggerOrder")
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

        inner_txns = collect_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 1)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.user_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], collected_target_amount)
