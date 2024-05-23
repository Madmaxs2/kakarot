from collections import namedtuple

import pytest
import pytest_asyncio
from eth_utils import keccak
from starknet_py.net.full_node_client import FullNodeClient
from starkware.starknet.public.abi import get_storage_var_address

Wallet = namedtuple("Wallet", ["address", "private_key", "starknet_contract"])

TOTAL_SUPPLY = 10000 * 10**18
TEST_AMOUNT = 10 * 10**18


@pytest.fixture(scope="session")
async def class_hashes():
    """
    All declared class hashes.
    """
    from kakarot_scripts.utils.starknet import get_declarations

    return get_declarations()


@pytest_asyncio.fixture(scope="module")
async def new_account(max_fee):
    """
    Return a random funded new account.
    """
    from kakarot_scripts.utils.kakarot import get_eoa
    from kakarot_scripts.utils.starknet import fund_address
    from tests.utils.helpers import generate_random_private_key

    private_key = generate_random_private_key()
    account = Wallet(
        address=private_key.public_key.to_checksum_address(),
        private_key=private_key,
        # deploying an account with enough ETH to pass ~10 tx
        starknet_contract=await get_eoa(private_key, amount=100 * max_fee / 1e18),
    )
    await fund_address(account.starknet_contract.address, 10)
    return account


@pytest_asyncio.fixture(scope="function")
async def counter(deploy_contract, new_account):
    return await deploy_contract(
        "PlainOpcodes",
        "Counter",
        caller_eoa=new_account.starknet_contract,
    )


@pytest_asyncio.fixture(scope="module")
async def caller(deploy_contract, owner):
    return await deploy_contract(
        "PlainOpcodes",
        "Caller",
        caller_eoa=owner.starknet_contract,
    )


@pytest.fixture(autouse=True)
async def cleanup(invoke, class_hashes):
    yield

    await invoke(
        "kakarot",
        "set_account_contract_class_hash",
        class_hashes["account_contract"],
    )
    await invoke(
        "kakarot", "set_cairo1_helpers_class_hash", class_hashes["Cairo1Helpers"]
    )


async def assert_counter_transaction_success(counter, new_account):
    """
    Assert that the transaction sent, other than upgrading the account contract, is successful.
    """
    prev_count = await counter.count()
    await counter.inc(caller_eoa=new_account.starknet_contract)
    assert await counter.count() == prev_count + 1


async def assert_caller_contract_increases_counter(caller, counter, new_account):
    """
    Assert that the transaction sent, other than upgrading the account contract, is successful.
    """
    prev_count = await counter.count()
    inc_selector = keccak(b"inc()")[0:4]
    await caller.call(
        counter.address, inc_selector, caller_eoa=new_account.starknet_contract
    )
    assert await counter.count() == prev_count + 1


@pytest.mark.asyncio(scope="session")
@pytest.mark.AccountContract
class TestAccount:
    class TestAutoUpgradeOnTransaction:
        async def test_should_upgrade_outdated_account_on_transfer(
            self,
            starknet: FullNodeClient,
            invoke,
            counter,
            new_account,
            class_hashes,
            cleanup,
        ):
            prev_class = await starknet.get_class_hash_at(
                new_account.starknet_contract.address
            )
            target_class = class_hashes["account_contract_fixture"]
            assert prev_class != target_class
            assert prev_class == class_hashes["account_contract"]

            await invoke(
                "kakarot",
                "set_account_contract_class_hash",
                target_class,
            )

            await assert_counter_transaction_success(counter, new_account)

            new_class = await starknet.get_class_hash_at(
                new_account.starknet_contract.address
            )
            assert new_class == target_class

        async def test_should_update_cairo1_helpers_class(
            self,
            starknet: FullNodeClient,
            invoke,
            counter,
            new_account,
            class_hashes,
        ):
            prev_cairo1_helpers_class = await starknet.get_storage_at(
                new_account.starknet_contract.address,
                get_storage_var_address("Account_cairo1_helpers_class_hash"),
            )
            target_class = class_hashes["Cairo1HelpersFixture"]
            assert prev_cairo1_helpers_class != target_class

            await invoke(
                "kakarot",
                "set_account_contract_class_hash",
                class_hashes["account_contract_fixture"],
            )
            await invoke("kakarot", "set_cairo1_helpers_class_hash", target_class)

            await assert_counter_transaction_success(counter, new_account)

            assert (
                await starknet.get_storage_at(
                    new_account.starknet_contract.address,
                    get_storage_var_address("Account_cairo1_helpers_class_hash"),
                )
                == target_class
            )

    class TestAutoUpgradeContracts:
        async def test_should_upgrade_outdated_contract_transaction_target(
            self,
            starknet: FullNodeClient,
            invoke,
            call,
            counter,
            new_account,
            class_hashes,
        ):
            counter_starknet_address = (
                await call(
                    "kakarot",
                    "get_starknet_address",
                    int(counter.address, 16),
                )
            ).starknet_address
            prev_class = await starknet.get_class_hash_at(counter_starknet_address)
            target_class = class_hashes["account_contract_fixture"]
            assert prev_class != target_class
            assert prev_class == class_hashes["account_contract"]

            await invoke(
                "kakarot",
                "set_account_contract_class_hash",
                target_class,
            )

            await assert_counter_transaction_success(counter, new_account)

            new_class = await starknet.get_class_hash_at(counter_starknet_address)
            assert new_class == target_class

        async def test_should_upgrade_outdated_contract_called_contract(
            self,
            starknet: FullNodeClient,
            invoke,
            counter,
            call,
            caller,
            new_account,
            class_hashes,
            cleanup,
        ):
            counter_starknet_address = (
                await call(
                    "kakarot",
                    "get_starknet_address",
                    int(counter.address, 16),
                )
            ).starknet_address
            prev_class = await starknet.get_class_hash_at(counter_starknet_address)
            target_class = class_hashes["account_contract_fixture"]
            assert prev_class != target_class
            assert prev_class == class_hashes["account_contract"]

            await invoke(
                "kakarot",
                "set_account_contract_class_hash",
                target_class,
            )

            await assert_caller_contract_increases_counter(caller, counter, new_account)

            new_class = await starknet.get_class_hash_at(counter_starknet_address)
            assert new_class == target_class
