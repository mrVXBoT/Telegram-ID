"""
tests.services.test_session_manager_stress
==========================================
Empirical Adversarial Stress Harness for TelethonSessionManager:
1. High concurrency on same phone session (stampede, reconnection, mutual exclusion).
2. Cross-phone concurrency (true parallelism, slow phone non-blocking).
3. Safe Disconnect Protocol & Real Windows SQLite file unlocking (WinError 32 prevention).
4. Disconnect_all under high load, rapid shutdown, and fault injection.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon import TelegramClient

from services.session_manager import TelethonSessionManager


@pytest.fixture
def temp_sessions_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for session files."""
    sdir = tmp_path / "sessions_stress"
    sdir.mkdir(parents=True, exist_ok=True)
    return sdir


# ============================================================================
# Area 1: High Concurrency on Same Phone Session
# ============================================================================


@pytest.mark.asyncio
async def test_stress_same_phone_get_client_stampede(temp_sessions_dir: Path) -> None:
    """
    Stress-test: 100 concurrent tasks requesting get_client() simultaneously for the same phone.
    Verifies that asyncio.Lock prevents double-initialization and race conditions:
    - TelegramClient is instantiated exactly ONCE.
    - connect() is awaited exactly ONCE.
    - All 100 tasks receive the identical client instance.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"

    client_mock = AsyncMock()
    client_mock.is_connected = MagicMock(return_value=True)
    client_mock.connect = AsyncMock()

    # Simulate realistic network delay during connect
    async def delayed_connect():
        await asyncio.sleep(0.02)

    client_mock.connect.side_effect = delayed_connect

    instantiations = 0

    def mock_tg_client(*args, **kwargs):
        nonlocal instantiations
        instantiations += 1
        return client_mock

    with patch("services.session_manager.TelegramClient", side_effect=mock_tg_client):
        # Fire 100 concurrent requests
        results = await asyncio.gather(
            *(manager.get_client(phone, connect=True) for _ in range(100))
        )

        # Assertions
        assert instantiations == 1, f"Expected 1 instantiation, got {instantiations}"
        assert client_mock.connect.call_count == 1, (
            f"Expected connect() called once, got {client_mock.connect.call_count}"
        )
        assert len(results) == 100
        for client in results:
            assert client is client_mock
        assert manager.has_client(phone)


@pytest.mark.asyncio
async def test_stress_same_phone_reconnect_stampede(temp_sessions_dir: Path) -> None:
    """
    Stress-test: Existing cached client drops connection (is_connected=False).
    50 concurrent tasks call get_client(phone, connect=True) simultaneously.
    Verifies reconnect happens exactly ONCE.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"

    client_mock = AsyncMock()
    client_mock.is_connected = MagicMock(return_value=True)
    client_mock.connect = AsyncMock()

    with patch("services.session_manager.TelegramClient", return_value=client_mock):
        # Initial connect
        c1 = await manager.get_client(phone)
        assert client_mock.connect.call_count == 1

        # Simulate connection drop
        client_mock.is_connected.return_value = False

        async def reconnect_action():
            await asyncio.sleep(0.01)
            # Once connected, is_connected becomes True
            client_mock.is_connected.return_value = True

        client_mock.connect.side_effect = reconnect_action

        # 50 tasks stampede to reconnect
        results = await asyncio.gather(
            *(manager.get_client(phone, connect=True) for _ in range(50))
        )

        assert len(results) == 50
        # Exactly 2 connects total (1 initial + 1 reconnect)
        assert client_mock.connect.call_count == 2


