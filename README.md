# Telegram Account Manager & Contact Extractor Bot

A professional, high-performance Telegram Account Manager and Contact Extractor Bot refactored with a modern modular architecture, asynchronous SQLite persistence, in-place UI message editing, and comprehensive automated test coverage.

---

## 🌟 Key Features

- **Multi-Account MTProto Lifecycle**: Add, authenticate, and manage multiple Telegram accounts concurrently with Telethon session isolation, proper 2FA handling, and clean disconnects.
- **In-Place UI Flow (Zero Chat Clutter)**: The bot maintains a single living prompt message in the chat (`edit_message_text`), instantly deleting sensitive user inputs (phone numbers, SMS codes, passwords) to protect user privacy.
- **Contact Extraction & Filtering**:
  - Filter contacts by ID length: 7, 8, 9, 10, and 11 digits.
  - Bulk extraction for legacy accounts (7 to 9 digits).
  - Mutual contacts extraction (contacts where both parties have each other's number).
  - In-memory streaming VCF (vCard 3.0) file generation without temporary disk clutter.
- **Creator Chats & Channel Inventory**: Fetch all channels, supergroups, and groups owned by the account with invite links, creation dates, and history visibility.
- **Official Telegram Code Retrieval**: Automatically read login authentication codes received from the official Telegram service peer (`777000`).
- **Batch Contact Deletion**: Remove all contacts in batches with real-time progress percentage updates and error recovery.
- **Bilingual Interface**: Clean, balanced Persian and English output across all operational summaries, menus, and error messages.
- **Asynchronous SQLite Database**: ACID transactions via `aiosqlite`, Write-Ahead Logging (WAL), foreign keys, and automatic legacy JSON data migration.

---

## 📁 Architecture & Package Structure

```
├── main.py                  # Bot entry point and lifecycle orchestration
├── config/                  # Pydantic settings loading from .env
├── database/                # Async SQLite connection, repositories, models, migration
├── services/                # Telethon session manager, auth, contact & chat services
├── bot/                     # python-telegram-bot v22 handlers, in-place helpers, UI
│   ├── handlers/            # Start, auth conversation, account menu, contact & chat handlers
│   ├── helpers.py           # In-place prompt editing and safe message deletion
│   ├── keyboards.py         # Concise, non-truncating inline keyboards
│   └── messages.py          # Bilingual message templates and report formatters
├── utils/                   # Contact filtering, phone sanitization, streaming VCF
├── tests/                   # 670 automated unit, integration, and e2e tests
├── .env.example             # Configuration template
└── requirements.txt         # Production dependencies
```

---

## 🚀 Quick Start

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/mrvxbot/Telegram-ID.git
cd Telegram-ID
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

```ini
API_ID=your_telegram_api_id
API_HASH=your_telegram_api_hash
BOT_TOKEN=your_botfather_token
DATABASE_PATH=data/bot.db
SESSIONS_DIR=sessions
```

### 3. Run Automated Tests

```bash
python -m pytest
```

### 4. Start the Bot

```bash
python main.py
```

---

## 🧪 Verification & Test Suite

The project includes 670 automated tests covering:
- In-place message editing and user input message deletion (`tests/bot/test_inplace_editing.py`)
- Full conversation and authentication workflows with 2FA (`tests/bot/test_conversation_flow.py`)
- Contact filtering, streaming VCF generation, and phone sanitization (`tests/unit/`)
- Concurrent session management and resource locking under stress (`tests/services/`)
- End-to-end full lifecycle simulation (`tests/e2e/test_full_lifecycle.py`)

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
