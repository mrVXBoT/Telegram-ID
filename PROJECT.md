# Project: Telegram Account Manager & Contact Extractor Modernization

## Architecture
Clean 6-layer modular architecture replacing the 1,316-line monolith `TG-ID.py`:
- `config/`: Pydantic BaseSettings loading from `.env` and environment variables. Zero hardcoded secrets.
- `database/`: Asynchronous SQLite storage via `aiosqlite` with WAL mode, foreign keys, and automatic migration from `user_data.json`.
- `services/`: Telethon async session manager, auth lifecycle (2FA, code hashes), contact extraction & batch deletion, dialogs & 777000 code retriever.
- `bot/`: Modular `python-telegram-bot` v22 handlers (conversations, callbacks, commands), inline keyboards, and bilingual messages.
- `utils/`: Phone sanitizer, digit length filters, and streaming in-memory VCF generator (`io.BytesIO`).
- `tests/`: Multi-tier automated test suite using `pytest` and `pytest-asyncio`.

## Code Layout
```
c:\Users\PC\Downloads\Telegram-ID-main\
├── .env.example
├── requirements.txt
├── pytest.ini
├── main.py
├── config/
│   ├── __init__.py
│   └── settings.py
├── database/
│   ├── __init__.py
│   ├── connection.py
│   ├── models.py
│   ├── repository.py
│   └── migration.py
├── services/
│   ├── __init__.py
│   ├── session_manager.py
│   ├── auth_service.py
│   ├── contact_service.py
│   └── chat_service.py
├── bot/
│   ├── __init__.py
│   ├── application.py
│   ├── states.py
│   ├── keyboards.py
│   ├── messages.py
│   └── handlers/
│       ├── __init__.py
│       ├── start.py
│       ├── auth_conversation.py
│       ├── account_menu.py
│       ├── contact_handlers.py
│       └── chat_handlers.py
├── utils/
│   ├── __init__.py
│   ├── phone.py
│   ├── filters.py
│   └── vcf.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── unit/
    ├── database/
    ├── services/
    └── bot/
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Configuration & Secrets Management | Pydantic settings loading from `.env`, `.env.example`, no hardcoded secrets | M1 | R4, Survey 3 |
| 2 | Phone Validation & Sanitization | Phone normalization, country code detection, international regex | M1 | R1, Survey 1, Survey 3 |
| 3 | Contact ID Digit Filtering | Predicates for 7, 8, 9, 10, 11 digits and 7-9 bulk range | M1 | R5, Survey 1 |
| 4 | Streaming VCF Generator | In-memory VCF card generation (`io.BytesIO`) using vobject, no disk leakage | M1 | R1, R5, Survey 1 |
| 5 | Modern Dependencies & Pytest Config | Modernized requirements.txt, pytest.ini with asyncio_mode=auto | M1 | R6, Survey 3 |
| 6 | Async SQLite Connection | `aiosqlite` connection manager, WAL mode, foreign keys enabled | M2 | R3, Survey 2 |
| 7 | Database Schema & Models | Dataclasses/models for users, accounts, operation history, and metadata | M2 | R3, Survey 2 |
| 8 | Async Repository Layer | CRUD operations for users and accounts, query by user_id and phone | M2 | R3, Survey 2 |
| 9 | JSON Auto-Migration | Automatic lossless import of accounts from `user_data.json` on startup | M2 | R3, Survey 2 |
| 10 | Migration Safety & Missing Session | JSON backup (.bak) creation, graceful handling of missing .session files | M2 | R2, R3, Survey 2 |
| 11 | Telethon Session Pool & Lifecycle | Async session manager, per-phone locks, client caching, disconnect_all | M3 | R2, Survey 2, Survey 3 |
| 12 | Telethon Authentication Flow | Phone code request, phone_code_hash tracking, sign-in verification | M3 | R2, Survey 2 |
| 13 | 2FA Password Handling | Graceful handling of SessionPasswordNeededError with retry | M3 | R2, Survey 2 |
| 14 | Safe Disconnect & File Unlock | Calling disconnect() before file removal to prevent WinError 32 | M3 | R2, Survey 3 |
| 15 | Session File Backward Compatibility | Seamless reuse of existing `.session` files in `sessions/` | M3 | R2, Survey 2 |
| 16 | Contact Extraction Service | Telethon GetContactsRequest with digit length filtering (7-11, 7to9) | M3 | R5, Survey 1 |
| 17 | Mutual Contacts Service | Mutual contacts detection (`mutual=True`) and extraction | M3 | R5, Survey 1 |
| 18 | Batch Contact Deletion | Deletion in batches of 100 with progress callbacks and rate limit pauses | M3 | R5, Survey 1 |
| 19 | Owned Dialogs & Chats Listing | Listing channels, supergroups, basic chats with creator flag & deduplication | M3 | R5, Survey 1 |
| 20 | Chat History Visibility Probe | Detection of `hidden_prehistory` on channels and supergroups | M3 | R5, Survey 1 |
| 21 | Telegram Auth Code Retriever | Extracting 5-digit verification codes (`\b\d{5}\b`) from peer 777000 | M3 | R5, Survey 1 |
| 22 | PTB Application Builder & Lifecycle | Application setup with post_init and post_shutdown hooks | M4 | R1, Survey 3 |
| 23 | Universal Navigation & Re-entry | /start, /cancel, and cancel_auth handlers with complete state reset | M4 | R5, Survey 1 |
| 24 | Complete Inline Keyboards | Main menu, account list, 13-action account keyboard, delete confirm | M4 | R5, Survey 1 |
| 25 | Add Account Conversation | PTB ConversationHandler for PHONE -> CODE -> 2FA PASSWORD -> ACTIONS | M4 | R1, R5, Survey 1 |
| 26 | Account Selection & Sub-Menu Nav | Account selection, sub-menu back navigation to account actions or list | M4 | R5, Survey 1 |
| 27 | Contact Extraction Bot Handler | Extraction command triggering, progress notices, VCF document sending | M4 | R5, Survey 1 |
| 28 | Contact Deletion Bot Handler | Warning confirmation, live progress percentage editing, final report | M4 | R5, Survey 1 |
| 29 | Chats & Auth Code Bot Handlers | Listing user-owned chats and displaying retrieved 777000 login code | M4 | R5, Survey 1 |
| 30 | Logout & Session Removal Handler | Account logout via Telethon, session disconnect, DB & file removal | M4 | R2, R5, Survey 1 |
| 31 | Bootstrap Entry Point | `main.py` executing DB migration, initializing bot, starting polling | M4 | R1, Survey 3 |
| 32 | Opaque-Box E2E Tests (Tiers 1-4) | Comprehensive pytest test suite for all features, boundaries, combinations | M5 | R6 |
| 33 | Adversarial Coverage Hardening (Tier 5) | White-box stress tests, fault injection, concurrency race tests | M5 | R6 |
| 34 | Final Acceptance & Verification | 100% test pass rate, clean bot startup, complete verification claim | M5 | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Config, Utils & Packaging | `config/`, `utils/`, `requirements.txt`, `pytest.ini`, `.env.example` | none | DONE |
| M2 | Async SQLite & JSON Migration | `database/` (connection, models, repository, migration, tests) | M1 | DONE |
| M3 | Telethon Session Manager & Services | `services/` (session_manager, auth, contacts, chats, tests) | M1, M2 | DONE |
| M4 | Modular Bot UI & Application | `bot/`, `main.py`, handlers, keyboards, messages, integration tests | M1, M2, M3 | DONE |
| M5 | E2E Testing Track & Final Verification | Full test suite execution (Tiers 1-5), audit, acceptance verification | M1, M2, M3, M4 | DONE |

## Interface Contracts
### `config` -> All Modules
- `get_settings()` returns validated `Settings` instance with `api_id: int`, `api_hash: str`, `bot_token: str`, `database_path: Path`, `sessions_dir: Path`.

### `database` -> `services` & `bot`
- `DatabaseConnection.get_db()`: Async context manager yielding active `aiosqlite.Connection`.
- `UserRepository.get_or_create_user(telegram_id: int) -> UserRecord`
- `AccountRepository.get_user_accounts(user_id: int) -> list[AccountRecord]`
- `AccountRepository.add_account(user_id: int, phone: str, status: str = 'active') -> AccountRecord`
- `AccountRepository.remove_account(user_id: int, phone: str) -> bool`
- `run_migration(db_path: Path, json_path: Path, sessions_dir: Path) -> MigrationResult`

### `services` -> `bot`
- `TelethonSessionManager.get_client(phone: str) -> TelegramClient`
- `TelethonSessionManager.disconnect(phone: str) -> None`
- `TelethonSessionManager.disconnect_all() -> None`
- `AuthService.send_code(phone: str) -> str (phone_code_hash)`
- `AuthService.sign_in(phone: str, code: str, phone_code_hash: str, password: Optional[str] = None) -> SignInResult`
- `ContactService.extract_contacts_by_length(phone: str, id_length: Union[int, str]) -> list[ContactInfo]`
- `ContactService.get_mutual_contacts(phone: str) -> list[ContactInfo]`
- `ContactService.delete_all_contacts(phone: str, progress_callback: Callable[[int, int], Awaitable[None]]) -> DeleteResult`
- `ChatService.list_creator_chats(phone: str) -> list[ChatInfo]`
- `ChatService.get_latest_login_code(phone: str) -> Optional[str]`

### `utils` -> `services` & `bot`
- `validate_phone_number(phone: str) -> Optional[str]`
- `filter_contacts_by_digit_length(contacts: Iterable, length_spec: Union[int, str]) -> list`
- `generate_vcf_stream(contacts: list[ContactInfo]) -> io.BytesIO`