@pytest.mark.asyncio
async def test_stress_per_phone_lock_mutual_exclusion(temp_sessions_dir: Path) -> None:
    """
    Stress-test: 50 concurrent coroutines acquiring the same phone's lock.
    Verifies strict mutual exclusion (current concurrency <= 1 at all times).
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"

    current_concurrency = 0
    max_concurrency = 0
    total_executions = 0

    async def worker(idx: int):
        nonlocal current_concurrency, max_concurrency, total_executions
        lock = manager.get_lock(phone)
        async with lock:
            current_concurrency += 1
            if current_concurrency > max_concurrency:
                max_concurrency = current_concurrency
            # In-critical-section delay
            await asyncio.sleep(0.005)
            assert current_concurrency == 1, f"Lock invariant violated! current={current_concurrency}"
            total_executions += 1
            current_concurrency -= 1

    await asyncio.gather(*(worker(i) for i in range(50)))

    assert total_executions == 50
    assert max_concurrency == 1
    assert current_concurrency == 0


@pytest.mark.asyncio
async def test_stress_get_client_exception_releases_lock(temp_sessions_dir: Path) -> None:
    """
    Stress-test: If client.connect() raises an exception, the lock MUST be released,
    and subsequent get_client() calls must not deadlock or hang.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"

    client_failing = AsyncMock()
    client_failing.connect.side_effect = ConnectionError("MTProto socket unreachable")

    client_healthy = AsyncMock()
    client_healthy.is_connected = MagicMock(return_value=True)
    client_healthy.connect = AsyncMock()

    with patch("services.session_manager.TelegramClient", side_effect=[client_failing, client_healthy]):
        # First call fails
        with pytest.raises(ConnectionError, match="MTProto socket unreachable"):
            await manager.get_client(phone)

        # Lock must not be stuck! Subsequent call must succeed
        client = await asyncio.wait_for(manager.get_client(phone), timeout=2.0)
        assert client is client_healthy
        assert manager.has_client(phone)


# ============================================================================
# Area 2: Cross-Phone Concurrency & True Parallelism
# ============================================================================


@pytest.mark.asyncio
async def test_stress_cross_phone_true_parallelism(temp_sessions_dir: Path) -> None:
    """
    Stress-test: 10 distinct phones perform operations concurrently.
    If locks are correctly segregated per phone, operations run in parallel.
    With each operation taking 0.08s, serialized execution would take 0.80s,
    while parallel execution completes in ~0.10s - 0.20s.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phones = [f"+155500000{i:02d}" for i in range(10)]

    concurrency_counter = 0
    max_concurrent_phones = 0

    async def phone_operation(phone_num: str):
        nonlocal concurrency_counter, max_concurrent_phones
        lock = manager.get_lock(phone_num)
        async with lock:
            concurrency_counter += 1
            if concurrency_counter > max_concurrent_phones:
                max_concurrent_phones = concurrency_counter
            await asyncio.sleep(0.08)
            concurrency_counter -= 1

    start_time = time.monotonic()
    await asyncio.gather(*(phone_operation(p) for p in phones))
    elapsed = time.monotonic() - start_time

    # Verification:
    # 1. Total time must be significantly less than serialized time (0.8s)
    assert elapsed < 0.45, f"Cross-phone operations were serialized! Elapsed: {elapsed:.3f}s"
    # 2. Concurrency across different phones must be > 1 (ideally near 10)
    assert max_concurrent_phones >= 5, (
        f"Expected high cross-phone concurrency, got peak={max_concurrent_phones}"
    )


@pytest.mark.asyncio
async def test_stress_slow_phone_does_not_block_fast_phone(temp_sessions_dir: Path) -> None:
    """
    Stress-test: Phone A holds a long-running lock (0.3s).
    Phone B executes 10 rapid operations.
    Phone B must complete quickly without waiting for Phone A's lock.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone_a = "+1111111111"
    phone_b = "+2222222222"

    phone_a_started = asyncio.Event()
    phone_b_finished = asyncio.Event()

    async def slow_phone_task():
        lock = manager.get_lock(phone_a)
        async with lock:
            phone_a_started.set()
            await asyncio.sleep(0.25)

    async def fast_phone_task():
        await phone_a_started.wait()
        start = time.monotonic()
        # Perform 5 operations on phone B while phone A is locked
        for _ in range(5):
            lock = manager.get_lock(phone_b)
            async with lock:
                await asyncio.sleep(0.005)
        elapsed = time.monotonic() - start
        phone_b_finished.set()
        # Fast phone must finish in under 0.1s, unaffected by slow phone's 0.25s lock
        assert elapsed < 0.12, f"Phone B was delayed by Phone A! Elapsed: {elapsed:.3f}s"

    await asyncio.gather(slow_phone_task(), fast_phone_task())
    assert phone_b_finished.is_set()


