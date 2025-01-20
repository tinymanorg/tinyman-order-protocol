from base64 import b64encode
from algojig import get_suggested_params
from algosdk.v2client.algod import AlgodClient


class JigAlgod():
    def __init__(self, ledger) -> AlgodClient:
        self.ledger = ledger

    def send_transactions(self, transactions):
        try:
            timestamp = self.ledger.next_timestamp
        except Exception:
            timestamp = None

        if timestamp:
            block = self.ledger.eval_transactions(transactions, block_timestamp=timestamp)
        else:
            block = self.ledger.eval_transactions(transactions)
        self.ledger.last_block = block
        return transactions[0].get_txid()

    def pending_transaction_info(self, txid):
        return {"confirmed-round": 1}
    
    def status_after_block(self, round):
        return {}
    
    def status(self):
        return {"last-round": 1}
    
    def suggested_params(self):
        return get_suggested_params()
    
    def application_box_by_name(self, application_id: int, box_name: bytes):
        value = self.ledger.boxes[application_id][box_name]
        value = bytes(value)
        response = {
            "name": b64encode(box_name),
            "round": 1,
            "value": b64encode(value)

        }
        return response

    def application_info(self, application_id):
        global_state = []
        for k, v in self.ledger.global_states.get(application_id, {}).items():
            value = {}
            if type(v) == bytes:
                value["bytes"] = b64encode(v)
                value["uint"] = 0
                value["type"] = 1
            else:
                value["bytes"] = ""
                value["uint"] = v
                value["type"] = 2
            global_state.append({"key": b64encode(k).decode(), "value": value})
        result = {
            "id": application_id,
            "params": {
                "global-state": global_state
            }
        }
        return result
