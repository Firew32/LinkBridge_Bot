# LinkedIn Profile Sharing Telegram Bot

This is an anonymous Telegram bot designed to help students and staff submit their LinkedIn profiles and receive others' profiles, fostering professional connections within the department.

## Features
- Collects LinkedIn profiles anonymously.
- Returns a list of collected profiles to the user.
- Stores profiles in a PostgreSQL database.

## Requirements
- Python 3.8+
- Telegram Bot API Token (from BotFather)
- PostgreSQL

## Setup

1. Clone the repository:
    ```bash
    git clone https://github.com/Alpha-mintamir/linkedin-bot.git
    ```

2. Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

3. Set up your PostgreSQL database and update the `.env` file with your credentials.

4. Initialize the database:
    ```bash
    python scripts/db_setup.py
    ```

5. Run the bot:
    ```bash
    python bot.py
    ```

## License
MIT License

---

### Recap:
This folder structure is designed to keep your project modular and maintainable, with clear separation of concerns for bot logic, database handling, and environment management.