# ============================================================================
# Area 3: Safe Disconnect Protocol & Real Windows SQLite File Unlock
# ============================================================================


@pytest.mark.asyncio
async def test_stress_windows_real_sqlite_file_unlock_repeated(temp_sessions_dir: Path) -> None:
    """
    Empirical Stress-test on Windows filesystem:
    Instantiate real Telethon TelegramClients using real SQLite sessions on disk.
    Repeat create -> write -> disconnect -> remove cycle 30 times consecutively.
    Verifies that client.disconnect() and client.session.close() release the Windows
    OS file handle immediately, completely preventing:
    PermissionError: [WinError 32] The process cannot access the file because it is being used by another process.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )

    iterations = 30
    for i in range(iterations):
        phone = f"+1888555{i:04d}"
        session_file = manager.get_session_file_path(phone)

        # 1. Instantiate real client without connecting over network
        client = await manager.get_client(phone, connect=False)
        assert isinstance(client, TelegramClient)

        # 2. Write real SQLite data into the session file
        client.session.save()
        assert session_file.exists(), f"Session file missing at cycle {i}"

        # 3. Disconnect safely via manager
        await manager.disconnect(phone)
        assert not manager.has_client(phone)

        # 4. Attempt immediate unlinking on Windows
        try:
            session_file.unlink()
        except PermissionError as e:
            pytest.fail(f"Windows WinError 32 detected at cycle {i}: {e}")

        assert not session_file.exists(), f"Session file still exists at cycle {i}"

        # 5. Verify file can be immediately re-created with exclusive write access
        with open(session_file, "w") as f:
            f.write("exclusive lock test")
        session_file.unlink()


@pytest.mark.asyncio
async def test_stress_remove_session_file_real_sqlite(temp_sessions_dir: Path) -> None:
    """
    Verify remove_session_file() cleanly deletes a real SQLite session file on Windows.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+19998887777"
    session_file = manager.get_session_file_path(phone)

    client = await manager.get_client(phone, connect=False)
    client.session.save()
    assert session_file.is_file()

    # remove_session_file should disconnect and unlink
    removed = await manager.remove_session_file(phone)
    assert removed is True
    assert not session_file.exists()
    assert not manager.has_client(phone)

    # Calling again returns False safely
    assert await manager.remove_session_file(phone) is False


@pytest.mark.asyncio
async def test_stress_idempotent_disconnect(temp_sessions_dir: Path) -> None:
    """
    Stress-test: Calling disconnect() 10 times consecutively on the same phone.
    Must be completely idempotent, no-op after first disconnect, no errors raised.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"

    client_mock = AsyncMock()
    client_mock.is_connected = MagicMock(return_value=True)

    with patch("services.session_manager.TelegramClient", return_value=client_mock):
        await manager.get_client(phone)
        assert manager.has_client(phone)

        for _ in range(10):
            await manager.disconnect(phone)
            assert not manager.has_client(phone)

        # disconnect should only have been called once on the client
        assert client_mock.disconnect.call_count == 1


# ============================================================================
# Area 4: High Load Chaos & Disconnect_all Under Load
# ============================================================================


@pytest.mark.asyncio
async def test_stress_concurrent_get_and_disconnect_chaos(temp_sessions_dir: Path) -> None:
    """
    Adversarial chaos test: 60 tasks interleaved across 3 phones executing get_client,
    disconnect, and is_authorized concurrently.
    Verifies no race conditions, unhandled exceptions, or deadlocks occur.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phones = ["+1111111111", "+2222222222", "+3333333333"]

    def make_mock(*args, **kwargs):
        m = AsyncMock()
        m.is_connected = MagicMock(return_value=True)
        m.connect = AsyncMock()
        m.disconnect = AsyncMock()
        m.is_user_authorized = AsyncMock(return_value=True)
        m.session = MagicMock()
        return m

    with patch("services.session_manager.TelegramClient", side_effect=make_mock):
        async def task_get(p: str):
            c = await manager.get_client(p)
            assert c is not None

        async def task_dc(p: str):
            await asyncio.sleep(0.005)
            await manager.disconnect(p)

        async def task_auth(p: str):
            await asyncio.sleep(0.002)
            auth = await manager.is_authorized(p)
            assert auth is True

        tasks = []
        for i in range(20):
            p = phones[i % 3]
            tasks.append(task_get(p))
            tasks.append(task_dc(p))
            tasks.append(task_auth(p))

        # Run all 60 tasks concurrently
        await asyncio.gather(*tasks)

        # Clean shutdown afterwards
        await manager.disconnect_all()
        assert len(manager.get_active_phones()) == 0


