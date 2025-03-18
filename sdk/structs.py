from pathlib import Path
from sdk.struct import register_struct_file, get_struct

SDK_DIR = Path(__file__).parent


register_struct_file(filepath=SDK_DIR / "order_structs.json")
register_struct_file(filepath=SDK_DIR / "registry_structs.json")


Order = get_struct("Order")
Entry = get_struct("Entry")
RecurringOrder = get_struct("RecurringOrder")
