# The Onigiri Shop — Management System

This Python application is a menu-driven management system for an Onigiri shop. It manages ingredients, recipes, orders, inventory deductions, low-stock alerts, suppliers and purchasing, customer/employee accounts, self-service profiles, loyalty points and rewards, employee payroll, a shared Accounting Ledger, and sales/inventory/revenue trend predictions, plus customer feedback submission and staff review. Owners can optionally load separate test datasets for inventory, accounting, trends and payroll.

**The database is persistent.** Data is stored in a local SQLite file named `btm495.db` (the existing filename is retained so older installations keep working). The application creates that file **only if it does not already exist**. On subsequent launches, it reads and updates the same file; it does not wipe the database on startup. You do **not** need to run the original `database.py` or `main.py` to use this application.

> **Important:** The reset and restore options *do* replace the active database, but only when an Owner selects and confirms those actions. Every reset creates a backup first. If other applications or modules share this SQLite file, read [Section 8](#8-sample-data-backups-resets-and-restore) before performing a reset.

---

## Optional sample users and profiles — only through option 21

The ZIP starts **without a preloaded user database**. The first run prompts you to create **your own Owner account**. **No fictional users are loaded automatically on startup.** To add eight fictional accounts, sign in as Owner and select **21 → 7 — Load 8 fictional sample users and profiles**. Confirm the action and verify your Owner password. The loader preserves existing users, inventory and orders. It skips already-imported accounts on later runs, even if their details were edited. The sample-user loader **does not auto-enroll sample customers or create loyalty transactions**; customers enroll through option 5. The optional usernames and passwords are documented in [Section 8](#8-sample-data-backups-resets-and-restore).

---

## Sample loyalty rewards (option 5)

The first time an Owner, Employee, or Customer opens **5 — Loyalty Program**, the
app adds four demonstration discounts to the shared SQLite `Reward` table:

| Example reward | Points required |
|---|---:|
| $5 CAD discount | 1,000 |
| $10 CAD discount | 2,000 |
| $15 CAD discount | 3,000 |
| $20 CAD discount | 4,000 |

Owners/Employees can see the full catalogue using **5 → 6 — List rewards**.
Customers who join the loyalty program see these in **5 — My Loyalty**,
including whether their existing balance covers each reward. During order
completion (options **1** or **2**), the program automatically offers any
affordable applicable discount and records earned points. Option **5 → 5**
remains available for older completed orders that have no loyalty transaction.
The loyalty discount does not change `Order.totalAmount`, which remains the
original menu-price total. The Accounting Ledger records the sale's **net value
after any loyalty discount**. This is an internal financial posting, not an
actual card charge or bank settlement.

The examples are not seeded at first-time setup, and importing fictional users
via **21 → 7** remains optional and independent. Returning to option 5 does
not duplicate sample rewards or re-enable rewards an Owner deactivated. Owners
can add other rewards under **5 → 7**. Reward point costs and discounts are
configurable sample values, not legal or externally mandated amounts. Earning
now defaults to **10 points per $1 CAD of eligible spending**, with whole points rounded down. For example, $10 earns 100 points and $100 earns 1,000 points; the $5 discount is therefore an illustrative **5% effective reward rate**. Any previous active sample reward with the exact old name, cost and discount is updated in place the next time option 5 opens. Modified and deactivated rewards remain untouched; existing loyalty balances and transaction history are not recalculated.

## 1. Requirements

- **Python 3.10 or later**, installed on your computer.
- Windows, macOS or Linux. The supplied `START_HERE.bat` launcher works **on Windows only**; other systems can run the Python command below.
- A terminal or Command Prompt (Windows Terminal, Command Prompt, PowerShell, or the VS Code terminal).
- Permission to create files in the application folder.

The main application uses Python's standard library, including `sqlite3`. **Matplotlib is required only for the pop-up graphs in option 19.** If it is not installed, the numerical forecasts and every other menu still work. To enable graphs, install Matplotlib once in the **same Python environment** you use to launch the application:

Windows:

```bat
py -m pip install matplotlib
```

macOS / Linux:

```bash
python3 -m pip install matplotlib
```

Graph windows also require a desktop session with a graphical Matplotlib backend (such as TkAgg or QtAgg). A headless server or non-interactive backend such as Agg cannot open a window; the application will explain that limitation without interrupting the forecast.

To check your Python installation on Windows, open Command Prompt and enter:

```bat
py --version
```

If that command is not recognized, try `python --version`. On macOS or Linux, use `python3 --version`. If Python is missing, install Python 3.10+ before continuing. On Windows, make sure the Python launcher or the `python` command is available.

## 2. Install and launch

### Windows — launcher

1. Clone or download the repository, or extract all application files to a permanent folder such as `Documents\OnigiriInventory`.
2. Open the extracted folder and double-click **`START_HERE.bat`**.
3. A command window will open, initialize or connect to the database, and display the setup/login screen.
4. Follow the on-screen prompts. When you finish, choose **`0 — Exit`**.

### Windows — terminal method

Open Command Prompt or the VS Code terminal in the extracted folder, then run:

```bat
py inventory_cli.py
```

Alternatively:

```bat
python inventory_cli.py
```

You can also navigate to the folder yourself; use quotation marks around a path containing spaces:

```bat
cd "%USERPROFILE%\Documents\OnigiriInventory"
py inventory_cli.py
```

### macOS / Linux

Open a terminal, navigate to the extracted folder, and run:

```bash
python3 inventory_cli.py
```

**Tip:** Keep all application `.py` files together in the same folder. Running `inventory_cli.py` alone without its companion files will produce a module import error.

### Files included

| File | Purpose | Edit it for ordinary use? |
|---|---|---|
| `inventory_cli.py` | Main menu, login prompts, input and output | No |
| `inventory_service.py` | Business rules: inventory, recipes, orders, deliveries, alerts, shared login accounts | No |
| `profile_service.py` | Profile model, validation, viewing and atomic updates | No |
| `feedback_service.py` | Validated customer submissions, feedback history and staff review permissions | No |
| `user_management_service.py` | Owner-only management of shared User accounts, roles, credentials and activation | No |
| `inventory_db.py` | SQLite database connection, tables and compatible schema additions | No |
| `demo_tools.py` | Sample Onigiri data; backup, reset and restore actions | No |
| `sample_users.py` | **Optional** fictional user + profile import, only through Owner option 21 → 7 | No |
| `loyalty_service.py`, `loyalty_models.py` | Loyalty accounts, rewards, earned points and redemptions | No |
| `payroll_service.py`, `payroll.py` | Owner-only payroll workflow, calculations, pay stubs and expense recording | No |
| `accounting_service.py` | Shared financial ledger, automatic source-linked postings, summaries and discrepancy checks | No |
| `trend_prediction_service.py` | Read-only sales, ingredient consumption and net order-revenue estimates with optional Matplotlib pop-up charts | No |
| `test_payroll.py`, `test_integrated_system.py` | Payroll and cross-feature regression tests | Optional |
| `test_accounting.py`, `test_accounting_integration.py` | Ledger, legacy database and cross-module financial posting tests | Optional |
| `test_trend_prediction.py` | Forecast calculations, loyalty-aware revenue, empty-data screens and menu integration tests | Optional |
| `test_demo_datasets.py` | Optional sample-data imports, duplicate prevention, audit trail and forecast regression tests | Optional |
| `test_loyalty.py`, `test_loyalty_diagrams.py`, `test_loyalty_profile_integration.py` | Loyalty, domain-model and combined profile tests | Optional |
| `test_sample_users.py` | Tests for optional import, permissions and safe repetition | Optional |
| `START_HERE.bat` | Windows double-click launcher | No |
| `README.md` | This setup and menu guide | Read this |
| `test_inventory.py` | Automated inventory feature tests | Optional |
| `test_demo_tools.py` | Automated sample data, backup and reset tests | Optional |
| `test_profile.py` | Profile role, validation, persistence, cancellation and rollback tests | Optional |
| `test_user_management.py` | Tests for Owner-only management, safe deletion, password resets and role changes | Optional |
| `test_feedback.py` | Feedback tests for permissions, input, cancel/back navigation, account integration, and storage failures | Optional |
| `test_main_menu_navigation.py` | Checks the grouped menu, every management option, Customer access and logout navigation | Optional |
| `btm495.db` | **Your saved database, created automatically on first run** | **Keep it** |
| `backups/` | Dated database backups, created when needed | **Keep it** |

The `.db` file and the `backups/` folder are not bundled with the downloadable code. They are generated on your own computer when you use the application. To update an existing installation, replace its `.py` source files and README while **retaining your existing `btm495.db` and `backups/` folder**. See the database-migration instructions below.

## 3. First-time setup and login

### First launch: create the initial Owner

If the database has no login-enabled users, the application displays **FIRST-TIME SETUP**. Enter:

1. Owner's name.
2. A unique Owner username.
3. An Owner password of **at least eight characters**.
4. Then, at the normal login screen, sign in using that username and password.

The password is hidden while you type it; a blank-looking password line is normal. Credentials are saved to the SQLite database. Passwords are stored using salted PBKDF2-SHA256 hashes, not as plain text.

### Returning to the application

Every later launch normally goes **directly to the Login screen**. Enter the same username and password you created previously. You do not have to register again. Usernames are **not case-sensitive**; passwords are case-sensitive.

Enter `exit` at the username prompt to close the application without signing in. From the main menu, choose **23 — Log out** to return to the login screen, or **0 — Exit** to close the application completely.

### Add Employees, Customers or another Owner

1. Sign in as an Owner.
2. Select **20 — Manage users**.
3. Review existing users, then choose **2 — Create new user**.
4. Select `e` for **Employee**, `o` for **Owner**, or `c` for **Customer**.
5. Enter the person's name and unique username, optional email address, phone number and date of birth (press Enter to skip any of these), and password (twice). If provided, the date of birth must use **YYYY-MM-DD**.
6. The new user can now sign in after you log out.

The Owner's **3 — Edit user information** option supports the same profile information: name, username, email, phone number and date of birth. Role changes and password resets are handled separately. All signed-in Owners, Employees and Customers (including imported sample users) can use **22 — My Profile** to add, edit, or clear their email address, edit their name, phone number, and date of birth. Username and role remain read-only here; the Owner can edit usernames through option 20.

Owners and Employees can use the original inventory and ordering menus. Customers can sign in and view/update **their own profile and loyalty history**, and submit/view **their own feedback**; inventory administration is unavailable to Customers. Only an **Owner** can manage all users in option 20 or open **21 — Demo / backup / reset**. Staff can register new loyalty customers through option 5 → 1. Be careful when adding another Owner: that person can also reset and restore the database.

Only Owners can run payroll through **17 — Payroll**. Employee accounts must exist (option **20 → 2**) and have an hourly rate (option **17 → 7**) before their payroll can be calculated. Payroll is a simplified local recordkeeping workflow; it does not transfer money to employees or submit statutory filings.

> Owners can now reset an account password or disable and reactivate logins without destroying the account history. When a disabled user enters their correct password, the login screen tells them their account is disabled and to contact an Owner. Account removal is only possible when the user has no related business records.

## 4. Main menu reference

After a successful login, the menu stays open in a loop. Type an option number and press **Enter**. After completing an action, press Enter to return to the main menu. An invalid menu number displays a message and lets you try again. The staff/Owner menu groups related options into **Orders & Customers**, **Inventory & Purchasing**, **Management & Reporting**, and **Account**. Options run from **1–23**, followed by **0 — Exit**; Customers can use options **5, 6, 22, 23, and 0** only.

| Option | Menu name | What it does |
|---|---|---|
| **1** | Create customer order | Selects recipes, servings and an optional Customer ID, saves a Pending order, and optionally completes it with stock and loyalty updates. |
| **2** | View/complete customer orders | Reviews orders and linked Customer IDs, completes a Pending order with stock/loyalty updates, or cancels one. |
| **3** | Create/edit recipe | Creates a menu recipe and defines or changes the ingredients required per serving. |
| **4** | View recipes | Lists recipes and lets you inspect a recipe's ingredients. |
| **5** | Loyalty Program / My Loyalty | Staff register/enroll/find customers, view rewards and history, and manage loyalty; Customers see their own account. |
| **6** | Feedback System | Customers submit written feedback, optionally rate 1–5 and view their submissions. Employees/Owners view all submissions and mark them Reviewed. |
| **7** | View inventory | Shows ingredient IDs, names, quantities, measurement units, reorder levels, and OK/LOW status. |
| **8** | Add ingredient | Adds a new ingredient with a starting quantity, unit and reorder level. |
| **9** | Manually adjust inventory | Adds or removes stock and optionally records a separately valued accounting adjustment. |
| **10** | Set reorder level | Changes the reorder threshold **for an individual ingredient** and updates its alerts. |
| **11** | Review low-stock alerts | Shows active alerts and allows them to be marked Reviewed or Closed. |
| **12** | Create inventory purchase order | Creates a confirmed order for ingredients that need replenishment. |
| **13** | View inventory purchase orders | Shows order status and quantities ordered, received and still outstanding. |
| **14** | Receive supplier delivery | Receives ingredients, optionally linked to a supplier/purchase order, and records an accounting Purchase when the invoice amount is supplied. |
| **15** | Manage suppliers | Lists suppliers and allows you to add one with contact information. |
| **16** | View transaction history | Lists the most recent inventory transactions, including manual changes and order deductions. |
| **17** | Payroll (**Owner only**) | Set hourly rates, create pay runs, enter hours, calculate/approve payroll, generate pay stubs and record paid payroll expenses. Not available to Customers. |
| **18** | Accounting Ledger (**Owner only**) | Review all financial transactions, enter manual transactions, reconcile references, and resolve discrepancies. Automatically linked sales, payroll expenses, purchases and valued inventory adjustments are shown together. |
| **19** | Trend Predicting Dashboard | View completed-order counts, ingredient consumption and discounted order-revenue histories; calculate simple trends and estimates. Available to Owners and Employees. |
| **20** | Manage users (**Owner only**) | View, create, edit, change role, reset password, disable/reactivate and (where safe) delete user accounts. |
| **21** | Demo / backup / reset (**Owner only**) | Choose individual sample datasets for inventory, historical sales/consumption, accounting or payroll; create backups, reset or restore the database. |
| **22** | My Profile | View and update the signed-in Customer, Employee or Owner profile. |
| **23** | Log out | Returns to the username/password login screen. |
| **0** | Exit | Closes the program without deleting saved data. |

### Useful input conventions

- **IDs** are the positive whole numbers shown in list screens. Use the displayed ID, not an ingredient's position in the list.
- For inventory quantities, decimals are allowed (for example, `0.5`). When creating customer orders, servings must be **whole numbers**.
- Units are selected when an ingredient is created and used consistently in its recipes. For example, if Rice is measured in `g`, entering `120` in a recipe means **120 g per serving**, not 120 kg.
- Enter **positive quantities** when adding, removing or receiving stock. For a new ingredient's *starting quantity* and for a *reorder level*, zero is permitted.
- When entering multiple ingredient or recipe lines, **leave the next ID blank and press Enter to finish**. Confirm the operation when prompted. Pressing Enter by itself is **not** a universal cancel command; it cancels or finishes only when the prompt explicitly says so.
- Confirmations normally accept `y` for Yes or `n` for No. The default is shown in square brackets where applicable.
- If an operation fails validation or the database save fails, the application displays an error rather than partially saving the transaction.

## 5. Inventory and low-stock walkthrough (options 7–11)

### View and add an ingredient

**Option 7** displays the current inventory. Each ingredient shows its `ID`, quantity on hand, unit, reorder level and `OK`/`LOW` status.

To add an ingredient, choose **8** and provide its name, measurement unit, starting quantity and reorder level, then confirm. Duplicate ingredient names are rejected. An ingredient with starting stock below its reorder level immediately qualifies for a low-stock alert.

### How the LOW condition works

An ingredient is **LOW when its current quantity is below its reorder level**:

```text
LOW: current quantity < reorder level
OK:  current quantity >= reorder level
```

For example, if Sushi Rice has **1,130 g** available and a reorder level of **1,200 g**, its status is **LOW**. If its quantity reaches exactly 1,200 g, its status becomes **OK**.

**Each ingredient has its own reorder level.** To edit one:

1. Choose **10 — Set reorder level**.
2. Find the ingredient in the displayed inventory list.
3. Enter its ingredient ID.
4. Enter the new threshold (for example, `1500`).
5. Review the updated list. The new level is immediately saved, and alerts are synchronized.

Setting the reorder level to **0** effectively disables LOW alerts for that ingredient because stock cannot become negative.

### Add or remove inventory manually

1. Select **9 — Manually adjust inventory**.
2. Choose the ingredient's ID.
3. Enter `a` to **add** stock or `r` to **remove** it.
4. Enter a positive adjustment quantity and, optionally, a reason.
5. Confirm. The new quantity is saved, and a transaction is recorded.

The program **does not allow stock to fall below zero**. If you try to remove more than what is available, the change is rejected and stock is left unchanged.

### Review low-stock alerts

Choose **11 — Review low-stock alerts** to see active alerts. A change that moves an ingredient below its threshold generates an alert if it has no active one. You can:

- Enter `r` to mark the selected alert **Reviewed** (it stays on the active list).
- Enter `c` to mark it **Closed** (it leaves the active list).
- Leave the alert ID blank to return without changing it.

When inventory is replenished to **at least** the reorder level, the application automatically closes active alerts for that ingredient. If you manually close an alert while stock is still low, another alert can be created after a later stock change.

## 6. Recipes and customer orders (options 1–4)

### Create a recipe (option 3)

1. Select **3 — Create/edit recipe**, then confirm that you want to create a new recipe.
2. Enter the recipe's name (such as `Tuna Mayo Onigiri`) and its menu price.
3. Choose an ingredient ID and specify **how much is needed for one serving**.
4. Repeat for each ingredient and leave the ingredient ID blank to finish.
5. Use **4 — View recipes** to inspect the saved recipe and its quantities.

To edit a recipe, choose **3**, answer **No** when asked to create a new recipe, then enter an existing recipe ID. Select an ingredient and either remove it from the recipe or enter a new per-serving quantity. **Editing a recipe's price is not available in the current menu**; the price is set when the recipe is created.

### Create and complete an order

1. Choose **1 — Create customer order**.
2. Select one or more **recipe IDs** and enter a whole-number serving count for each.
3. Leave the recipe ID blank to finish. Enter the **Customer ID** if the customer wants loyalty points (or leave it blank). Use **5 → 9** to list customers and their IDs; **5 → 1** creates a new walk-in customer, and **5 → 2** enrolls an existing Customer user.
4. Confirm **Save as Pending**, then choose whether to **mark the order Completed now**.
   - **Yes:** the system checks the linked customer's loyalty status, offers available discounts, previews earned/redeemed points and asks for final confirmation. Completing checks inventory, deducts required ingredients, updates the order and records loyalty points together.
   - **No:** the order stays Pending; no ingredients or points are deducted yet. The Customer ID is retained.
5. To complete it later, choose **2**, select the order ID, enter `c` and follow the **same loyalty/discount prompts**. For an order with no Customer ID, staff can assign one before finishing.

If a customer has not joined loyalty yet, the completion menu **offers to enroll them** first. If loyalty is suspended, the customer account is disabled, or the order has no customer attached, the program explains what must be activated or linked and can complete the order **without loyalty points** after explicit confirmation. A cancelled or still-Pending order earns no points. A Completed order cannot be completed again, so stock and points cannot be double-counted.

If stock is insufficient or the selected reward is invalid, the completion stops and the order remains Pending. Inventory deduction, order status, loyalty writes (when applicable), and the **net Sale posting** are committed in **one database transaction**; a failure rolls everything back. The original order total remains unchanged, but accounting records its value after any reward discount. No money is charged or refunded by this program; real payment processing would be integrated separately.

If the order requires more of **any** ingredient than you have available, the completion is rejected. **Nothing is deducted and the order remains Pending**; this prevents a partly fulfilled inventory update. An order that has already been completed cannot be completed again, preventing a duplicate deduction.

**Example:** If one Tuna Mayo Onigiri uses 120 g of rice, 1 nori sheet, 55 g of tuna, 20 g of mayonnaise and 1 wrapper, completing an order for **two** uses **240 g of rice, 2 sheets, 110 g of tuna, 40 g of mayonnaise and 2 wrappers**. The menu item’s recipe defines these requirements.

Option **2** also allows you to **cancel** a Pending order using `x`; a cancelled order does not deduct inventory. External orders from other systems that have no recipe lines cannot be completed through this menu.

## 7. Suppliers, purchase orders and deliveries (options 12–15)

### Register suppliers (option 15)

Choose **15 — Manage suppliers** to list existing suppliers. Confirm that you want to add one, then enter its name and contact details. Supplier IDs are displayed when you receive a delivery.

### Create an inventory purchase order (option 12)

1. Choose **12 — Create inventory purchase order**.
2. Review the current low-stock ingredients listed as a reference. You can order ingredients **even if they are not currently low**.
3. Enter the ingredient ID and the positive quantity you want to order. Repeat as necessary.
4. Leave the next ingredient ID blank when finished.
5. Enter optional notes and confirm.

The purchase order is stored as **Confirmed**. **Creating the purchase order does not add stock to inventory**. Stock increases only after a delivery is recorded.

### Receive a delivery (option 14)

1. Choose **14 — Receive supplier delivery**.
2. Enter the Supplier ID (or leave it blank if the supplier is unknown).
3. Indicate whether the delivery belongs to a **confirmed purchase order**.
4. If Yes, enter the purchase order ID and select from its **outstanding** ingredients.
5. Enter how much of each ingredient actually arrived; leave the next ID blank to finish.
6. Enter the supplier's total invoice amount in CAD if it is known; amounts must be positive and have no more than two decimals. Leave it blank if the invoice is not yet available. Enter the invoice number/reference if you supplied an amount (or let the system generate a reference).
7. Confirm the delivery. Inventory, purchase order quantities, and any financial Purchase posting are saved in the same database transaction.

If a delivery is linked to a purchase order, you cannot receive an ingredient that is not on the order or a quantity greater than its remaining balance. The purchase order status changes to **Partially Received** or **Received** as appropriate.

If the delivery is **not** linked to a purchase order, you can still select ingredients and record the stock receipt; it simply will not update a purchase order's received quantities.

**Accounting:** The purchase order itself is only an inventory commitment: it stores quantities, not dollar costs. A delivery records an accounting **Purchase** only when its actual invoice amount is entered. Without that amount, the delivery remains in inventory history, and the program explicitly tells you that no financial entry was posted. Once the invoice is available, you can record it manually using **18 → 3**. If an invoice covers several deliveries, record the amount only once to avoid double-counting it.

Use **13 — View inventory purchase orders** to see each purchase order and its individual `Ordered`, `Received` and `Remaining` quantities.

Use **16 — View transaction history** to review the **40 most recent** inventory movements, newest first. Adding stock records a positive change; deductions record a negative change. Transaction types include Opening Stock, Manual Adjustment, Supplier Delivery and Customer Order.

**Manual stock adjustments (option 9):** Supply a quantity and reason as before. An optional positive CAD value can now be recorded as an **Inventory Adjustment** in the Accounting Ledger at the same time. If no value is entered, only the stock movement is recorded. Accounting adjustments are displayed separately and do not automatically change the sales-minus-expenses balance because the system does not infer an adjustment's debit/credit direction.

## Owner account management (option 20)

After signing in as an **Owner**, enter **20** to display the User Management submenu. It **stays open** until you select **0 — Return to main menu**, so you can work on several users without starting again.

The user list and individual account details show a **Customer ID** column. It displays `—` for Owners, Employees and Customers who have not yet enrolled in loyalty. This is intentionally different from **User ID**: each User is assigned a User ID, and every Customer subtype has a database Customer ID, but the owner user-list column only shows that Customer ID once loyalty is enrolled. To see **all** customers, including unenrolled accounts and their Customer IDs, use **5 → 9**.

| Choice | Owner action | What changes |
|---|---|---|
| 1 | View user details | Shows profile and login metadata without passwords. |
| 2 | Create new user | Creates a shared `User`, associated role subtype and `Profile`; email, phone number and date of birth are optional. |
| 3 | Edit user information | Changes name, username, email, phone or birth date. Blank input keeps a field; a single `-` clears optional fields. |
| 4 | Change user's role | Changes Employee/Customer/Owner, updating subtype data consistently. Restricted by any existing foreign-key references. |
| 5 | Reset password | Requires re-entering the current Owner password, and choosing the new account password twice. |
| 6 | Disable / enable user | Disables sign-in while retaining profiles, orders, transactions, and other historical records. |
| 7 | Delete user | Requires explicit DELETE confirmation and Owner password. Only unreferenced accounts can be permanently deleted. |
| 0 | Return | Leaves account management for the regular menu. |

**Important:** The account-management service checks the Owner role against the *current database* every time; even a direct call by an Employee/Customer is denied. Do not disable your only Owner account. If a user has linked business records, disable their account instead of deleting it. Other team modules should use the same `User.userID` identity rather than creating a second user database.

For existing installations, update the Python files **inside your existing application folder** but retain `btm495.db` and `backups/`. On the next start, the program adds any missing profile, loyalty, payroll and accounting tables or supporting columns without removing existing users, profiles, orders or other saved records. If you unzip to a different folder, a separate empty database will be created there unless you move your existing `btm495.db` into that folder.

---

## My Profile (option 22)

This menu always displays the signed-in user's profile and optionally lets them update it.

1. Log in as an Owner, Employee or Customer using your own or imported demo credentials. Owners can create Customer accounts in option **20**; login registration remains Owner-controlled in this base version.
2. Select **22 — My Profile**. The system retrieves **your own** linked profile and displays the profile ID, name, phone number and birth date, plus a read-only username and role, and a displayed, editable email (if any).
3. Respond **n** to close the profile without changing it. Respond **y** to edit name, email address, phone number, or birth date.
4. For each field, press **Enter** to keep the existing value. Type a new value to change it. Type **`-`** to remove an email address, phone number, or birth date. Dates use **YYYY-MM-DD**.
5. The system validates the proposed values. It requires a nonempty name, checks email and phone number syntax, and prevents impossible or future birth dates. Invalid entries display an error and invite correction. You can decline to save and discard all pending edits.
6. Confirm **Save** to write changes atomically to the existing SQLite database. The updated name and email also appear in the shared `User` table, with name displayed in the menu after successful saving. A save failure rolls back all pending changes.

**Customers** see a limited menu (`5 — My Loyalty`, `6 — Feedback System`, `22 — My Profile`, `23 — Log out`, `0 — Exit`). They do not receive the stock/order administration menu. The application currently trusts the user ID returned by its existing login service; any future web/API integration must identify the user from an authenticated session and must not accept an arbitrary user ID from the client.

**For developers:** `ProfileService(db_path).view_profile(current_user_id)` returns an immutable `Profile` object. `update_profile(current_user_id, {'name': ..., 'email': ..., 'phoneNumber': ..., 'dateOfBirth': ...}, expected_version=profile.version)` validates and commits the user's data. Profile IDs are stable strings. Future modules should reuse the same `User.userID` and `Profile` row. Loyalty points, payroll data and authentication credentials cannot be edited through My Profile.

---

## Loyalty Program (option 5)

Owners and Employees have the following staff submenu. Customers see **5 — My Loyalty** instead, where they may enroll themselves if necessary and review only their own points, available rewards and transaction history.

| Staff option | Action | How to use it |
|---|---|---|
| **1** | Register a walk-in customer | Enter a name, email or phone number (at least one contact method required), optional date of birth, optional username and optional password (8+ characters). A blank username generates `walkin<UserID>`; a blank password generates a **unique random temporary password**, shown once. The created customer can sign in immediately. Give the credentials privately to the customer. |
| **2** | Enroll an existing Customer user | Enter the **User ID**, not Customer ID. A blank ID returns to the loyalty submenu. Already-enrolled Customers keep their existing account and points. |
| **3** | Find by email/phone | Search exact contact information; shows both IDs and whether points exist. |
| **4** | View loyalty details | Enter the **Customer ID** to see balance, available rewards and transaction history. |
| **5** | Record a completed order manually | For an older Completed order not already in the loyalty ledger, enter Customer ID and Order ID, preview any redemption, confirm and record points once. **Not needed for orders completed through main menu options 1/2 with active loyalty.** |
| **6** | List rewards | Shows all rewards and whether they are active. |
| **7** | Configure rewards (Owner) | Create rewards or activate/deactivate existing ones. |
| **8** | Suspend/reactivate loyalty (Owner) | Changes loyalty status without removing historical transactions; suspended accounts cannot earn/redeem. |
| **9** | List all Customer users | Shows **User ID, Customer ID, name, username, login status, loyalty enrollment/status, and balance**, even for Customers who have not joined loyalty. |
| **0** | Return | Back to main menu. |

### Which ID should I enter?

- **User ID** identifies a login account, whether Owner, Employee or Customer. Staff use it with **5 → 2** to enroll an existing Customer user.
- **Customer ID** identifies the Customer record used by `Order.customerID` and the loyalty program. Staff use it for order creation/completion and **5 → 4/5/8**. It is not interchangeable with User ID; they may have different numbers.
- **Loyalty transaction ID** identifies one completed purchase's point activity. Only one loyalty transaction is permitted per order.

### How loyalty is recorded when an order completes

1. Staff link the Customer ID to the order using main menu **1**, or when completing an existing Pending order under main menu **2**.
2. If the Customer does not yet have a loyalty account, the menu offers to enroll them. A disabled Customer login must be re-enabled under **20 → 6**, and a suspended loyalty account must be reactivated under **5 → 8** before loyalty can be applied. Staff may instead explicitly proceed without points.
3. The program checks active rewards the customer can afford **with their existing points**, excluding discounts larger than the order total. Staff can select a Reward ID or leave it blank to save points.
4. The preview shows order value, discount and expected new balance. Staff confirm order completion; the inventory and loyalty transaction are posted together. A receipt-style **loyalty confirmation** displays the points and discount recorded. Completing the same order again cannot earn more points.

Earning uses **10 whole points per $1 CAD** of eligible spending; fractions are rounded down. Points are earned on the value after the selected discount: a $20 order with a $5 reward earns `($20 − $5) × 10 = 150 points`. Rewards are redeemed using **previously earned** points, not the points from the current order. The built-in examples are listed near the top of this README. The stored `Order.totalAmount` does not change; the accounting Sale records $15 in this example. The loyalty quote is **not an actual payment or tax receipt**.

For other modules or a future GUI, `InventoryService.create_customer_order(recipes, staff_user_id, customer_id)` saves a linked Pending order. `LoyaltyService.complete_order_with_loyalty(staff_user_id, customer_id, order_id, reward_id=...)` completes it and posts points **atomically**. Use `preview_purchase()` before presenting a reward. `InventoryService.complete_customer_order()` remains available for inventory-only orders with no loyalty activity. For an already-Completed order that has no loyalty entry, `process_eligible_purchase()` records only the points/redemption without deducting stock again. Avoid calling both recording methods for the same order.

The loyalty domain classes `LoyaltyAccount`, `LoyaltyTransaction`, `Reward` and `Redemption` are in `loyalty_models.py`. SQLite retains the existing integer IDs and foreign keys so other modules continue to work, while loyalty records also have stable `publicUUID` values for future integration. The optional Customer → LoyaltyAccount relationship allows customer profiles to exist without joining. Historical account balances, status and transaction records survive a normal application restart; the schema initializer only performs additive upgrades.

---

## Payroll (option 17 — Owner only)

Payroll uses the same Employee accounts managed through **20 — Manage users**. The Owner creates a pay run for a specific date, enters employees' regular and overtime hours, validates and calculates their pay, approves the payroll, then records it as Paid after the employees have actually been paid. Approved and Paid runs are locked against hour changes. Only active Owner accounts can use the payroll service.

| Payroll option | Action | Details |
|---|---|---|
| **1** | Open payroll | Enter a pay date in `YYYY-MM-DD` format. Only one payroll can exist per pay date; new runs start as **Draft**. |
| **2** | Enter or correct hours | Choose an existing **Draft Payroll ID** (validated immediately), then select Employee IDs and enter regular/overtime hours. Repeat until you leave the Employee ID blank. |
| **3** | Validate, calculate and review | Checks for missing employees, hourly rates and unrealistic/zero hours. Calculates deductions, net pay and total payroll cost when valid. |
| **4** | Approve payroll | Reviews a fully calculated Draft and locks it as **Approved**. |
| **5** | Record payment and expense | For an Approved run **after employees have been paid**, mark it **Paid** and post one expense to the Accounting Ledger. This cannot be undone from the menu. |
| **6** | View pay stubs | Shows per-employee pay stubs for Approved and Paid payrolls. |
| **7** | Set employee hourly rates | Choose an active Employee ID, enter a positive hourly rate, and repeat until the ID is blank. Changing a rate invalidates earlier calculations in Draft payrolls that include that employee. |
| **8** | Remove an employee | Choose a Draft payroll, review its entries, and remove Employee IDs in a loop until blank. Recalculate after removing anyone. |
| **0** | Return | Back to the main menu. |

### First payroll setup

1. Sign in as Owner. If the Employee list is empty, create an Employee through **20 → 2** (or activate a disabled Employee under **20 → 6**).
2. Select **17 → 7**, set each employee's hourly rate and press Enter at a blank Employee ID to return.
3. Select **17 → 1** to open a payroll for a date, then **17 → 2** to enter hours for the employees who worked that period.
4. Select **17 → 3** to validate and calculate. If an employee has no rate, no hours, more than **80 regular hours**, or more than **120 total hours**, the program explains what to correct. Enter hours through option 2, set the rate through option 7, or remove the employee through option 8, then recalculate.
5. Select **17 → 4** to approve. Review/print the text pay stubs under **17 → 6**. Once payments have been made outside this system, record the expense under **17 → 5**.

**Pay rules are simplified examples, not actual payroll deductions or employment-law calculations.** The current model assumes a two-week period, **1.5×** overtime pay and a flat **20% deduction** from gross earnings. Total payroll cost equals the sum of gross earnings (net pay plus deductions). Payroll does **not** send payments, calculate taxes accurately, file remittances, or interface with a bank. The Accounting Ledger records the total expense only; it is not a full general ledger.

Employee IDs are distinct from User IDs. Find Employee IDs in payroll options **2** or **7**; use User IDs for account administration under option **20**. A missing payroll must first be opened with **17 → 1**, while a missing Employee account must be created/enabled in **20**. Historical pay stubs keep calculated amounts if an employee's current hourly rate later changes; the employee-rate column shown in payroll details is always the **current** rate.

---

## Accounting Ledger (option 18 — Owner only)

Choose **18 — Accounting Ledger** to view financial entries from all management modules together. The Owner-only submenu stays open until **0 — Return to main menu**. After any option 1–8, the result stays visible until **Enter** is pressed. Entries show a `Source` (for example, `Order #3`, `Payroll #2`, `Delivery #14`, `Adjustment #18`, or `Manual`).

| Accounting option | Action | Details |
|---|---|---|
| **1** | Dashboard and summary | Totals for sales, purchases, expenses and inventory adjustments, the calculated balance, recent entries, flagged discrepancies and reconciliation history. |
| **2** | View all transactions | List dates, types, descriptions, references, amounts, source links and IDs from across the system. |
| **3** | Add accounting transaction | Enter a type by number or name: **[1] Sale**, **[2] Purchase**, **[3] Expense**, **[4] Inventory Adjustment**. Blank transaction type cancels. Date, description and amount are validated; invoice/reference is optional. |
| **4** | Update a transaction | Select an existing **manual** accounting entry; blank ID returns. Linked automatic entries are read-only here to avoid contradicting payroll, orders or inventory records. |
| **5** | Reconcile | Check duplicate non-empty references (case-insensitive), create flags for new possible duplicates, clear obsolete flags when corrected, and record a run in the reconciliation log. Displays the actual number checked, newly flagged and cleared. |
| **6** | Review/resolve flags | Review discrepancies and mark one or more Resolved; blank discrepancy ID returns. Resolving a flag does not modify the original transaction. |
| **7** | Transaction entry help | Explains fields, accepted types, amount requirements, reconciliation and which entries post automatically. |
| **8** | Review/import historical completed orders | Lists completed orders that lack a source-linked Sale. Choose individual Order IDs to import after reviewing them against existing manual sales; blank ID returns. |
| **0** | Return | Back to the main management menu. |

### Which activities post automatically?

| Event | Accounting entry | When it is created |
|---|---|---|
| Customer order is marked Completed | `Sale` | On successful completion, at the order total. If a loyalty discount is applied, the **same Sale** is adjusted to the net amount. Fully discounted/zero-dollar orders have no positive Sale entry. |
| Payroll is recorded Paid | `Expense` | Once per approved and paid payroll, for the payroll's total cost. |
| Supplier delivery | `Purchase` | Only if the invoice amount is entered in main menu option 14. A quantity-only delivery does not imply a known purchase price. |
| Manual inventory adjustment | `Inventory Adjustment` | Only if a monetary value is entered in main menu option 9. The sign of the quantity change is kept in inventory history; accounting reports the absolute value separately. |
| Manual accounting entry | Selected type | When an Owner explicitly adds it through 18 → 3. |

**No duplicate automatic postings:** each source event has a unique `sourceType` and `sourceID` link. Completing an order, awarding its loyalty points, and later recording a discount cannot create three sales. Payroll retains its existing `accountingTransactionID` reference, and saving a financial entry happens in the same SQLite transaction as its operational event. If the accounting write fails, the related stock/order/payroll change is rolled back too.

The dashboard balance is **sales − purchases − expenses**. Inventory adjustments have their own subtotal because this version does not classify them as gains or losses. Reconciliation checks repeated references **inside this database**; it does not compare bank statements, process payments, verify real invoices, or prepare financial statements.

### Existing data and accounting database compatibility

The first time an Owner opens option 18, previously completed shop orders with recipe lines and a recorded total are added to the ledger if they have no source-linked Sale yet **and the ledger has no pre-existing manual Sale entries**. When a historical loyalty transaction exists, its net `finalAmount` is used. If manual sales already exist, automatic historical import is skipped to avoid potential double-counting: the Owner receives an explanation and can use **18 → 8** to review and import individual orders after comparing them with existing entries. The sync is repeat-safe. Existing payroll expenses are linked to their payroll runs without changing their transaction IDs or amounts. Financial entries are **not populated with fictional sample transactions simply because the ledger is empty**. The optional shop dataset under option 21 contains its own sample completed orders, which are recorded as sample sales when you explicitly load that dataset.

The original payroll module and the standalone accounting addition used different column names in the same SQLite tables. This release supports both without replacing either transaction table:

| Field | Older merged/payroll database | Accounting-format database |
|---|---|---|
| Date | `date` | `transactionDate` |
| Type | `type` | `transactionType` |
| Ledger name | Only `ledgerID` was stored | Optional `ledgerName` also exists |
| Creation/update timestamps | Not present in legacy rows | `createdAt`, `updatedAt` |

The application checks the table layout and reads or saves to the matching columns. It returns consistent `transactionDate` and `transactionType` names to the accounting screens. New `sourceType`/`sourceID` fields, discrepancy tables, reconciliation history and indexes are added non-destructively. Older payroll tables require positive accounting amounts; newer accounting tables may allow zero-valued manual records. Automatic zero-dollar events never create financial postings in either format.

Keep a separate database backup before upgrading. If you have manually entered sales for historical orders, use the per-order review under **18 → 8** before importing. Unrelated manual entries cannot always be matched automatically to an Order ID, so the program does not assume they represent different sales. Only **source-linked entries** are excluded from subsequent automatic syncs.

## Trend Predicting Dashboard (option 19)

Owners and Employees can open **19 — Trend Predicting Dashboard**. It uses existing shop data and **does not add database tables, edit transactions, adjust stock or create purchasing orders**. Select **0** or leave a menu selection blank to return. Forecast results remain on screen until you press **Enter**.

With Matplotlib installed, the dashboard also opens a **pop-up line graph** when you confirm a Sales or Financial trend analysis, or select an ingredient that has enough consumption history. The graph displays the dated historical measurements and a dashed line leading to the next-day estimate, with a legend and labeled axes. **Close the graph window to return to the terminal**, then press Enter to return to the dashboard. If Matplotlib is missing or a graphical desktop is unavailable, a helpful message appears and the printed calculations remain available. See [Requirements](#1-requirements) for installation instructions.

| Dashboard choice | Historical source | What it shows |
|---|---|---|
| **1 — Sales** | `Order` records with status `Completed`, grouped by the date of the order | Number of completed orders on each recorded date; direction of the recent trend and an estimated count for the day after the latest recorded date. Pending and cancelled orders are excluded. |
| **2 — Inventory** | Negative `InventoryTransaction` quantities labeled `Customer Order`, grouped by date and ingredient | Select an ingredient by its displayed list number. Review consumption, current stock, reorder level, 7-day estimated use, estimated coverage and a replenishment suggestion. Deliveries and manual adjustments are **not** treated as customer consumption. |
| **3 — Financial** | Completed priced `Order` records, using `LoyaltyTransaction.finalAmount` when a discount was recorded | Daily net completed-order revenue in CAD (not profit), with trend and estimate. An order's discount is counted once; separately entered ledger transactions and payroll/purchasing expenses are not included in this **sales-revenue forecast**. For all financial entries, use **18 — Accounting Ledger**. |

**How estimates work:** The dashboard needs at least **three distinct dates with recorded activity** for the chosen series. It compares the latest value to the average of the two preceding recorded dates to report **Increasing**, **Decreasing** or **Stable**. The forecast is the average of the latest three recorded dates, shown as an estimate for the day following the latest recorded date. Dates without a record are not assumed to have zero activity, and the estimate may refer to a past date if the shop has not recorded recent activity. Inventory coverage assumes consumption at that estimated level every calendar day, even though the recorded-day average may exclude inactive dates. Treat these as illustrative planning estimates, not validated demand forecasts or automatic purchase recommendations.

If there are not enough records, the menu says what is missing. Create recipes and complete customer orders (**3, 1 or 2**) to build sales/consumption history; at least three **different dates** are required to generate a forecast. Alternatively, use **21 → 1 → 1** to prepare the empty starter shop and **21 → 1 → 2** to load 12 historical days of orders and ingredient movements in one step. If an ingredient has no consumption records, choose one that appears in recipes used by completed orders. Viewing trends makes no changes to the SQLite file. The accounting and forecasting views read the same shop data but answer different questions: **18** is a transaction ledger, while **19** summarizes order-derived activity over time.

---

## Feedback System (option 6)

**Customer — submit and view feedback:** Sign in with an active Customer
account and choose **6 → 1**. Enter a required comment (up to 2,000
characters) and optionally a whole-number rating from **1** to **5**. Leave
the rating blank to submit written feedback without a rating. Blank comments,
ratings outside 1–5, and invalid text are rejected with an explanation;
unsaved feedback is not kept. Enter **`/back`** at the comment prompt to cancel
without submitting. On success the menu displays a saved Feedback ID.
Choose **6 → 2** to view your own submissions and their Submitted/Reviewed
statuses. If you have never submitted feedback, the screen explains how to
create your first entry. Enrollment in loyalty and a completed order are
**not required** to submit feedback.

**Employee or Owner — review feedback:** Sign in with an active Employee or
Owner account. Choose **6 → 1** to view all customer submissions. Choose
**6 → 2** to see all feedback **waiting for review**, including its ID, date,
customer name and username, optional rating and full comment. The Customer ID
remains stored for reliable linking, even if the customer is not enrolled in
loyalty. Enter one of the Feedback IDs, then confirm to
mark it **Reviewed**. At the review-ID prompt, enter **`0` or just press Enter**
to return to the feedback menu; invalid IDs also show these exit instructions.
The feedback menu itself accepts **`0` or Enter** to return to the shop's main
menu. If no submissions have been received, or none remain to be reviewed, the
screen explicitly says so and does not ask for an ID. Press Enter after the
result to return to the feedback menu. If you select an already-
reviewed or nonexistent ID while other records are pending, the system tells
you to select a Submitted ID. A declined confirmation does not change status.

**Account setup and access:** A shop Owner creates Customer and Employee logins
under **20 → 2 — Create new user**. A new account can use the Feedback System
immediately after creation; there is no separate enrollment or activation
step for feedback. The Owner can optionally load sample accounts via **21 → 7**.
Customers only see their own feedback, while Employees/Owners can read and
review feedback from all customers. If a customer account is missing its
underlying Customer record, the user is directed to the Owner's account
management screen rather than receiving a generic database error. Disabled
accounts must be reactivated by an Owner before accessing feedback.
Feedback history is preserved when an account is disabled; changing the role
or deleting the Customer identity is blocked while it has feedback history.

**Shared storage:** All feedback is stored in the existing persistent SQLite
`btm495.db` in a new `Feedback` table. Each feedback record belongs to an
existing `Customer.customerID`, has an integer `feedbackID`, a stable
`publicUUID` for future merged-system integration, its text, an optional
integer rating, an ISO-8601 `submissionDate`, and a `Submitted`/`Reviewed`
status. A customer's login ID and Customer ID are different identifiers:
`FeedbackService` resolves the latter from the signed-in user and verifies
permissions on every operation. Account management continues to show its
loyalty-related Customer ID only for loyalty-enrolled accounts; this does not
prevent other customers from submitting feedback. Existing user, profile,
inventory, ordering, accounting, loyalty, payroll and trend tables remain intact. Input problems are explained, and a failed database write is
rolled back so the customer can retry. A feedback status update is likewise
transactional.

**For another module:** Import `FeedbackService` from `feedback_service.py` and
pass the current authenticated `userID` into `submit_feedback(user_id, text,
rating=None)`, `view_submitted_feedback(user_id)`,
`view_feedback(staff_user_id)` or `review_feedback(staff_user_id,
feedback_id)`. New Python modules should use the snake_case methods; camelCase
compatibility aliases such as `submitFeedback`, `storeFeedback`,
`viewSubmittedFeedback`, `viewFeedback`,
`getFeedback`, `reviewFeedback`, and `updateStatus` are available. See
`test_feedback.py` for examples.

**Backup/reset:** Normal restarts and routine database backups retain feedback.
Owner option 21 **Reset** deliberately clears feedback alongside other
business data, even when it preserves user accounts; a pre-reset backup is
created so previous data can be recovered with the restore option.

## 8. Sample data, backups, resets and restore

### Optional fictional customer/staff logins (21 → 7)

These eight accounts are **never imported unless an Owner explicitly selects 21 → 7**, confirms and re-enters the Owner password. Their original sample credentials are:

| Username | Name | Role | Sample password |
|---|---|---|---|
| `akira.owner` | Akira Tanaka | Owner | `OwnerDemo!2026` |
| `emma.staff` | Emma Laurent | Employee | `StaffDemo!2026` |
| `jordan.staff` | Jordan Kim | Employee | `StaffDemo!2026` |
| `maya.customer` | Maya Chen | Customer | `CustomerDemo!2026` |
| `noah.customer` | Noah Tremblay | Customer | `CustomerDemo!2026` |
| `olivia.customer` | Olivia Martin | Customer | `CustomerDemo!2026` |
| `leo.customer` | Leo Nguyen | Customer | `CustomerDemo!2026` |
| `sara.customer` | Sara Patel | Customer | `CustomerDemo!2026` |

Each gets a Profile with fictional contact information and birth date. Repeating the import skips existing sample accounts and **does not overwrite any profile, changed username, password, account status or loyalty enrollment**. Name/username conflicts with unrelated accounts stop the import. Use **20** to view accounts and **23** to switch login. To enroll sample Customers, use **5 → 2** or let them sign in and join through **5 — My Loyalty**. These example passwords should not be used for real customers or production deployment.

**21 is available to Owners only.** It opens its own sub-menu:

| Sub-option | Action | What is saved or replaced? |
|---|---|---|
| **1 — Load sample data** | Opens a submenu with separate starter shop, trend-history, accounting and payroll samples. | These imports add only their selected records; they do not reset the database. Owner password verification and confirmation are required. See the next table. |
| **2 — Create backup** | Copies the current database to `backups/`. | **Does not change** the active database. |
| **3 — Backup + reset + sample data** | Creates a backup, clears the live database and loads the supplied sample dataset. | **Preserves Customer/Employee/Owner login accounts, profiles and employee hourly rates**; clears loyalty, payroll and business transactions. Use when a consistent starting dataset is needed. |
| **4 — Backup + reset empty** | Creates a backup and prepares a blank set of business tables. | **Preserves login accounts, profiles and employee hourly rates**; clears loyalty, payroll and other business records. |
| **5 — Restore a previous backup** | Lists backups, allows you to choose one and backs up the current state before restoring. | Replaces the **entire** live database with the selected backup, including accounts and unrelated tables. |
| **6 — Backup + factory reset** | Backs up the current database and clears everything. | Also **removes all accounts**; the next startup asks you to create a new Owner. |
| **0 — Back** | Returns to the main menu. | No changes. |

### Included sample data

**Option 21 → 1** opens a second menu, so you can load the datasets you actually need. Each additional dataset (choices 2–4) can be imported **once per database**; rerunning one tells you it is already present and adds nothing. Records from other modules remain intact. Use the backup/reset menu only if you explicitly want a fresh database.

| Sample-data choice | Content and prerequisites | Where to review it |
|---|---|---|
| **1 — Starter shop** | The existing empty-inventory-only starter dataset. Requires no inventory/recipe/transaction records. Adds 14 ingredients, 7 recipes, suppliers, 4 completed orders, 1 pending order and a partial delivery. | **2**, **4**, **7**, **11**, **13**, **15**, **16**, **18** |
| **2 — Historical orders / trends** | Requires the starter shop recipes and their ingredients (choice 1). Adds **41 completed priced orders over 12 separate past dates**, their dated ingredient deductions and linked accounting Sales. If there is too little stock, adds a fully received purchase order, inventory delivery and one valued accounting Purchase first. | **2**, **16**, **18 → 2**, **19 → 1/2/3** |
| **3 — Accounting activity** | Can run independently of the starter shop. Adds **10 dated manual transactions** across Sales, Purchases, Expenses and Inventory Adjustments. Two example Expenses intentionally share a reference so you can test reconciliation. | **18 → 1/2** for summary/history; **18 → 5/6** for duplicate-reference checks and resolution |
| **4 — Paid payroll example** | Requires at least one active Employee with a **positive hourly rate** (create/enable under **20**; set pay under **17 → 7**). Creates one fictional payroll for up to three rated Employees, calculates hours/deductions, marks it Paid and adds **one source-linked accounting Expense**. No payment is actually sent. | **17 → 1/6**, **18 → 1/2** |
| **0 / blank — Back** | Returns to the Demo / Database Management menu without making changes. | — |

**Recommended order for testing everything:** **21 → 1 → 1**, then **21 → 1 → 2**, then **21 → 1 → 3**. If you also want payroll examples, first create or import Employees using **20** or **21 → 7**, set their hourly rates using **17 → 7**, then run **21 → 1 → 4**. You can run accounting examples before the starter shop; they are independent. All loaders run in an SQLite transaction: a failed import does not leave partial entries. The additional datasets are labeled as sample information, not genuine transactions or payments. The intentionally repeated accounting reference can be corrected through **18 → 4**, then reconciliation rerun to clear the flags. A small `DemoDataSet` table tracks which optional import has already succeeded; it is added only when you use an additional dataset and does not rename or replace existing accounting tables.

The **starter shop dataset** (choice 1) includes:

- **14 ingredients**, with quantities and individually defined reorder levels.
- **7 recipes:** Tuna Mayo, Salmon, Umeboshi, Teriyaki Tofu, Cucumber Sesame, Spicy Tuna and Plain Onigiri.
- **3 fictional suppliers** and contact details.
- **5 customer orders:** 4 Completed (with ingredients already deducted) and 1 Pending.
- **1 partially received inventory purchase order**, with its remaining quantities.
- Inventory transactions and **3 initial low-stock alerts**.

Only the starter shop dataset is included automatically when you choose **21 → 3 — Backup + reset + sample data**. That reset does **not** automatically add the historical orders, additional accounting entries or paid payroll. Choose those individually afterward. Reset and restore actions replace business data only after their separate confirmations and automatic safety backups.

All sample quantities, supplier contacts and menu prices are fictional.

**To load sample data:** choose **21 → 1** when the inventory is empty. To clear existing business data and reload the same sample dataset, use **21 → 3**. This resets the entire shared database, so back up or coordinate with any other applications using it first.

### Where backups go

Backups are stored in the **`backups/` folder beside `btm495.db`**, with timestamped names similar to:

```text
OnigiriInventory/
    inventory_cli.py
    inventory_service.py
    inventory_db.py
    demo_tools.py
    btm495.db                    <-- active database
    backups/
        btm495_backup_20261018_153000_123456_before_reset_abc12345.db
        btm495_backup_20261018_154500_123456_before_restore_def67890.db
```

The timestamped filenames are examples. Each backup is a complete SQLite database that can be used to return to a previous state.

### Reset procedure — read carefully

For reset options **3, 4 or 6**, the application:

1. Displays a warning that **all business data in the entire shared SQLite database** will be replaced.
2. Requires you to type **`RESET`** exactly.
3. Requires you to enter the current **Owner password** again.
4. Creates a dated **backup of the full active database**.
5. Builds and checks the replacement database, and swaps it into place.
6. Returns you to the login screen. Options 3 and 4 use your existing account; option 6 requires new first-time Owner setup.

**Reset affects the entire management system.** Loyalty account balances, rewards, transaction history, payroll runs, pay stubs and accounting expenses are **cleared** by reset options 3, 4 and 6 (along with inventory/orders). The tables are recreated as empty, and the original data remains in the dated backup. Options 3 and 4 preserve all account credentials, profiles, employee hourly rates and sample-user import history; option 6 removes those too. Do not reset a shared database without coordinating with other users or applications relying on it.

**Close other programs using `btm495.db` before resetting or restoring**, including database browser applications, or other Python applications. Keep an additional offline copy of any important project data.

### Restore procedure

1. Log in as Owner and select **21 → 5**.
2. Choose the numbered backup you want to restore.
3. Type **`RESTORE`** exactly and re-enter the current Owner password.
4. The program first backs up the **current** database again, then restores the selected backup.
5. Log in using the **accounts and passwords that existed when the restored backup was created**.

Restoring a backup also restores its *old* inventory quantities, customer orders, supplier orders, alerts and other database tables. It replaces changes made after that backup was captured (which remain available in the automatic before-restore backup).

## 9. Existing databases and integration

The application can share key tables with an existing SQLite-based system instead of requiring a separate database.

| Inventory concept | SQLite table(s) | Purpose |
|---|---|---|
| User / Owner / Employee / Customer | `User`, `Owner`, `Employee`, `Customer` | Shared account records and roles |
| Profile | `Profile` | One-to-one user profile with name, phone, birth date, and revision number |
| Ingredient | `InventoryItem` | Ingredient names, units, quantities, reorder thresholds |
| InventoryTransaction | `InventoryTransaction`, `InventoryAdjustment` | Detailed inventory movement history |
| Supplier | `Supplier` | Contact and receipt linkage |
| Recipe | `Recipe`, `RecipeIngredient` | Menu items, prices, ingredients and quantities per serving |
| CustomOrder | `Order`, `OrderRecipe` | Customer orders and their recipe/serving lines |
| LowStockAlert | `LowStockAlert` | Open, Reviewed and Closed alerts |
| InventoryOrder / InventoryOrderItem | `InventoryOrder`, `InventoryOrderLine` | Purchasing and received/outstanding quantities |
| Loyalty accounts and points | `LoyaltyAccount`, `Reward`, `LoyaltyTransaction`, `Redemption` | Customer enrollment, rewards and points history |
| Payroll | `Payroll`, `PayrollEntry` | Pay periods, employee hours and calculated payroll |
| Accounting and financial audit | `AccountingLedger`, `AccountingTransaction`, `AccountingDiscrepancy`, `AccountingReconciliationLog` | Shared Sales/Purchases/Expenses/Adjustments, event links, duplicate-reference checks and history |
| Optional sample-data tracking | `DemoDataSet` | Records successful optional dataset imports once each; created only when needed |

The `RecipeIngredient` table stores the amount of an ingredient needed for one serving; `OrderRecipe` stores the number of servings on a customer order. These are supporting tables needed to implement recipe-based deductions reliably.

### Using an existing `btm495.db`

1. **Make a separate copy of the database before connecting it.**
2. Put the application's `.py` files alongside that `btm495.db`, or carefully arrange for `inventory_db.py` to point to your intended database location.
3. Run `inventory_cli.py` normally. It will use the existing file and add missing inventory, profile, loyalty, payroll, accounting and feedback-supporting tables/columns as needed, without resetting it on startup. Existing User records are given linked profiles if missing.
4. Test the connection using a **copy** of your real database first, especially if its existing schema differs from the supplied tables.

**Caution:** The database path is based on the folder containing `inventory_db.py`, **not** whatever folder your terminal happens to be in. If you accidentally run a second copy of the application from another extracted folder, it may create a second `btm495.db` there. Always run the correct copy.

**Loyalty is integrated** into order options **1/2** and menu option **5**; **payroll** is under **17**, **accounting** under **18**, **trend prediction** under **19**, and **customer feedback** under **6**. The shared accounting service also posts source-linked entries for qualifying financial events in the other modules. The trend dashboard reads existing orders, loyalty records and inventory movements without modifying them. This remains a simplified financial ledger with basic trend estimates, not full double-entry accounting or advanced analytics. Updating an external order's status with raw SQL does **not** automatically deduct ingredients, grant points or post a sale. An external ordering system should call `LoyaltyService.complete_order_with_loyalty()` for a linked, enrolled customer, or `InventoryService.complete_customer_order()` for an inventory-only order, rather than directly updating database status.

## 10. Troubleshooting

| Problem | What to check |
|---|---|
| `py` or `python` command not found | Confirm Python 3.10+ is installed, then try `py`, `python` or `python3` as appropriate. |
| `No module named inventory_service` or `demo_tools` | Extract **all** files to one folder; don't run only `inventory_cli.py` in isolation. |
| Application creates a new, empty database | Confirm you launched the copy of the application that sits beside the intended `btm495.db`. |
| Cannot log in after closing/restarting | Use the same username and password. If you switched to a different folder/database or restored a backup, its accounts may differ. |
| Walk-in customer cannot log in | Walk-ins created in 5 → 1 now receive a username and either a staff-chosen or randomly generated password. Give them those credentials; Owners may reset forgotten passwords using 20 → 5. Walk-ins created in older versions without credentials require an Owner password reset and username setup. |
| Password appears invisible | This is expected: the program deliberately hides password input. |
| Feedback menu has no submissions | A Customer must sign in and submit a comment under **6 → 1**. If no Customer login exists, an Owner creates one under **20 → 2** (or optionally imports sample logins under **21 → 7**). Feedback does not require loyalty enrollment. |
| Feedback review asks for an ID | **6 → 2** lists pending feedback IDs. Enter a listed ID, or press **Enter** / type **0** to go back. If none are pending, the screen returns without asking for an ID. |
| Feedback is not available for a customer | Check that the User is an **active Customer** with a linked Customer record. An Owner can inspect accounts under **20**. Customers cannot use staff review functions. |
| Customer role cannot be changed after submitting feedback | Existing feedback must remain linked to its customer. **Disable the account** under **20 → 6** to retain its history instead of changing the role or deleting the account. |
| Sample-data loading says existing records found | This prevents duplicates. Use **21 → 3** to reset and reload sample data, after reviewing the shared-database warning. |
| Ingredient shows `LOW` when quantity is not zero | `LOW` is based on **quantity below reorder level**, not quantity reaching zero. Change its threshold using main menu option **10**. |
| Cannot complete a customer order | Check that the order is Pending, each recipe has ingredients, and there is enough stock for the **entire** order. |
| Customer doesn't earn loyalty points | Check that the order has the correct **Customer ID**, the Customer is enrolled and both the User and LoyaltyAccount are active. Option 5 → 9 shows status; option 5 → 2 enrolls, Owner 20 → 6 enables logins, and Owner 5 → 8 reactivates loyalty. Orders completed without loyalty can be recorded once using 5 → 5. |
| Payroll says no employees or hourly rates found | Create/enable an Employee using **20**, then assign a rate under **17 → 7**. Employees must be active and have a positive hourly rate. |
| Payroll ID not found | Open a payroll using **17 → 1** and select the ID listed at the top of the payroll submenu. Blank ID returns without changes. |
| Payroll cannot be calculated or approved | Use **17 → 2** to enter nonzero, valid hours, **17 → 7** for missing rates, and **17 → 8** to remove employees who did not work. Then run **17 → 3** before approval with **17 → 4**. |
| Payroll already Approved or Paid | Only **Draft** payrolls can be changed. Approved payrolls can have pay stubs viewed; recording payment changes Approved to Paid. |
| Purchase order does not increase stock | This is expected. Use main menu option **14** to receive the ordered ingredients. |
| Received stock is not shown as an accounting Purchase | Main menu option **14** only creates a financial Purchase when an invoice amount is entered. If the invoice was unavailable, record it once later using **18 → 3**. |
| Manual adjustment is missing from accounting | Main menu option **9** requires a monetary adjustment value for an accounting entry; quantity-only stock updates stay in inventory history. |
| A completed order is absent from accounting | Check whether it was a zero-dollar order; otherwise open **18** to sync existing completed orders with recipe lines. If manual Sales already exist, use **18 → 8** to review and import individually. Imported orders without recipe lines are not auto-posted. |
| `AccountingLedger` column error on an older database | Use this version's compatible initializer and accounting service; retain a backup. It supports both `date`/`type` and `transactionDate`/`transactionType` without replacing the accounting transaction table. |
| Accounting says no transactions/discrepancies exist | Complete a priced order, record paid payroll, or enter a delivery invoice/valued adjustment; **18 → 5** only checks duplicate references in transactions that exist. |
| Need more accounting records to test | Use **21 → 1 → 3** to load 10 additional sample entries, including a repeated reference for reconciliation. **21 → 1 → 2** also posts sales from historical orders and an invoice if stock needs replenishment. |
| Need at least three dates for trend forecasting | Use the starter shop dataset followed by **21 → 1 → 2**. Its dated orders and consumption movements allow Sales, Inventory and Financial forecasts in option 19. |
| Sample payroll says no eligible employees | Create/enable an Employee through **20**, then set a positive hourly rate under **17 → 7**. Reopen **21 → 1 → 4** afterward. |
| Sample dataset says it was already loaded | Each additional package can be added once. Inspect its existing records under the relevant menus, or make a backup and explicitly reset the database before reloading. |
| Trend dashboard says insufficient history | Complete orders on at least **three distinct dates**. Several orders on the same date count as one daily observation; demo data may not span three dates. |
| Trend graph does not pop up | Install Matplotlib in the same Python environment using **`py -m pip install matplotlib`** on Windows (or **`python3 -m pip install matplotlib`** on macOS/Linux). Launch from a graphical desktop session; a non-interactive backend such as Agg cannot open a pop-up window. The numerical forecast remains available either way. |
| An ingredient has no inventory trend | Select an ingredient that a completed customer order actually consumed. Opening stock, deliveries, spoiled-stock adjustments and Pending orders do not count. |
| Revenue trend differs from the accounting dashboard | **19 → 3** reports net completed-order revenue only; **18** includes manual Sales, supplier Purchases, paid payroll Expenses and other financial entries. The forecast uses order dates, not an accounting bank-clearing date. |
| Cannot receive a purchase order line | Verify the purchase order is open, the ingredient belongs to it and the received amount does not exceed what remains outstanding. |
| Reset or restore reports that the database is in use | Close other Python programs, database browsers and other applications using the SQLite file, then try again. |
| Database save error | Recheck file/folder permissions and disk space. A failed inventory transaction is rolled back rather than half-saved. |

## 11. Optional automated tests

From the project folder, run:

```bat
py -m unittest discover -v
```

On macOS or Linux, replace `py` with `python3`. The tests exercise the grouped main-menu routing and Customer access rules, inventory, profiles, user management, loyalty, payroll, accounting, trend predictions, sample-data import options, feedback submission/review (including returning from a review prompt with 0 or Enter), and backups, including Pending-order completion, discounted sale posting, supplier invoice amounts, valued stock changes, both accounting database formats, forecast calculations, rollback and duplicate prevention. **They create temporary test databases, not your live `btm495.db`.**

## 12. Updating from an older version

If you're updating from an earlier version and **already have saved data**:

1. Close the running application.
2. Back up your existing `btm495.db` to another folder first.
3. Replace the application `.py` files and `README.md` with the updated files, or just replace `README.md` if you're only updating this guide.
4. **Do not overwrite or delete `btm495.db` or the `backups/` folder.**
5. Launch the application again and log in as normal.

The repository or source ZIP does not include an active database. Replacing the README or Python files does not reset an existing `btm495.db`.

---

**Current scope:** This is a local, single-location command-line management application. It supports inventory, ordering, users, profiles, loyalty, simplified payroll, source-linked accounting, basic historical trend estimates and customer feedback. It does not process actual customer or employee payments, connect to bank feeds, calculate statutory payroll deductions, operate as a production POS, support multiple locations, or provide full double-entry accounting or statistically validated demand forecasting.