@pytest.mark.asyncio
async def test_stress_disconnect_all_under_load(temp_sessions_dir: Path) -> None:
    """
    Stress-test: 20 active clients in pool.
    Trigger disconnect_all() while tasks are actively executing.
    Verifies all 20 clients are disconnected and cleared from the pool.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phones = [f"+177700000{i:02d}" for i in range(20)]

    clients = {}
    for p in phones:
        m = AsyncMock()
        m.is_connected = MagicMock(return_value=True)
        m.disconnect = AsyncMock()
        m.session = MagicMock()
        clients[p] = m

    with patch(
        "services.session_manager.TelegramClient",
        side_effect=lambda base, aid, ahash: clients[Path(base).name],
    ):
        for p in phones:
            await manager.get_client(p)

        assert len(manager.get_active_phones()) == 20

        # Run rapid disconnect_all
        await manager.disconnect_all()

        assert len(manager.get_active_phones()) == 0
        for p, c in clients.items():
            c.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_stress_concurrent_disconnect_all_calls(temp_sessions_dir: Path) -> None:
    """
    Stress-test: 5 simultaneous calls to disconnect_all().
    Global lock must serialize/protect shutdown without deadlocks or double-disconnect errors.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15156723850"

    client_mock = AsyncMock()
    client_mock.is_connected = MagicMock(return_value=True)
    client_mock.disconnect = AsyncMock()
    client_mock.session = MagicMock()

    with patch("services.session_manager.TelegramClient", return_value=client_mock):
        await manager.get_client(phone)
        assert manager.has_client(phone)

        # Launch 5 concurrent disconnect_all calls
        await asyncio.gather(*(manager.disconnect_all() for _ in range(5)))

        assert len(manager.get_active_phones()) == 0
        # Disconnect on the individual client should only have been called once
        assert client_mock.disconnect.call_count == 1


@pytest.mark.asyncio
async def test_stress_disconnect_all_fault_injection(temp_sessions_dir: Path) -> None:
    """
    Adversarial fault injection: 10 clients in pool, 5 of which raise harsh exceptions
    during client.disconnect() (ConnectionResetError, RuntimeError, OSError).
    disconnect_all() must catch all exceptions, log warnings, and still cleanly
    disconnect the remaining healthy clients and empty the pool.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phones = [f"+166600000{i:02d}" for i in range(10)]

    clients = {}
    for i, p in enumerate(phones):
        m = AsyncMock()
        m.is_connected = MagicMock(return_value=True)
        m.session = MagicMock()
        if i % 2 == 0:
            m.disconnect.side_effect = ConnectionResetError("Remote socket forcefully closed")
        else:
            m.disconnect = AsyncMock()
        clients[p] = m

    with patch(
        "services.session_manager.TelegramClient",
        side_effect=lambda base, aid, ahash: clients[Path(base).name],
    ):
        for p in phones:
            await manager.get_client(p)

        assert len(manager.get_active_phones()) == 10

        # disconnect_all must NOT propagate the ConnectionResetError
        await manager.disconnect_all()

        # All healthy clients were disconnected
        for i, p in enumerate(phones):
            if i % 2 != 0:
                clients[p].disconnect.assert_awaited_once()

        # Pool is completely cleared
        assert len(manager.get_active_phones()) == 0


# ============================================================================
# Area 5: Discovered Vulnerabilities & Failure Mode Verification
# ============================================================================


@pytest.mark.asyncio
async def test_vulnerability_remove_session_file_unlocked_race(temp_sessions_dir: Path) -> None:
    """
    REMEDIATED CHALLENGE 1: Race Condition in remove_session_file() resolved.
    remove_session_file() acquires and holds the per-phone lock for the entire duration
    (disconnecting the client, closing SQLite handles, and unlinking the file).
    Concurrent get_client() calls serialize cleanly on the lock, preventing
    PermissionError: [WinError 32] on Windows.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15550001111"
    session_file = manager.get_session_file_path(phone)

    # 1. Create real session file on disk
    client = await manager.get_client(phone, connect=False)
    client.session.save()
    assert session_file.exists()
    assert manager.has_client(phone)

    # 2. Launch concurrent remove_session_file and get_client tasks
    # Both operations synchronize on the per-phone lock: no WinError 32 can occur
    results = await asyncio.gather(
        manager.remove_session_file(phone),
        manager.get_client(phone, connect=False),
        return_exceptions=True,
    )

    # Neither task should have raised PermissionError (WinError 32)
    for res in results:
        assert not isinstance(res, PermissionError), f"Unexpected PermissionError: {res}"
        if isinstance(res, Exception):
            raise res

    # Cleanup
    await manager.disconnect_all()


