from datetime import datetime, timezone

from algojig.exceptions import LogicEvalError
from algosdk import transaction
from algosdk.account import generate_account
from algosdk.encoding import decode_address, encode_address
from algosdk.transaction import OnComplete

from tinyman.utils import TransactionGroup

from sdk.constants import *
from sdk.client import RegistryClient
from sdk.event import decode_logs
from sdk.events import registry_events

from tests.constants import registry_approval_program, registry_clear_state_program, WEEK, DAY, registry_app_global_schema, registry_app_local_schema, registry_app_extra_pages
from tests.core import OrderProtocolBaseTestCase


class OrderProtocolRegistryTests(OrderProtocolBaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.ledger.set_account_balance(self.user_address, int(1e14))

    def test_create_registry_app(self):
        account_sk, account_address = generate_account()

        self.ledger.set_account_balance(account_address, 10_000_000)
        transactions = [
            transaction.ApplicationCreateTxn(
                sender=account_address,
                sp=self.sp,
                on_complete=OnComplete.NoOpOC,
                app_args=[b"create_application", self.vault_app_id, decode_address(self.manager_address)],
                approval_program=registry_approval_program.bytecode,
                clear_program=registry_clear_state_program.bytecode,
                global_schema=registry_app_global_schema,
                local_schema=registry_app_local_schema,
                extra_pages=registry_app_extra_pages,
            ),
        ]

        txn_group = TransactionGroup(transactions)
        txn_group.sign_with_private_key(account_address, account_sk)
        block = self.ledger.eval_transactions(txn_group.signed_transactions)
        block_txns = block[b'txns']
        app_id = block_txns[0][b'apid']

        self.assertDictEqual(
            self.ledger.global_states[app_id],
            {
                MANAGER_KEY: decode_address(self.manager_address),
                VAULT_APP_ID_KEY: self.vault_app_id,
                ORDER_FEE_RATE_KEY: 30,
                GOVERNOR_ORDER_FEE_RATE_KEY: 15,
                GOVERNOR_FEE_RATE_POWER_THRESHOLD: 500_000_000,
            }
        )

    def test_create_entry(self):
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

    def test_propose_and_accept_manager(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        user_1_client = self.get_new_manager_client()

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Propose Manager
        self.ledger.next_timestamp = now + DAY
        self.manager_client.propose_manager(user_1_client.user_address)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        propose_manager_txn = block_txns[0]

        self.assertEqual(propose_manager_txn[b'dt'][b'gd'][PROPOSED_MANAGER_KEY][b'bs'], decode_address(user_1_client.user_address))

        self.assertDictEqual(
            self.ledger.global_states[self.registry_app_id],
            {
                MANAGER_KEY: decode_address(self.manager_address),
                PROPOSED_MANAGER_KEY: decode_address(user_1_client.user_address),
                VAULT_APP_ID_KEY: self.vault_app_id,
                ORDER_FEE_RATE_KEY: 30,
                GOVERNOR_ORDER_FEE_RATE_KEY: 15,
                GOVERNOR_FEE_RATE_POWER_THRESHOLD: 500_000_000,
            }
        )

        # Accept Manager
        self.ledger.next_timestamp = now + DAY + 1
        user_1_client.accept_manager()

        block = self.ledger.last_block
        block_txns = block[b'txns']
        propose_manager_txn = block_txns[0]

        self.assertEqual(propose_manager_txn[b'dt'][b'gd'][PROPOSED_MANAGER_KEY][b'at'], 1)

        self.assertDictEqual(
            self.ledger.global_states[self.registry_app_id],
            {
                MANAGER_KEY: decode_address(user_1_client.user_address),
                PROPOSED_MANAGER_KEY: None,
                VAULT_APP_ID_KEY: self.vault_app_id,
                ORDER_FEE_RATE_KEY: 30,
                GOVERNOR_ORDER_FEE_RATE_KEY: 15,
                GOVERNOR_FEE_RATE_POWER_THRESHOLD: 500_000_000,
            }
        )

    def test_asset_opt_in(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Asset Opt In
        self.ledger.next_timestamp = now + DAY
        self.manager_client.asset_opt_in(asset_id=self.talgo_asset_id)

        self.assertEqual(self.ledger.accounts[self.register_application_address]["balances"][self.talgo_asset_id][0], 0)

    def test_set_order_fee_rate(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Asset Opt In
        self.ledger.next_timestamp = now + DAY
        self.manager_client.set_order_fee_rate(50)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        set_order_fee_rate_txn = block_txns[0]

        self.assertEqual(set_order_fee_rate_txn[b'dt'][b'gd'][ORDER_FEE_RATE_KEY][b'ui'], 50)

        self.assertDictEqual(
            self.ledger.global_states[self.registry_app_id],
            {
                MANAGER_KEY: decode_address(self.manager_address),
                VAULT_APP_ID_KEY: self.vault_app_id,
                ORDER_FEE_RATE_KEY: 50,
                GOVERNOR_ORDER_FEE_RATE_KEY: 15,
                GOVERNOR_FEE_RATE_POWER_THRESHOLD: 500_000_000,
            }
        )

    def test_set_governor_order_fee_rate(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Asset Opt In
        self.ledger.next_timestamp = now + DAY
        self.manager_client.set_governor_order_fee_rate(20)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        set_gov_order_fee_rate_txn = block_txns[0]

        self.assertEqual(set_gov_order_fee_rate_txn[b'dt'][b'gd'][GOVERNOR_ORDER_FEE_RATE_KEY][b'ui'], 20)

        self.assertDictEqual(
            self.ledger.global_states[self.registry_app_id],
            {
                MANAGER_KEY: decode_address(self.manager_address),
                VAULT_APP_ID_KEY: self.vault_app_id,
                ORDER_FEE_RATE_KEY: 30,
                GOVERNOR_ORDER_FEE_RATE_KEY: 20,
                GOVERNOR_FEE_RATE_POWER_THRESHOLD: 500_000_000,
            }
        )

    def test_set_governor_fee_rate_power_threshold(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        # Asset Opt In
        self.ledger.next_timestamp = now + DAY
        self.manager_client.set_governor_fee_rate_power_threshold(2_000_000_000)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        set_governor_fee_rate_power_threshold_txn = block_txns[0]

        self.assertEqual(set_governor_fee_rate_power_threshold_txn[b'dt'][b'gd'][GOVERNOR_FEE_RATE_POWER_THRESHOLD][b'ui'], 2_000_000_000)

        self.assertDictEqual(
            self.ledger.global_states[self.registry_app_id],
            {
                MANAGER_KEY: decode_address(self.manager_address),
                VAULT_APP_ID_KEY: self.vault_app_id,
                ORDER_FEE_RATE_KEY: 30,
                GOVERNOR_ORDER_FEE_RATE_KEY: 15,
                GOVERNOR_FEE_RATE_POWER_THRESHOLD: 2_000_000_000,
            }
        )

    def test_claim_fees(self):
        self.create_registry_app(self.registry_app_id, self.app_creator_address)
        self.ledger.set_account_balance(self.register_application_address, 10_000_000)

        now = int(datetime.now(tz=timezone.utc).timestamp())

        self.ledger.opt_in_asset(self.manager_address, self.tiny_asset_id)
        self.ledger.set_account_balance(self.register_application_address, 1000, self.tiny_asset_id)

        # Asset Opt In
        self.ledger.next_timestamp = now + DAY
        self.manager_client.claim_fees(self.tiny_asset_id)

        block = self.ledger.last_block
        block_txns = block[b'txns']
        claim_fees_txn = block_txns[0]

        # Inner Transaction Checks
        inner_txns = claim_fees_txn[b'dt'][b'itx']

        self.assertEqual(len(inner_txns), 1)
        self.assertEqual(inner_txns[0][b'txn'][b'type'], b'axfer')
        self.assertEqual(inner_txns[0][b'txn'][b'xaid'], self.tiny_asset_id)
        self.assertEqual(inner_txns[0][b'txn'][b'snd'], decode_address(self.ordering_client.registry_application_address))
        self.assertEqual(inner_txns[0][b'txn'][b'arcv'], decode_address(self.manager_address))
        self.assertEqual(inner_txns[0][b'txn'][b'aamt'], 1000)
