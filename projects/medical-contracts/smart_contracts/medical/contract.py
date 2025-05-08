from pyteal import *
from pyteal.ast import *

# Contract metadata
APP_NAME = "MedicalNFTPlatform"
VERSION = "1.0"

# Global state keys
UNITARY_PRICE_KEY = Bytes("unitaryPrice")
NFT_COUNT_KEY = Bytes("nftCount")
NFT_PREFIX = Bytes("nft_")  # Prefix for NFT metadata (e.g., nft_1, nft_2)

# Constants
MAX_NFTS = Int(100)  # Maximum NFTs the contract can manage
MIN_ALGO_BALANCE = Int(100000)  # Minimum balance for contract (0.1 ALGO)

class MedicalNFTContract:
    def __init__(self):
        self.unitary_price = App.globalGet(UNITARY_PRICE_KEY)  # Price to mint an NFT

    # Approval program
    def approval_program(self):
        # On creation: Initialize global state
        on_create = Seq([
            App.globalPut(UNITARY_PRICE_KEY, Int(1000000)),  # 1 ALGO in microAlgos
            App.globalPut(NFT_COUNT_KEY, Int(0)),  # Initialize NFT count
            Return(Int(1))
        ])

        # On opt-in: No special logic needed
        on_opt_in = Return(Int(1))

        # Mint NFT: Create an ASA and store metadata
        @Subroutine(TealType.none)
        def mint_nft(txn_index: TealType.uint64):
            file_hash = Txn.application_args[1]  # File hash (e.g., IPFS CID)
            nft_count = App.globalGet(NFT_COUNT_KEY)
            
            return Seq([
                # Validate payment
                Assert(
                    Gtxn[txn_index].type_enum() == TxnType.Payment,
                    comment="Must be a payment transaction"
                ),
                Assert(
                    Gtxn[txn_index].sender() == Txn.sender(),
                    comment="Payment sender must match app call sender"
                ),
                Assert(
                    Gtxn[txn_index].receiver() == Global.current_application_address(),
                    comment="Payment must be to app address"
                ),
                Assert(
                    Gtxn[txn_index].amount() >= self.unitary_price,
                    comment="Payment amount must match unitary price"
                ),
                # Validate NFT count
                Assert(
                    nft_count < MAX_NFTS,
                    comment="Maximum NFT limit reached"
                ),
                # Create ASA (NFT)
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetConfig,
                    TxnField.config_asset_total: Int(1),  # Single unit for NFT
                    TxnField.config_asset_decimals: Int(0),
                    TxnField.config_asset_unit_name: Bytes("MEDNFT"),
                    TxnField.config_asset_name: Concat(Bytes("MedicalNFT_"), Itob(nft_count + Int(1))),
                    TxnField.config_asset_manager: Global.current_application_address(),
                    TxnField.config_asset_clawback: Global.current_application_address(),
                }),
                InnerTxnBuilder.Submit(),
                # Store NFT metadata
                App.globalPut(
                    Concat(NFT_PREFIX, Itob(nft_count + Int(1))),
                    Concat(file_hash, Bytes(":"), Txn.sender())  # Store hash and owner
                ),
                App.globalPut(NFT_COUNT_KEY, nft_count + Int(1)),
            ])

        # Share NFT: Transfer NFT to another address
        @Subroutine(TealType.none)
        def share_nft():
            nft_id = Btoi(Txn.application_args[1])  # Asset ID
            recipient = Txn.application_args[2]  # Recipient address
            
            return Seq([
                # Validate caller is the creator
                Assert(
                    App.globalGet(Concat(NFT_PREFIX, Itob(nft_id))) != Bytes(""),
                    comment="NFT does not exist"
                ),
                # Perform asset transfer
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: nft_id,
                    TxnField.asset_receiver: recipient,
                    TxnField.asset_amount: Int(1),
                    TxnField.asset_sender: Global.current_application_address(),
                }),
                InnerTxnBuilder.Submit(),
                # Update owner in metadata
                App.globalPut(
                    Concat(NFT_PREFIX, Itob(nft_id)),
                    Concat(
                        Substring(App.globalGet(Concat(NFT_PREFIX, Itob(nft_id))), Int(0), Int(32)),
                        Bytes(":"),
                        recipient
                    )
                ),
            ])

        # Revoke NFT: Clawback NFT to original owner
        @Subroutine(TealType.none)
        def revoke_nft():
            nft_id = Btoi(Txn.application_args[1])  # Asset ID
            current_owner = Txn.accounts[1]  # Current owner address
            
            return Seq([
                # Validate caller is the creator
                Assert(
                    App.globalGet(Concat(NFT_PREFIX, Itob(nft_id))) != Bytes(""),
                    comment="NFT does not exist"
                ),
                # Perform clawback
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: nft_id,
                    TxnField.asset_receiver: Txn.sender(),
                    TxnField.asset_amount: Int(1),
                    TxnField.asset_sender: current_owner,
                }),
                InnerTxnBuilder.Submit(),
                # Update owner in metadata
                App.globalPut(
                    Concat(NFT_PREFIX, Itob(nft_id)),
                    Concat(
                        Substring(App.globalGet(Concat(NFT_PREFIX, Itob(nft_id))), Int(0), Int(32)),
                        Bytes(":"),
                        Txn.sender()
                    )
                ),
            ])

        # Get NFT Metadata: Read NFT details
        @Subroutine(TealType.bytes)
        def get_nft_metadata():
            nft_id = Btoi(Txn.application_args[1])  # NFT ID
            return App.globalGet(Concat(NFT_PREFIX, Itob(nft_id)))

        # Handle application calls
        program = Cond(
            [Txn.application_id() == Int(0), on_create],
            [Txn.on_completion() == OnComplete.OptIn, on_opt_in],
            [Txn.on_completion() == OnComplete.CloseOut, Return(Int(1))],
            [Txn.on_completion() == OnComplete.UpdateApplication, Return(Int(0))],  # Disallow updates
            [Txn.on_completion() == OnComplete.DeleteApplication, Return(Int(0))],  # Disallow deletion
            [Txn.application_args[0] == Bytes("mint"), mint_nft(Int(1))],
            [Txn.application_args[0] == Bytes("share"), share_nft()],
            [Txn.application_args[0] == Bytes("revoke"), revoke_nft()],
            [Txn.application_args[0] == Bytes("get_nft"), Return(get_nft_metadata())]
        )

        return program

    # Clear program
    def clear_program(self):
        return Return(Int(1))

# Compile and export contract
def compile_contract():
    contract = MedicalNFTContract()
    approval_teal = compileTeal(contract.approval_program(), mode=Mode.Application, version=6)
    clear_teal = compileTeal(contract.clear_program(), mode=Mode.Application, version=6)
    
    with open("medical_nft_approval.teal", "w") as f:
        f.write(approval_teal)
    with open("medical_nft_clear.teal", "w") as f:
        f.write(clear_teal)
    
    return approval_teal, clear_teal