@pytest.mark.asyncio
async def test_vulnerability_connect_failure_leaves_file_locked(temp_sessions_dir: Path) -> None:
    """
    REMEDIATED CHALLENGE 2: Connect Failure Safely Releases SQLite Session File Lock.
    When TelegramClient.connect() raises an exception during get_client(),
    the exception handler safely closes the client's SQLite session handle and disconnects.
    The session file on Windows is NOT left locked, and can be cleanly unlinked without WinError 32.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    phone = "+15559998888"
    session_file = manager.get_session_file_path(phone)

    async def failing_connect(self):
        raise ConnectionError("Simulated network outage during connect")

    with patch.object(TelegramClient, "connect", failing_connect):
        with pytest.raises(ConnectionError, match="Simulated network outage"):
            await manager.get_client(phone, connect=True)

    # The file was created by Telethon
    assert session_file.exists()

    # Remediated: SQLite session handle was closed on failure, so unlink succeeds cleanly!
    session_file.unlink()
    assert not session_file.exists()
    assert not manager.has_client(phone)


@pytest.mark.asyncio
async def test_vulnerability_disconnect_all_concurrent_leak(temp_sessions_dir: Path) -> None:
    """
    REMEDIATED CHALLENGE 3: Disconnect_all Drains Concurrent Client Additions.
    disconnect_all drains the client pool using a dynamic while-loop. If concurrent coroutines
    insert new clients into the pool while disconnect_all is executing, the loop continues
    until all clients are popped and disconnected, leaving zero orphaned connections.
    """
    manager = TelethonSessionManager(
        api_id=12345,
        api_hash="test_hash",
        sessions_dir=temp_sessions_dir,
    )
    c1 = AsyncMock()
    c1.is_connected = MagicMock(return_value=True)
    c1.session = MagicMock()

    c2 = AsyncMock()
    c2.is_connected = MagicMock(return_value=True)
    c2.session = MagicMock()

    clients = {"+1111": c1, "+2222": c2}

    with patch(
        "services.session_manager.TelegramClient",
        side_effect=lambda base, aid, ahash: clients[Path(base).name],
    ):
        await manager.get_client("+1111")

        orig_dc1 = c1.disconnect

        async def slow_dc():
            # While +1111 is disconnecting, a concurrent request adds +2222
            await manager.get_client("+2222")
            await orig_dc1()

        c1.disconnect = slow_dc

        await manager.disconnect_all()

        # Remediated: Both c1 and c2 were cleanly disconnected and drained
        assert orig_dc1.call_count == 1
        assert c2.disconnect.call_count == 1  # c2 was safely disconnected, NOT leaked!
        assert manager.get_active_phones() == []  # pool is cleanly emptied!
