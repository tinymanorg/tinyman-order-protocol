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
                app_args=[b"create_application", decode_address(self.manager_address)],
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

