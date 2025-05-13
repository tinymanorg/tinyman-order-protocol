import unittest

from algosdk.account import generate_account
from algosdk.encoding import decode_address
from algosdk.logic import get_application_address
from algojig import get_suggested_params
from algojig.ledger import JigLedger

from tinyman.utils import int_to_bytes, get_global_state
from tinyman.governance.vault.constants import MAX_LOCK_TIME

from sdk.constants import *
from sdk.client import OrderingClient, RegistryClient
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
        self.vault_app_id = 1003
        self.ledger.create_app(app_id=self.vault_app_id, approval_program=vault_approval_program, creator=self.app_creator_address, local_ints=0, local_bytes=0, global_ints=4, global_bytes=0)
        self.ledger.set_global_state(self.vault_app_id, {"tiny_asset_id": self.tiny_asset_id, "total_locked_amount": 0, "total_power_count": 0, "last_total_power_timestamp": 0})
        self.ledger.set_account_balance(get_application_address(self.vault_app_id), 300_000)
        self.ledger.boxes[self.vault_app_id] = {}

        self.algod = JigAlgod(self.ledger)
        self.ordering_client = OrderingClient(self.algod, self.registry_app_id, self.vault_app_id, self.user_address, self.user_sk)
        self.manager_client = RegistryClient(self.algod, self.registry_app_id, self.vault_app_id, self.manager_address, self.manager_sk)

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
                MANAGER_KEY: decode_address(self.manager_address),
                VAULT_APP_ID_KEY: self.vault_app_id,
                ORDER_FEE_RATE_KEY: 30,
                GOVERNOR_ORDER_FEE_RATE_KEY: 15,
                GOVERNOR_FEE_RATE_POWER_THRESHOLD: 500_000_000,
            }
        )

        if app_id not in self.ledger.boxes:
            self.ledger.boxes[app_id] = {}

    def create_order_app(self, app_id, app_creator_address):
        self.ledger.create_app(
            app_id=app_id,
            approval_program=order_approval_program,
            extra_pages=3,
            creator=app_creator_address,
            local_ints=order_app_local_schema.num_uints,
            local_bytes=order_app_local_schema.num_byte_slices,
            global_ints=order_app_global_schema.num_uints,
            global_bytes=order_app_global_schema.num_byte_slices
        )

        self.ledger.global_states[app_id] = {
            USER_ADDRESS_KEY: decode_address(app_creator_address),
            REGISTRY_APP_ID_KEY: self.registry_app_id,
            REGISTRY_APP_ACCOUNT_ADDRESS_KEY: decode_address(self.register_application_address),
            VAULT_APP_ID_KEY: self.vault_app_id,
            VERSION_KEY: 1,
        }

        # Register the app.
        entry_box_name = self.ordering_client.get_registry_entry_box_name(app_creator_address)
        entry = Entry()
        entry.app_id = app_id

        self.ledger.set_box(self.registry_app_id, key=entry_box_name, value=entry._data)
        self.ledger.global_states[self.registry_app_id][ENTRY_COUNT_KEY] = self.ledger.global_states[self.registry_app_id].get(ENTRY_COUNT_KEY, 0) + 1

        return OrderingClient(self.algod, self.registry_app_id, self.vault_app_id, self.user_address, self.user_sk, self.app_id)

    def simulate_user_voting_power(self, account_address=None, locked_amount=510_000_000, lock_start_time = None, lock_end_time=None):
        """
        For MAX_LOCK_TIME, locked_amount is equivalent to voting power. Added +10_000_000 microunits for rounding errors and keeping the power enough over a time span.
        """

        now = int(datetime.now(tz=timezone.utc).timestamp())

        lock_start_time = lock_start_time or now
        lock_end_time = lock_end_time or (lock_start_time + MAX_LOCK_TIME)
        assert(lock_start_time < lock_end_time)

        account_address = account_address or self.user_address
        account_state = int_to_bytes(locked_amount) + int_to_bytes(lock_end_time) + int_to_bytes(1) + int_to_bytes(0)

        self.ledger.set_box(self.vault_app_id, key=decode_address(account_address), value=account_state)

    def get_new_ordering_client(self, user_sk, user_address):
        return OrderingClient(self.algod, self.registry_app_id, self.vault_app_id, user_address, user_sk)

    def get_new_registry_client(self, user_sk, user_address):
        return RegistryClient(self.algod, self.registry_app_id, self.vault_app_id, user_address, user_sk)

    def get_new_user(self):
        user_sk, user_address = generate_account()
        self.ledger.set_account_balance(user_address, 100_000_000)

        return user_sk, user_address

    def get_new_user_client(self):
        user_sk, user_address = self.get_new_user()
        return self.get_new_ordering_client(user_sk, user_address)

    def get_new_manager_client(self):
        user_sk, user_address = self.get_new_user()
        return self.get_new_registry_client(user_sk, user_address)
