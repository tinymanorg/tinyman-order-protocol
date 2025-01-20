import unittest

from algosdk.account import generate_account
from algosdk.encoding import decode_address
from algosdk.logic import get_application_address
from algojig import get_suggested_params
from algojig.ledger import JigLedger

from tinyman.utils import int_to_bytes, get_global_state
from tinyman.governance.vault.constants import MAX_LOCK_TIME

from sdk.constants import *
from sdk.client import OrderingClient
from sdk.structs import Entry, Order

from tests.constants import *
from tests.utils import JigAlgod


class OrderProtocolBaseTestCase(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app_id = 8_000
        cls.registry_app_id = 9000

        cls.register_application_address = get_application_address(cls.registry_app_id)

        cls.app_creator_sk, cls.app_creator_address = generate_account()
        cls.manager_sk, cls.manager_address = generate_account()

        cls.tiny_asset_creator_sk, cls.tiny_asset_creator_address = generate_account()

        cls.user_sk, cls.user_address = ("ckFZbhsmsdIuT/jJlAG9MWGXN6sYpq1X9OKVbsGFeOYBChEy71FWSsru0yawsDx1bWtJE2UdV5nolNL6tUEzmA==", "AEFBCMXPKFLEVSXO2MTLBMB4OVWWWSITMUOVPGPISTJPVNKBGOMKU54THY")
        cls.sp = get_suggested_params()

    def setUp(self):
        self.ledger = JigLedger()
        self.ledger.set_account_balance(self.user_address, 100_000_000)
        self.ledger.set_account_balance(self.app_creator_address, 10_000_000)
        self.ledger.set_account_balance(self.manager_address, 10_000_000)
        self.ledger.set_account_balance(self.tiny_asset_creator_address, 10_000_000)

        # Create Test Assets
        self.tiny_asset_id = 1001
        self.ledger.create_asset(self.tiny_asset_id, dict(total=10**15, decimals=6, name="Tinyman", unit_name="TINY", creator=self.tiny_asset_creator_address))
        self.talgo_asset_id = 1004
        self.ledger.create_asset(self.talgo_asset_id,
            {
                "creator": self.tiny_asset_creator_address,
                "decimals": 6,
                "default-frozen": False,
                "name": "TALGO",
                "name-b64": "VEFMR08=",
                "reserve": self.tiny_asset_creator_address,
                "total": 10000000000000000,
                "unit-name": "TALGO",
                "unit-name-b64": "VEFMR08=",
                "url": "https://tinyman.org",
                "url-b64": "aHR0cHM6Ly90aW55bWFuLm9yZw=="
            }
        )

        # Set up vault.
        # self.ledger.create_app(app_id=self.vault_app_id, approval_program=vault_approval_program, creator=self.app_creator_address, local_ints=0, local_bytes=0, global_ints=4, global_bytes=0)
        # self.ledger.set_global_state(self.vault_app_id, {"tiny_asset_id": self.tiny_asset_id, "total_locked_amount": 0, "total_power_count": 0, "last_total_power_timestamp": 0})
        # self.ledger.set_account_balance(get_application_address(self.vault_app_id), 300_000)
        # self.ledger.boxes[self.vault_app_id] = {}

        self.algod = JigAlgod(self.ledger)
        self.ordering_client = OrderingClient(self.algod, self.registry_app_id, self.user_address, self.user_sk)

    def create_registry_app(self, app_id, app_creator_address):
        self.ledger.create_app(
            app_id=app_id,
            approval_program=registry_approval_program,
            creator=app_creator_address,
            local_ints=registry_app_local_schema.num_uints,
            local_bytes=registry_app_local_schema.num_byte_slices,
            global_ints=registry_app_global_schema.num_uints,
            global_bytes=registry_app_global_schema.num_byte_slices
        )

        self.ledger.set_global_state(
            app_id,
            {
                ENTRY_COUNT_KEY: 0,
                MANAGER_KEY: decode_address(self.manager_address),
            }
        )

        if app_id not in self.ledger.boxes:
            self.ledger.boxes[app_id] = {}

    def create_order_app(self, app_id, app_creator_address):
        self.ledger.create_app(
            app_id=app_id,
            approval_program=order_approval_program,
            creator=app_creator_address,
            local_ints=order_app_local_schema.num_uints,
            local_bytes=order_app_local_schema.num_byte_slices,
            global_ints=order_app_global_schema.num_uints,
            global_bytes=order_app_global_schema.num_byte_slices
        )

        self.ledger.global_states[app_id] = {
            MANAGER_KEY: decode_address(self.register_application_address),
            USER_ADDRESS_KEY: decode_address(app_creator_address)
        }

        # Register the app.
        entry_box_name = self.ordering_client.get_registry_entry_box_name(app_creator_address)
        entry = Entry()
        entry.app_id = app_id

        self.ledger.set_box(self.registry_app_id, key=entry_box_name, value=entry._data)
        self.ledger.global_states[self.registry_app_id][ENTRY_COUNT_KEY] = self.ledger.global_states[self.registry_app_id].get(ENTRY_COUNT_KEY, 0) + 1

        return OrderingClient(self.algod, self.registry_app_id, self.user_address, self.user_sk, app_id)
