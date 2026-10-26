# E2E Test Infra: Telegram Account Manager & Contact Extractor Modernization

## Test Philosophy
- Opaque-box, requirement-driven automated verification using `pytest` and `pytest-asyncio`.
- No dependency on internal implementation details; test behaviors, state transitions, outputs, and edge cases.
- Methodology: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Interaction + Real-World Workloads.

## Feature Inventory Coverage Matrix
| # | Feature | Source | Tier 1 (Base) | Tier 2 (Boundary) | Tier 3 (Pairwise) | Tier 4 (Scenario) |
|---|---------|--------|:-------------:|:-----------------:|:-----------------:|:-----------------:|
| 1 | Configuration & Secrets Loading | R4 | 5 | 5 | ✓ | ✓ |
| 2 | Phone Number Validation | R1 | 5 | 5 | ✓ | ✓ |
| 3 | Contact ID Digit Filtering (7-11, 7to9) | R5 | 5 | 5 | ✓ | ✓ |
| 4 | Streaming VCF Generation | R1, R5 | 5 | 5 | ✓ | ✓ |
| 5 | Async SQLite Connection & WAL | R3 | 5 | 5 | ✓ | ✓ |
| 6 | Database CRUD (Users & Accounts) | R3 | 5 | 5 | ✓ | ✓ |
| 7 | JSON Auto-Migration & Backup | R3 | 5 | 5 | ✓ | ✓ |
| 8 | Telethon Client Pool & Lifecycle | R2 | 5 | 5 | ✓ | ✓ |
| 9 | Authentication Flow & 2FA Handling | R2 | 5 | 5 | ✓ | ✓ |
| 10 | Safe Disconnect & File Lock Release | R2 | 5 | 5 | ✓ | ✓ |
| 11 | Contact Extraction & Export | R5 | 5 | 5 | ✓ | ✓ |
| 12 | Mutual Contacts Detection & Export | R5 | 5 | 5 | ✓ | ✓ |
| 13 | Batch Contact Deletion with Progress | R5 | 5 | 5 | ✓ | ✓ |
| 14 | Dialogs Listing & Group Deduplication | R5 | 5 | 5 | ✓ | ✓ |
| 15 | Telegram Login Code Retrieval (777000) | R5 | 5 | 5 | ✓ | ✓ |
| 16 | Bot Application & State Re-entry (/start, /cancel) | R5 | 5 | 5 | ✓ | ✓ |
| 17 | Inline Keyboards & Back Navigation | R5 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- Test runner: `pytest` with `pytest-asyncio` (`asyncio_mode = auto`).
- Test location: `tests/` directory with organized suites:
  - `tests/unit/`: Pure function tests (phone validation, contact filtering, VCF generation).
  - `tests/database/`: SQLite connection, CRUD, JSON migration idempotency and error handling.
  - `tests/services/`: Mocked Telethon sessions, client pool, auth/2FA, contacts, dialogs, 777000 code.
  - `tests/bot/`: Keyboards, conversation handlers, universal `/start` and `/cancel` re-entry.
  - `tests/e2e/`: Real-world end-to-end integration workflows.
- Mocking strategy:
  - MTProto calls simulated using `unittest.mock.AsyncMock`.
  - In-memory SQLite (`:memory:`) or temporary database fixtures for fast, isolated tests.

## Coverage Thresholds
- Tier 1: ≥5 test cases per feature (Happy-path isolation)
- Tier 2: ≥5 test cases per feature (Boundaries, invalid inputs, edge cases)
- Tier 3: Pairwise combinations of major features (e.g., auth + 2FA + extraction; migration + account select + delete)
- Tier 4: Realistic end-to-end scenarios (e.g., full lifecycle from legacy JSON import to contact extraction and logout)
- Tier 5: Adversarial stress testing (race conditions, rapid cancellation, session lock recovery)
