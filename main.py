import hashlib
import re
import sqlite3
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, simpledialog, ttk
from typing import List, Optional, Tuple


class DatabaseManager:
    """Manages all database operations with proper error handling."""

    def __init__(self, db_name: str = "library_pro.db"):
        self.db_name = db_name
        self.conn: Optional[sqlite3.Connection] = None
        self.cursor: Optional[sqlite3.Cursor] = None
        self.initialize_database()

    def initialize_database(self) -> None:
        """Initialize database connection and create tables."""
        try:
            self.conn = sqlite3.connect(self.db_name)
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.cursor = self.conn.cursor()
            self._create_tables()
            self.conn.commit()
        except sqlite3.Error as exc:
            print(f"Database error: {exc}")
            raise

    def _create_tables(self) -> None:
        """Create required database tables."""
        assert self.cursor is not None

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
            """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS books (
                book_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL CHECK(price >= 0),
                quantity INTEGER NOT NULL CHECK(quantity >= 0),
                isbn TEXT UNIQUE,
                published_year INTEGER,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS loans (
                loan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                book_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                due_date TIMESTAMP NOT NULL,
                returned_at TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'issued',
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(book_id) REFERENCES books(book_id)
            )
            """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS wishlist (
                wishlist_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                book_id INTEGER NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(book_id) REFERENCES books(book_id),
                UNIQUE(user_id, book_id)
            )
            """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                book_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(book_id) REFERENCES books(book_id)
            )
            """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_logs (
                activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        self._migrate_cart_to_loans()

    def _migrate_cart_to_loans(self) -> None:
        """Convert legacy cart rows into active loans when needed."""
        assert self.cursor is not None

        try:
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cart'")
            cart_exists = self.cursor.fetchone() is not None
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='loans'")
            loans_exists = self.cursor.fetchone() is not None
            if not cart_exists or not loans_exists:
                return

            self.cursor.execute("SELECT COUNT(*) FROM cart")
            cart_count = self.cursor.fetchone()[0]
            if cart_count == 0:
                return

            self.cursor.execute("SELECT COUNT(*) FROM loans")
            loans_count = self.cursor.fetchone()[0]
            if loans_count > 0:
                return

            rows = self.cursor.execute("SELECT user_id, book_id, quantity, added_at FROM cart").fetchall()
            for user_id, book_id, quantity, added_at in rows:
                issued_at = added_at
                due_date = datetime.now() + timedelta(days=14)
                self.cursor.execute(
                    """
                    INSERT INTO loans (user_id, book_id, quantity, issued_at, due_date, returned_at, status)
                    VALUES (?, ?, ?, ?, ?, NULL, 'issued')
                    """,
                    (user_id, book_id, quantity, issued_at, due_date.strftime("%Y-%m-%d %H:%M:%S")),
                )
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()

    def execute_query(self, query: str, params: Tuple = ()) -> Optional[List[tuple]]:
        """Execute a SELECT query safely."""
        try:
            assert self.cursor is not None
            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except sqlite3.Error as exc:
            print(f"Query error: {exc}")
            return None

    def execute_update(self, query: str, params: Tuple = ()) -> bool:
        """Execute INSERT, UPDATE, or DELETE query safely."""
        try:
            assert self.conn is not None
            assert self.cursor is not None
            self.cursor.execute(query, params)
            self.conn.commit()
            return self.cursor.rowcount > 0
        except sqlite3.IntegrityError as exc:
            print(f"Data conflict: {exc}")
            return False
        except sqlite3.Error as exc:
            print(f"Query error: {exc}")
            return False

    def log_activity(self, user_id: Optional[int], username: str, action: str, details: str = "") -> None:
        """Record a user or admin action in the activity log."""
        try:
            assert self.conn is not None
            assert self.cursor is not None
            self.cursor.execute(
                """
                INSERT INTO activity_logs (user_id, username, action, details)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, username, action, details),
            )
            self.conn.commit()
        except sqlite3.Error as exc:
            print(f"Activity log error: {exc}")

    def get_user_activity(self, user_id: int) -> List[tuple]:
        result = self.execute_query(
            """
            SELECT activity_id, username, action, details, created_at
            FROM activity_logs
            WHERE user_id = ?
            ORDER BY created_at DESC, activity_id DESC
            """,
            (user_id,),
        )
        return result or []

    def get_all_activity(self) -> List[tuple]:
        result = self.execute_query(
            """
            SELECT activity_id, username, action, details, created_at
            FROM activity_logs
            ORDER BY created_at DESC, activity_id DESC
            """
        )
        return result or []

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()


class AuthManager:
    """Handles user authentication and validation."""

    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def is_valid_username(username: str) -> Tuple[bool, str]:
        if len(username) < 3:
            return False, "Username must be at least 3 characters long."
        if re.match(r"^[0-9_]", username):
            return False, "Username cannot start with a number or underscore."
        if not re.match(r"^[a-zA-Z0-9_]+$", username):
            return False, "Username can contain only letters, numbers, and underscores."
        return True, ""

    @staticmethod
    def is_valid_password(password: str) -> Tuple[bool, str]:
        if len(password) < 8:
            return False, "Password must be at least 8 characters long."
        if len(password) > 20:
            return False, "Password cannot be longer than 20 characters."
        if not re.search(r"[A-Z]", password):
            return False, "Password must contain at least one uppercase letter."
        if not re.search(r"[a-z]", password):
            return False, "Password must contain at least one lowercase letter."
        if not re.search(r"[0-9]", password):
            return False, "Password must contain at least one number."
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            return False, "Password must contain at least one special character."
        return True, ""

    @staticmethod
    def is_valid_email(email: str) -> Tuple[bool, str]:
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if re.match(pattern, email):
            return True, ""
        return False, "Invalid email format."


class UserManager:
    """Handles user registration and login."""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.auth = AuthManager()
        self.current_user: Optional[str] = None
        self.current_user_id: Optional[int] = None
        self.current_role: Optional[str] = None

    def register_user(
        self, username: str, email: str, password: str, confirm_password: str
    ) -> Tuple[bool, str]:
        valid, message = self.auth.is_valid_username(username)
        if not valid:
            return False, message

        valid, message = self.auth.is_valid_email(email)
        if not valid:
            return False, message

        valid, message = self.auth.is_valid_password(password)
        if not valid:
            return False, message

        if password != confirm_password:
            return False, "Passwords do not match."

        hashed_password = self.auth.hash_password(password)
        query = """
            INSERT INTO users (username, email, password, role)
            VALUES (?, ?, ?, 'user')
        """

        if self.db.execute_update(query, (username, email, hashed_password)):
            created_user = self.db.execute_query("SELECT user_id FROM users WHERE username = ?", (username,))
            user_id = created_user[0][0] if created_user else None
            self.db.log_activity(user_id, username, "register", "Created a new user account.")
            return True, "Account created successfully."
        return False, "Username or email already exists."

    def login_user(self, username: str, password: str) -> Tuple[bool, str, Optional[dict]]:
        hashed_password = self.auth.hash_password(password)
        query = """
            SELECT user_id, username, role
            FROM users
            WHERE username = ? AND password = ? AND is_active = 1
        """
        result = self.db.execute_query(query, (username, hashed_password))
        if result:
            user_id, user_name, role = result[0]
            self.current_user_id = user_id
            self.current_user = user_name
            self.current_role = role
            return True, "Login successful.", {"user_id": user_id, "username": user_name, "role": role}
        return False, "Invalid username or password.", None

    def set_current_admin(self) -> dict:
        self.current_user_id = 0
        self.current_user = "admin"
        self.current_role = "admin"
        return {"user_id": 0, "username": "admin", "role": "admin"}

    def logout(self) -> None:
        self.current_user = None
        self.current_user_id = None
        self.current_role = None


class BookManager:
    """Manages book operations."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def add_book(
        self,
        title: str,
        author: str,
        category: str,
        price: float,
        quantity: int,
        isbn: Optional[str] = None,
        published_year: Optional[int] = None,
        description: Optional[str] = None,
    ) -> Tuple[bool, str]:
        if not title or not author or not category:
            return False, "Title, author, and category are required."
        if price < 0 or quantity < 0:
            return False, "Price and quantity cannot be negative."

        query = """
            INSERT INTO books (title, author, category, price, quantity, isbn, published_year, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        if self.db.execute_update(query, (title, author, category, price, quantity, isbn, published_year, description)):
            return True, "Book added successfully."
        return False, "Failed to add the book."

    def delete_book(self, book_id: int) -> Tuple[bool, str]:
        exists = self.db.execute_query("SELECT title FROM books WHERE book_id = ?", (book_id,))
        if not exists:
            return False, "Book not found."
        if self.db.execute_update("DELETE FROM books WHERE book_id = ?", (book_id,)):
            return True, "Book deleted successfully."
        return False, "Failed to delete the book."

    def update_book(self, book_id: int, **fields) -> Tuple[bool, str]:
        allowed = ["title", "author", "category", "price", "quantity", "isbn", "published_year", "description"]
        updates = []
        params = []

        for key in allowed:
            if key in fields and fields[key] is not None:
                updates.append(f"{key} = ?")
                params.append(fields[key])

        if not updates:
            return False, "No changes were provided."

        updates.append("updated_at = CURRENT_TIMESTAMP")
        query = f"UPDATE books SET {', '.join(updates)} WHERE book_id = ?"
        params.append(book_id)

        if self.db.execute_update(query, tuple(params)):
            return True, "Book updated successfully."
        return False, "Failed to update the book."

    def get_book(self, book_id: int) -> Optional[tuple]:
        result = self.db.execute_query(
            "SELECT book_id, title, author, category, price, quantity, isbn, published_year, description FROM books WHERE book_id = ?",
            (book_id,),
        )
        return result[0] if result else None

    def list_books(self) -> List[tuple]:
        result = self.db.execute_query(
            "SELECT book_id, title, author, category, price, quantity, isbn, published_year, description FROM books ORDER BY book_id"
        )
        return result or []

    def search_books(self, search_term: str) -> List[tuple]:
        pattern = f"%{search_term}%"
        result = self.db.execute_query(
            """
            SELECT book_id, title, author, category, price, quantity, isbn, published_year, description
            FROM books
            WHERE title LIKE ? OR author LIKE ? OR category LIKE ? OR isbn LIKE ?
            ORDER BY title
            """,
            (pattern, pattern, pattern, pattern),
        )
        return result or []


class LoanManager:
    """Handles issue and return operations."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def view_user_loans(self, user_id: int) -> List[tuple]:
        result = self.db.execute_query(
            """
            SELECT l.loan_id, b.book_id, b.title, l.quantity, l.issued_at, l.due_date, l.returned_at, l.status
            FROM loans l
            JOIN books b ON l.book_id = b.book_id
            WHERE l.user_id = ?
            ORDER BY l.issued_at DESC
            """,
            (user_id,),
        )
        return result or []

    def view_all_loans(self) -> List[tuple]:
        result = self.db.execute_query(
            """
            SELECT l.loan_id, u.username, b.title, l.quantity, l.issued_at, l.due_date, l.returned_at, l.status
            FROM loans l
            JOIN users u ON l.user_id = u.user_id
            JOIN books b ON l.book_id = b.book_id
            ORDER BY l.issued_at DESC
            """
        )
        return result or []

    def borrow_book(self, user_id: int, username: str, book_id: int, quantity: int, action_label: str = "borrow") -> Tuple[bool, str]:
        if quantity <= 0:
            return False, "Quantity must be greater than zero."

        check = self.db.execute_query("SELECT quantity, title FROM books WHERE book_id = ?", (book_id,))
        if not check:
            return False, "Book not found."

        available_quantity, title = check[0]
        if available_quantity < quantity:
            return False, f"Insufficient stock. Available: {available_quantity}"

        due_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
        issued_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.db.execute_update(
            """
            INSERT INTO loans (user_id, book_id, quantity, issued_at, due_date, status)
            VALUES (?, ?, ?, ?, ?, 'issued')
            """,
            (user_id, book_id, quantity, issued_at, due_date),
        ):
            self.db.execute_update(
                "UPDATE books SET quantity = quantity - ? WHERE book_id = ?",
                (quantity, book_id),
            )
            self.db.log_activity(
                user_id,
                username,
                action_label,
                f"Borrowed book '{title}' x {quantity}. Due on {due_date}.",
            )
            return True, f"{title} borrowed successfully."

        return False, "Failed to borrow the book."

    def return_book(self, loan_id: int) -> Tuple[bool, str]:
        loan = self.db.execute_query(
            "SELECT user_id, book_id, quantity, status FROM loans WHERE loan_id = ?",
            (loan_id,),
        )
        if not loan:
            return False, "Loan not found."

        user_id, book_id, quantity, status = loan[0]
        if status == 'returned':
            return False, "This book has already been returned."

        user_row = self.db.execute_query("SELECT username FROM users WHERE user_id = ?", (user_id,))
        username = user_row[0][0] if user_row else "unknown"

        returned_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.db.execute_update(
            "UPDATE loans SET returned_at = ?, status = 'returned' WHERE loan_id = ?",
            (returned_at, loan_id),
        ):
            self.db.execute_update(
                "UPDATE books SET quantity = quantity + ? WHERE book_id = ?",
                (quantity, book_id),
            )
            self.db.log_activity(
                user_id,
                username,
                "return",
                f"Returned loan #{loan_id} with book_id {book_id} x {quantity}.",
            )
            return True, "Book returned successfully."

        return False, "Failed to return the book."

    def return_book_for_user(self, user_id: int, loan_id: int) -> Tuple[bool, str]:
        loan = self.db.execute_query("SELECT user_id FROM loans WHERE loan_id = ?", (loan_id,))
        if not loan:
            return False, "Loan not found."
        if loan[0][0] != user_id:
            return False, "You can only return your own borrowed books."
        return self.return_book(loan_id)


class LibraryApp:
    """Tkinter-based library management system."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Library Management System")
        self.root.geometry("1280x780")
        self.root.minsize(1120, 700)

        self.db = DatabaseManager()
        self.user_manager = UserManager(self.db)
        self.book_manager = BookManager(self.db)
        self.loan_manager = LoanManager(self.db)

        self.current_user_info: Optional[dict] = None
        self.admin_selected_book_id: Optional[int] = None

        self.login_username_var = tk.StringVar()
        self.login_password_var = tk.StringVar()
        self.login_role_var = tk.StringVar(value="user")

        self.register_username_var = tk.StringVar()
        self.register_email_var = tk.StringVar()
        self.register_password_var = tk.StringVar()
        self.register_confirm_var = tk.StringVar()

        self.user_search_var = tk.StringVar()
        self.admin_search_var = tk.StringVar()

        self.book_title_var = tk.StringVar()
        self.book_author_var = tk.StringVar()
        self.book_category_var = tk.StringVar()
        self.book_price_var = tk.StringVar()
        self.book_quantity_var = tk.StringVar()
        self.book_isbn_var = tk.StringVar()
        self.book_year_var = tk.StringVar()
        self.book_description_var = tk.StringVar()

        self.status_var = tk.StringVar(value="Ready")
        self.admin_activity_filter_var = tk.StringVar(value="All")

        self._configure_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")

        self.bg = "#f4f7fb"
        self.header_bg = "#18324a"
        self.accent = "#2d6cdf"
        self.accent_dark = "#1f4fbf"
        self.text_dark = "#1d2b36"

        self.root.configure(bg=self.bg)
        style.configure("Root.TFrame", background=self.bg)
        style.configure("Header.TFrame", background=self.header_bg)
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Section.TLabelframe", background=self.bg, padding=12)
        style.configure("Section.TLabelframe.Label", background=self.bg, foreground=self.text_dark, font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background=self.bg, foreground=self.text_dark, font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=self.header_bg, foreground="white", font=("Segoe UI", 20, "bold"))
        style.configure("SubHeader.TLabel", background=self.header_bg, foreground="#d7e4f1", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=self.bg, foreground=self.text_dark, font=("Segoe UI", 16, "bold"))
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=8)
        style.map("TButton", background=[("active", self.accent_dark), ("!disabled", self.accent)], foreground=[("!disabled", "white")])
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=28)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#dbe6f3", foreground=self.text_dark)
        style.map("Treeview", background=[("selected", "#cfe0ff")])
        style.configure("TNotebook", background=self.bg, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 10), font=("Segoe UI", 10, "bold"))
        style.configure("Status.TLabel", background="#e8eef6", foreground=self.text_dark, font=("Segoe UI", 10))

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, style="Root.TFrame", padding=12)
        container.pack(fill="both", expand=True)

        header = ttk.Frame(container, style="Header.TFrame", padding=(18, 14))
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="Library Management System", style="Header.TLabel").pack(anchor="w")
        ttk.Label(header, text="A modern desktop interface for books, users, loan tracking, and activity logs.", style="SubHeader.TLabel").pack(anchor="w", pady=(4, 0))

        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill="both", expand=True)

        self.login_tab = ttk.Frame(self.notebook, padding=18)
        self.register_tab = ttk.Frame(self.notebook, padding=18)
        self.user_tab = ttk.Frame(self.notebook, padding=12)
        self.admin_tab = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.login_tab, text="Login")
        self.notebook.add(self.register_tab, text="Register")
        self.notebook.add(self.user_tab, text="User Dashboard")
        self.notebook.add(self.admin_tab, text="Admin Dashboard")

        self.notebook.tab(self.user_tab, state="disabled")
        self.notebook.tab(self.admin_tab, state="disabled")

        self._build_login_tab()
        self._build_register_tab()
        self._build_user_tab()
        self._build_admin_tab()

        status_bar = ttk.Label(container, textvariable=self.status_var, style="Status.TLabel", anchor="w", padding=(12, 8))
        status_bar.pack(fill="x", pady=(12, 0))

    def _build_login_tab(self) -> None:
        content = ttk.Frame(self.login_tab)
        content.pack(fill="both", expand=True)

        left_card = ttk.LabelFrame(content, text="Sign in", style="Section.TLabelframe", padding=18)
        left_card.pack(side="left", fill="both", expand=True, padx=(0, 10))

        ttk.Label(left_card, text="Welcome back. Sign in to continue.", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 18))

        form = ttk.Frame(left_card)
        form.pack(fill="x")

        self._make_labeled_entry(form, "Username", self.login_username_var, 0)
        self._make_labeled_entry(form, "Password", self.login_password_var, 1, show="*")

        role_row = ttk.Frame(form)
        role_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(role_row, text="Login as").pack(side="left")
        role_box = ttk.Combobox(role_row, textvariable=self.login_role_var, values=["user", "admin"], state="readonly", width=12)
        role_box.pack(side="left", padx=(12, 0))

        action_row = ttk.Frame(form)
        action_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(action_row, text="Login", command=self.handle_login).pack(side="left")
        ttk.Button(action_row, text="Clear", command=self.clear_login_form).pack(side="left", padx=10)

        hint_card = ttk.LabelFrame(content, text="Notes", style="Section.TLabelframe", padding=18)
        hint_card.pack(side="right", fill="both", expand=True, padx=(10, 0))
        ttk.Label(
            hint_card,
            text=(
                "User accounts can be created from the Register tab.\n\n"
                "Admin access is available with the default credentials:\n"
                "Username: admin\n"
                "Password: Admin@123"
            ),
            justify="left",
            font=("Segoe UI", 11),
        ).pack(anchor="nw")

    def _build_register_tab(self) -> None:
        card = ttk.LabelFrame(self.register_tab, text="Create Account", style="Section.TLabelframe", padding=18)
        card.pack(fill="both", expand=True)

        ttk.Label(card, text="Create a new user account.", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))

        form = ttk.Frame(card)
        form.grid(row=1, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)

        self._make_labeled_entry(form, "Username", self.register_username_var, 0)
        self._make_labeled_entry(form, "Email", self.register_email_var, 1)
        self._make_labeled_entry(form, "Password", self.register_password_var, 2, show="*")
        self._make_labeled_entry(form, "Confirm Password", self.register_confirm_var, 3, show="*")

        button_row = ttk.Frame(form)
        button_row.grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Button(button_row, text="Register", command=self.handle_register).pack(side="left")
        ttk.Button(button_row, text="Clear", command=self.clear_register_form).pack(side="left", padx=10)

    def _build_user_tab(self) -> None:
        top_bar = ttk.Frame(self.user_tab)
        top_bar.pack(fill="x", pady=(0, 12))

        ttk.Label(top_bar, text="User Dashboard", style="Title.TLabel").pack(side="left")

        search_row = ttk.Frame(top_bar)
        search_row.pack(side="right")
        ttk.Entry(search_row, textvariable=self.user_search_var, width=32).pack(side="left", padx=(0, 8))
        ttk.Button(search_row, text="Search", command=self.search_user_books).pack(side="left")
        ttk.Button(search_row, text="Show All", command=self.refresh_user_dashboard).pack(side="left", padx=8)
        ttk.Button(search_row, text="Logout", command=self.logout).pack(side="left")

        panes = ttk.Panedwindow(self.user_tab, orient="horizontal")
        panes.pack(fill="both", expand=True)

        books_frame = ttk.LabelFrame(panes, text="Available Books", style="Section.TLabelframe", padding=12)
        loans_frame = ttk.LabelFrame(panes, text="My Borrowed Books", style="Section.TLabelframe", padding=12)
        panes.add(books_frame, weight=3)
        panes.add(loans_frame, weight=2)

        self.user_books_tree = self._create_treeview(
            books_frame,
            ("ID", "Title", "Author", "Category", "Price", "Stock"),
            (60, 250, 180, 140, 100, 90),
        )

        user_books_actions = ttk.Frame(books_frame)
        user_books_actions.pack(fill="x", pady=(10, 0))
        ttk.Button(user_books_actions, text="Borrow / Buy Selected Book", command=self.borrow_selected_book).pack(side="left")
        ttk.Button(user_books_actions, text="Refresh", command=self.refresh_user_dashboard).pack(side="left", padx=8)

        borrowed_tab = ttk.Frame(loans_frame)
        borrowed_tab.pack(fill="both", expand=True)

        self.user_loan_tree = self._create_treeview(
            borrowed_tab,
            ("Loan ID", "Book ID", "Title", "Qty", "Issued At", "Due Date", "Returned At", "Status"),
            (70, 70, 180, 60, 130, 130, 130, 90),
        )

        loans_actions = ttk.Frame(borrowed_tab)
        loans_actions.pack(fill="x", pady=(10, 0))
        ttk.Button(loans_actions, text="Return Selected Loan", command=self.return_selected_user_loan).pack(side="left")
        ttk.Button(loans_actions, text="Refresh", command=self.refresh_user_dashboard).pack(side="left", padx=8)

    def _build_admin_tab(self) -> None:
        top_bar = ttk.Frame(self.admin_tab)
        top_bar.pack(fill="x", pady=(0, 12))

        ttk.Label(top_bar, text="Admin Dashboard", style="Title.TLabel").pack(side="left")

        search_row = ttk.Frame(top_bar)
        search_row.pack(side="right")
        ttk.Entry(search_row, textvariable=self.admin_search_var, width=32).pack(side="left", padx=(0, 8))
        ttk.Button(search_row, text="Search", command=self.search_admin_books).pack(side="left")
        ttk.Button(search_row, text="Show All", command=self.refresh_admin_dashboard).pack(side="left", padx=8)
        ttk.Button(search_row, text="Logout", command=self.logout).pack(side="left")

        panes = ttk.Panedwindow(self.admin_tab, orient="horizontal")
        panes.pack(fill="both", expand=True)

        books_frame = ttk.LabelFrame(panes, text="Books", style="Section.TLabelframe", padding=12)
        loans_frame = ttk.LabelFrame(panes, text="Records", style="Section.TLabelframe", padding=12)
        panes.add(books_frame, weight=3)
        panes.add(loans_frame, weight=2)

        self.admin_books_tree = self._create_treeview(
            books_frame,
            ("ID", "Title", "Author", "Category", "Price", "Qty"),
            (60, 250, 180, 140, 100, 70),
        )
        self.admin_books_tree.bind("<<TreeviewSelect>>", self.on_admin_book_select)

        admin_book_actions = ttk.Frame(books_frame)
        admin_book_actions.pack(fill="x", pady=(10, 0))
        ttk.Button(admin_book_actions, text="Refresh", command=self.refresh_admin_dashboard).pack(side="left")
        ttk.Button(admin_book_actions, text="Load Selected", command=self.load_selected_admin_book).pack(side="left", padx=8)

        admin_records_tabs = ttk.Notebook(loans_frame)
        admin_records_tabs.pack(fill="both", expand=True)

        admin_loans_tab = ttk.Frame(admin_records_tabs)
        admin_activity_tab = ttk.Frame(admin_records_tabs)
        admin_records_tabs.add(admin_loans_tab, text="Loan History")
        admin_records_tabs.add(admin_activity_tab, text="Activity Log")

        self.admin_loan_tree = self._create_treeview(
            admin_loans_tab,
            ("Loan ID", "User", "Book", "Qty", "Issued At", "Due Date", "Returned At", "Status"),
            (70, 120, 150, 60, 130, 130, 130, 90),
        )

        loan_actions = ttk.Frame(admin_loans_tab)
        loan_actions.pack(fill="x", pady=(10, 0))
        ttk.Button(loan_actions, text="Mark Return", command=self.mark_selected_loan_returned).pack(side="left")
        ttk.Button(loan_actions, text="Refresh", command=self.refresh_admin_dashboard).pack(side="left", padx=8)

        admin_activity_filter_row = ttk.Frame(admin_activity_tab)
        admin_activity_filter_row.pack(fill="x", pady=(0, 8))
        ttk.Label(admin_activity_filter_row, text="Filter").pack(side="left")
        ttk.Combobox(
            admin_activity_filter_row,
            textvariable=self.admin_activity_filter_var,
            values=["All", "borrow", "return", "register", "login"],
            state="readonly",
            width=14,
        ).pack(side="left", padx=8)
        ttk.Button(admin_activity_filter_row, text="Refresh", command=self.refresh_admin_dashboard).pack(side="left")

        self.admin_activity_tree = self._create_treeview(
            admin_activity_tab,
            ("Activity ID", "User", "Action", "Details", "Time"),
            (80, 120, 100, 380, 170),
        )

        ttk.Label(books_frame, text="Select a book to view or update its details below.").pack(anchor="w", pady=(10, 4))

        form_host = self._create_scrollable_container(books_frame)
        form = ttk.Frame(form_host)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)

        self._make_labeled_entry(form, "Title", self.book_title_var, 0)
        self._make_labeled_entry(form, "Author", self.book_author_var, 1)
        self._make_labeled_entry(form, "Category", self.book_category_var, 2)
        self._make_labeled_entry(form, "Price", self.book_price_var, 3)
        self._make_labeled_entry(form, "Quantity", self.book_quantity_var, 4)
        self._make_labeled_entry(form, "ISBN", self.book_isbn_var, 5)
        self._make_labeled_entry(form, "Published Year", self.book_year_var, 6)
        self._make_labeled_entry(form, "Description", self.book_description_var, 7)

        form_buttons = ttk.Frame(form_host)
        form_buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(form_buttons, text="Add Book", command=self.add_book_from_form).pack(side="left")
        ttk.Button(form_buttons, text="Update Selected", command=self.update_selected_book).pack(side="left", padx=8)
        ttk.Button(form_buttons, text="Delete Selected", command=self.delete_selected_book).pack(side="left")
        ttk.Button(form_buttons, text="Clear Form", command=self.clear_admin_form).pack(side="left", padx=8)

    def _make_labeled_entry(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, show: Optional[str] = None) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=6)
        entry = ttk.Entry(parent, textvariable=variable, show=show)
        entry.grid(row=row, column=1, sticky="ew", pady=6)

    def _create_treeview(self, parent: ttk.Frame, columns: Tuple[str, ...], widths: Tuple[int, ...]) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        for column, width in zip(columns, widths):
            tree.heading(column, text=column)
            tree.column(column, width=width, anchor="w", stretch=True)

        scrollbar_y = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        scrollbar_x = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        tree.pack(side="left", fill="both", expand=True)
        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x.pack(side="bottom", fill="x")
        return tree

    def _create_scrollable_container(self, parent: ttk.Frame) -> ttk.Frame:
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True, pady=(8, 0))

        canvas = tk.Canvas(container, background=self.bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable_id = canvas.create_window((0, 0), window=scrollable, anchor="nw")

        def on_frame_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event):
            canvas.itemconfigure(scrollable_id, width=event.width)

        scrollable.bind("<Configure>", on_frame_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        return scrollable

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _show_error(self, text: str) -> None:
        messagebox.showerror("Error", text)
        self._set_status(text)

    def _show_info(self, text: str) -> None:
        messagebox.showinfo("Success", text)
        self._set_status(text)

    def clear_login_form(self) -> None:
        self.login_username_var.set("")
        self.login_password_var.set("")
        self.login_role_var.set("user")

    def clear_register_form(self) -> None:
        self.register_username_var.set("")
        self.register_email_var.set("")
        self.register_password_var.set("")
        self.register_confirm_var.set("")

    def clear_admin_form(self) -> None:
        self.admin_selected_book_id = None
        self.book_title_var.set("")
        self.book_author_var.set("")
        self.book_category_var.set("")
        self.book_price_var.set("")
        self.book_quantity_var.set("")
        self.book_isbn_var.set("")
        self.book_year_var.set("")
        self.book_description_var.set("")
        self.admin_books_tree.selection_remove(self.admin_books_tree.selection())

    def _enable_dashboard(self, role: str) -> None:
        if role == "admin":
            self.notebook.tab(self.admin_tab, state="normal")
            self.notebook.select(self.admin_tab)
            self.notebook.tab(self.user_tab, state="disabled")
        else:
            self.notebook.tab(self.user_tab, state="normal")
            self.notebook.select(self.user_tab)
            self.notebook.tab(self.admin_tab, state="disabled")

    def _disable_dashboard(self) -> None:
        self.notebook.tab(self.user_tab, state="disabled")
        self.notebook.tab(self.admin_tab, state="disabled")
        self.notebook.select(self.login_tab)

    def handle_login(self) -> None:
        username = self.login_username_var.get().strip()
        password = self.login_password_var.get().strip()
        role = self.login_role_var.get().strip().lower()

        if not username or not password:
            self._show_error("Username and password are required.")
            return

        if role == "admin" and username == "admin" and password == "Admin@123":
            self.current_user_info = self.user_manager.set_current_admin()
            self.db.log_activity(0, "admin", "login", "Administrator signed in.")
            self._enable_dashboard("admin")
            self.refresh_admin_dashboard()
            self._show_info("Admin login successful.")
            return

        success, message, user_info = self.user_manager.login_user(username, password)
        if not success or user_info is None:
            self._show_error(message)
            return

        if role == "admin":
            self._show_error("Use the admin credentials to sign in as an administrator.")
            self.user_manager.logout()
            return

        if user_info["role"] != "user":
            self._show_error("This account is not a standard user account.")
            self.user_manager.logout()
            return

        self.current_user_info = user_info
        self.db.log_activity(user_info["user_id"], user_info["username"], "login", "User signed in.")
        self._enable_dashboard("user")
        self.refresh_user_dashboard()
        self._show_info("Login successful.")

    def handle_register(self) -> None:
        username = self.register_username_var.get().strip()
        email = self.register_email_var.get().strip()
        password = self.register_password_var.get().strip()
        confirm_password = self.register_confirm_var.get().strip()

        success, message = self.user_manager.register_user(username, email, password, confirm_password)
        if success:
            self._show_info(message)
            self.clear_register_form()
        else:
            self._show_error(message)

    def refresh_user_dashboard(self) -> None:
        if not self.current_user_info:
            return

        search_term = self.user_search_var.get().strip()
        books = self.book_manager.search_books(search_term) if search_term else self.book_manager.list_books()

        self._fill_tree(
            self.user_books_tree,
            [
                (book_id, title, author, category, f"{price:.2f}", quantity)
                for book_id, title, author, category, price, quantity, *_ in books
            ],
        )

        loan_rows = self.loan_manager.view_user_loans(self.current_user_info["user_id"])
        self._fill_tree(
            self.user_loan_tree,
            [
                (loan_id, book_id, title, quantity, issued_at, due_date, returned_at or "", status)
                for loan_id, book_id, title, quantity, issued_at, due_date, returned_at, status in loan_rows
            ],
        )

        active_loans = sum(1 for row in loan_rows if row[7] == 'issued')
        self._set_status(f"User dashboard loaded. Active loans: {active_loans}")

    def search_user_books(self) -> None:
        self.refresh_user_dashboard()

    def borrow_selected_book(self) -> None:
        if not self.current_user_info:
            return

        selection = self.user_books_tree.selection()
        if not selection:
            self._show_error("Select a book first.")
            return

        values = self.user_books_tree.item(selection[0], "values")
        book_id = int(values[0])
        book_title = values[1]
        quantity = simpledialog.askinteger("Borrow Book", f"Enter quantity for '{book_title}':", minvalue=1, parent=self.root)
        if quantity is None:
            return

        success, message = self.loan_manager.borrow_book(
            self.current_user_info["user_id"],
            self.current_user_info["username"],
            book_id,
            quantity,
        )
        if success:
            self._show_info(message)
            self.refresh_user_dashboard()
        else:
            self._show_error(message)

    def return_selected_user_loan(self) -> None:
        if not self.current_user_info:
            return

        selection = self.user_loan_tree.selection()
        if not selection:
            self._show_error("Select a borrowed book first.")
            return

        values = self.user_loan_tree.item(selection[0], "values")
        loan_id = int(values[0])
        success, message = self.loan_manager.return_book_for_user(self.current_user_info["user_id"], loan_id)
        if success:
            self._show_info(message)
            self.refresh_user_dashboard()
        else:
            self._show_error(message)

    def refresh_admin_dashboard(self) -> None:
        if not self.current_user_info or self.current_user_info.get("role") != "admin":
            return

        search_term = self.admin_search_var.get().strip()
        books = self.book_manager.search_books(search_term) if search_term else self.book_manager.list_books()

        self._fill_tree(
            self.admin_books_tree,
            [
                (book_id, title, author, category, f"{price:.2f}", quantity)
                for book_id, title, author, category, price, quantity, *_ in books
            ],
        )

        loans = self.loan_manager.view_all_loans()
        self._fill_tree(
            self.admin_loan_tree,
            [
                (loan_id, username, title, quantity, issued_at, due_date, returned_at or "", status)
                for loan_id, username, title, quantity, issued_at, due_date, returned_at, status in loans
            ],
        )

        activity_rows = self.db.get_all_activity()
        admin_filter = self.admin_activity_filter_var.get().strip().lower()
        if admin_filter and admin_filter != "all":
            activity_rows = [row for row in activity_rows if row[2] == admin_filter]
        self._fill_tree(self.admin_activity_tree, activity_rows)

        issued_count = sum(1 for row in loans if row[7] == 'issued')
        returned_count = sum(1 for row in loans if row[7] == 'returned')
        self._set_status(f"Admin dashboard loaded. Books: {len(books)} | Issued: {issued_count} | Returned: {returned_count}")

    def search_admin_books(self) -> None:
        self.refresh_admin_dashboard()

    def on_admin_book_select(self, _event=None) -> None:
        selection = self.admin_books_tree.selection()
        if not selection:
            return
        values = self.admin_books_tree.item(selection[0], "values")
        self._populate_admin_form(int(values[0]))

    def load_selected_admin_book(self) -> None:
        selection = self.admin_books_tree.selection()
        if not selection:
            self._show_error("Select a book first.")
            return
        values = self.admin_books_tree.item(selection[0], "values")
        self._populate_admin_form(int(values[0]))

    def mark_selected_loan_returned(self) -> None:
        selection = self.admin_loan_tree.selection()
        if not selection:
            self._show_error("Select a loan first.")
            return

        values = self.admin_loan_tree.item(selection[0], "values")
        loan_id = int(values[0])
        success, message = self.loan_manager.return_book(loan_id)
        if success:
            self._show_info(message)
            self.refresh_admin_dashboard()
            self.refresh_user_dashboard()
        else:
            self._show_error(message)

    def _populate_admin_form(self, book_id: int) -> None:
        book = self.book_manager.get_book(book_id)
        if not book:
            self._show_error("Book not found.")
            return

        self.admin_selected_book_id = book_id
        _, title, author, category, price, quantity, isbn, published_year, description = book
        self.book_title_var.set(title)
        self.book_author_var.set(author)
        self.book_category_var.set(category)
        self.book_price_var.set(str(price))
        self.book_quantity_var.set(str(quantity))
        self.book_isbn_var.set(isbn or "")
        self.book_year_var.set(str(published_year) if published_year is not None else "")
        self.book_description_var.set(description or "")

    def add_book_from_form(self) -> None:
        try:
            price = float(self.book_price_var.get().strip())
            quantity = int(self.book_quantity_var.get().strip())
            published_year_text = self.book_year_var.get().strip()
            published_year = int(published_year_text) if published_year_text else None
        except ValueError:
            self._show_error("Price, quantity, and published year must be numeric.")
            return

        success, message = self.book_manager.add_book(
            title=self.book_title_var.get().strip(),
            author=self.book_author_var.get().strip(),
            category=self.book_category_var.get().strip(),
            price=price,
            quantity=quantity,
            isbn=self.book_isbn_var.get().strip() or None,
            published_year=published_year,
            description=self.book_description_var.get().strip() or None,
        )

        if success:
            self._show_info(message)
            self.clear_admin_form()
            self.refresh_admin_dashboard()
        else:
            self._show_error(message)

    def update_selected_book(self) -> None:
        if self.admin_selected_book_id is None:
            selection = self.admin_books_tree.selection()
            if not selection:
                self._show_error("Select a book first.")
                return
            values = self.admin_books_tree.item(selection[0], "values")
            self.admin_selected_book_id = int(values[0])

        fields = {
            "title": self.book_title_var.get().strip() or None,
            "author": self.book_author_var.get().strip() or None,
            "category": self.book_category_var.get().strip() or None,
            "isbn": self.book_isbn_var.get().strip() or None,
            "description": self.book_description_var.get().strip() or None,
        }

        try:
            price_text = self.book_price_var.get().strip()
            quantity_text = self.book_quantity_var.get().strip()
            year_text = self.book_year_var.get().strip()

            if price_text:
                fields["price"] = float(price_text)
            if quantity_text:
                fields["quantity"] = int(quantity_text)
            if year_text:
                fields["published_year"] = int(year_text)
        except ValueError:
            self._show_error("Price, quantity, and published year must be numeric.")
            return

        success, message = self.book_manager.update_book(self.admin_selected_book_id, **fields)
        if success:
            self._show_info(message)
            self.refresh_admin_dashboard()
        else:
            self._show_error(message)

    def delete_selected_book(self) -> None:
        selection = self.admin_books_tree.selection()
        if self.admin_selected_book_id is None and not selection:
            self._show_error("Select a book first.")
            return

        book_id = self.admin_selected_book_id if self.admin_selected_book_id is not None else int(self.admin_books_tree.item(selection[0], "values")[0])
        if not messagebox.askyesno("Confirm Delete", "Delete the selected book?"):
            return

        success, message = self.book_manager.delete_book(book_id)
        if success:
            self._show_info(message)
            self.clear_admin_form()
            self.refresh_admin_dashboard()
        else:
            self._show_error(message)

    def _fill_tree(self, tree: ttk.Treeview, rows: List[tuple]) -> None:
        for item in tree.get_children():
            tree.delete(item)
        for row in rows:
            tree.insert("", "end", values=row)

    def logout(self) -> None:
        if not self.current_user_info:
            self._disable_dashboard()
            return

        if messagebox.askyesno("Logout", "Log out of the current account?"):
            self.user_manager.logout()
            self.current_user_info = None
            self.user_search_var.set("")
            self.admin_search_var.set("")
            self.clear_login_form()
            self.clear_register_form()
            self.clear_admin_form()
            self._disable_dashboard()
            self._set_status("Logged out.")

    def on_close(self) -> None:
        self.db.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    app = LibraryApp()
    app.run()
