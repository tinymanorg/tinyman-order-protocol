#pragma version 10
#tealish version git+https://github.com/Hipo/tealish.git@d7441973671cf6b79dd55843016892f4b86ceeba


struct Address:
    address: bytes[32]
end


router:
    noop
    swap
end


@public()
func noop():
    return
end


@public()
func swap(input_amount: int, output_amount: int, route: int[8], pools: Address[8], swaps: int):
    bytes user_address = Txn.Sender

    # Swap Route:input_asset_id -> intermediary_asset_id -> output_asset_id
    int input_asset_id = route[0]
    int output_asset_id = route[swaps]

    # Check input transaction
    assert(Txn.GroupIndex)
    int input_txn_index = Txn.GroupIndex - 1
    assert(Gtxn[input_txn_index].Sender == user_address)

    if Gtxn[input_txn_index].TypeEnum == Pay:
        assert(Gtxn[input_txn_index].Receiver == Global.CurrentApplicationAddress)
        assert(!input_asset_id)
        assert(Gtxn[input_txn_index].Amount == input_amount)
    elif Gtxn[input_txn_index].TypeEnum == Axfer:
        assert(Gtxn[input_txn_index].AssetReceiver == Global.CurrentApplicationAddress)
        assert(input_asset_id == Gtxn[input_txn_index].XferAsset)
        assert(Gtxn[input_txn_index].AssetAmount == input_amount)
    else:
        Error()
    end
    assert(input_amount)


    # FAKE SWAP
    int final_output_amount = input_amount / 2

    # Transfer output to user
    transfer(output_asset_id, final_output_amount, Global.CurrentApplicationAddress, user_address)

    log(ARC28Event("swap(uint64,uint64,uint64,uint64)", itob(input_asset_id), itob(output_asset_id), itob(input_amount), itob(final_output_amount)))
    return
end


func transfer(asset_id: int, amount: int, sender: bytes, receiver: bytes):
    if !asset_id:
        inner_txn:
            TypeEnum: Pay
            Sender: sender
            Receiver: receiver
            Amount: amount
            Fee: 0
        end
    else:
        inner_txn:
            TypeEnum: Axfer
            Sender: sender
            AssetReceiver: receiver
            AssetAmount: amount
            XferAsset: asset_id
            Fee: 0
        end
    end
    return
end
