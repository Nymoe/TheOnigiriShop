# Onigiri Shop — Inventory Management System

This Python application provides a menu-driven system for managing inventory, orders, account administration, and Use Case #5 (Profile Management) at an Onigiri shop. It supports ingredients, recipes, customer orders, automatic stock deductions, low-stock alerts, purchase orders, supplier deliveries, and inventory transaction history.

**The database is persistent.** Data is stored in a local SQLite file named `btm495.db`. The application creates that file **only if it does not already exist**. On subsequent launches, it reads and updates the same file; it does not wipe the database on startup. You do **not** need to run the original `database.py` or `main.py` to use this application.

> **Important:** The reset and restore options *do* replace the active database, but only when an Owner selects and confirms those actions. Every reset creates a backup first. If other applications or modules share this SQLite file, read [Section 8](#8-sample-data-backups-resets-and-restore) before performing a reset.

---

## 1. Requirements

- **Python 3.10 or later**, installed on your computer.
- Windows, macOS or Linux. The supplied `START_HERE.bat` launcher works **on Windows only**; other systems can run the Python command below.
- A terminal or Command Prompt (Windows Terminal, Command Prompt, PowerShell, or the VS Code terminal).
- Permission to create files in the application folder.

All required libraries, including `sqlite3`, are included with Python. **No `pip install` or internet connection is required to run the application.**

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
| `profile_service.py` | Use Case #5: Profile model, validation, viewing and atomic updates | No |
| `user_management_service.py` | Owner-only management of shared User accounts, roles, credentials and activation | No |
| `inventory_db.py` | SQLite database connection, tables and compatible schema additions | No |
| `demo_tools.py` | Sample Onigiri data; backup, reset and restore actions | No |
| `START_HERE.bat` | Windows double-click launcher | No |
| `README.md` | This setup and menu guide | Read this |
| `test_inventory.py` | Automated inventory feature tests | Optional |
| `test_demo_tools.py` | Automated sample data, backup and reset tests | Optional |
| `test_profile.py` | Use Case #5 role, validation, persistence, cancellation and rollback tests | Optional |
| `test_user_management.py` | Tests for Owner-only management, safe deletion, password resets and role changes | Optional |
| `btm495.db` | **Your saved database, created automatically on first run** | **Keep it** |
| `backups/` | Dated database backups, created when needed | **Keep it** |

The `.db` file and the `backups/` folder are not bundled with the downloadable code. They are generated on your own computer when you use the application.

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

Enter `exit` at the username prompt to close the application without signing in. From the main menu, choose **17 — Log out** to return to the login screen, or **0 — Exit** to close the application completely.

### Add Employees, Customers or another Owner

1. Sign in as an Owner.
2. Select **15 — Manage users**.
3. Review existing users, then choose **2 — Create new user**.
4. Select `e` for **Employee**, `o` for **Owner**, or `c` for **Customer**.
5. Enter the person's name and unique username, optional email address, phone number and date of birth (press Enter to skip any of these), and password (twice). If provided, the date of birth must use **YYYY-MM-DD**.
6. The new user can now sign in after you log out.

The Owner's **3 — Edit user information** option supports the same profile information: name, username, email, phone number and date of birth. Role changes and password resets are handled separately. Customers can view these details under **18 — My Profile**, where they can update their own name, phone number and date of birth; their username, role and email remain read-only.

Owners and Employees can use the original inventory and ordering menus. Customers can sign in and view/update **their own profile only**; inventory administration is unavailable to Customers. Only an **Owner** can create accounts or open **16 — Demo / backup / reset**. Be careful when adding another Owner: that person can also reset and restore the database.

> Owners can now reset an account password or disable and reactivate logins without destroying the account history. When a disabled user enters their correct password, the login screen tells them their account is disabled and to contact an Owner. Account removal is only possible when the user has no related business records.

## 4. Main menu reference

After a successful login, the menu stays open in a loop. Type an option number and press **Enter**. After completing an action, press Enter to return to the main menu. An invalid menu number displays a message and lets you try again.

| Option | Menu name | What it does |
|---|---|---|
| **1** | View inventory | Shows ingredient IDs, names, quantities, measurement units, reorder levels, and OK/LOW status. |
| **2** | Add ingredient | Adds a new ingredient with a starting quantity, unit and reorder level. |
| **3** | Set reorder level | Changes the reorder threshold **for an individual ingredient** and updates its alerts. |
| **4** | Manually adjust inventory | Adds or removes a specified amount and records the adjustment. |
| **5** | Receive supplier delivery | Receives ingredients, optionally linked to a supplier and existing inventory purchase order. |
| **6** | Create/edit recipe | Creates a menu recipe and defines or changes the ingredients required per serving. |
| **7** | View recipes | Lists recipes and lets you inspect a recipe's ingredients. |
| **8** | Create customer order | Selects recipes and servings, saves a Pending order, and optionally completes it immediately. |
| **9** | View/complete customer orders | Reviews orders, completes a Pending order with stock deduction, or cancels one. |
| **10** | Review low-stock alerts | Shows active alerts and allows them to be marked Reviewed or Closed. |
| **11** | Create inventory purchase order | Creates a confirmed order for ingredients that need replenishment. |
| **12** | View inventory purchase orders | Shows order status and quantities ordered, received and still outstanding. |
| **13** | View transaction history | Lists the most recent inventory transactions, including manual changes and order deductions. |
| **14** | Manage suppliers | Lists suppliers and allows you to add one with contact information. |
| **15** | Manage users (**Owner only**) | View, create, edit, change role, reset password, disable/reactivate and (where safe) delete user accounts. |
| **16** | Demo / backup / reset (**Owner only**) | Loads sample data, creates backups, resets the database or restores a backup. |
| **17** | Log out | Returns to the username/password login screen. |
| **18** | My Profile | Opens Use Case #5 for the signed-in Customer, Employee or Owner: view, edit or cancel. |
| **0** | Exit | Closes the program without deleting saved data. |

### Useful input conventions

- **IDs** are the positive whole numbers shown in list screens. Use the displayed ID, not an ingredient's position in the list.
- For inventory quantities, decimals are allowed (for example, `0.5`). When creating customer orders, servings must be **whole numbers**.
- Units are selected when an ingredient is created and used consistently in its recipes. For example, if Rice is measured in `g`, entering `120` in a recipe means **120 g per serving**, not 120 kg.
- Enter **positive quantities** when adding, removing or receiving stock. For a new ingredient's *starting quantity* and for a *reorder level*, zero is permitted.
- When entering multiple ingredient or recipe lines, **leave the next ID blank and press Enter to finish**. Confirm the operation when prompted. Pressing Enter by itself is **not** a universal cancel command; it cancels or finishes only when the prompt explicitly says so.
- Confirmations normally accept `y` for Yes or `n` for No. The default is shown in square brackets where applicable.
- If an operation fails validation or the database save fails, the application displays an error rather than partially saving the transaction.

## 5. Inventory and low-stock walkthrough (options 1–4 and 10)

### View and add an ingredient

**Option 1** displays the current inventory. Each ingredient shows its `ID`, quantity on hand, unit, reorder level and `OK`/`LOW` status.

To add an ingredient, choose **2** and provide its name, measurement unit, starting quantity and reorder level, then confirm. Duplicate ingredient names are rejected. An ingredient with starting stock below its reorder level immediately qualifies for a low-stock alert.

### How the LOW condition works

An ingredient is **LOW when its current quantity is below its reorder level**:

```text
LOW: current quantity < reorder level
OK:  current quantity >= reorder level
```

For example, if Sushi Rice has **1,130 g** available and a reorder level of **1,200 g**, its status is **LOW**. If its quantity reaches exactly 1,200 g, its status becomes **OK**.

**Each ingredient has its own reorder level.** To edit one:

1. Choose **3 — Set reorder level**.
2. Find the ingredient in the displayed inventory list.
3. Enter its ingredient ID.
4. Enter the new threshold (for example, `1500`).
5. Review the updated list. The new level is immediately saved, and alerts are synchronized.

Setting the reorder level to **0** effectively disables LOW alerts for that ingredient because stock cannot become negative.

### Add or remove inventory manually

1. Select **4 — Manually adjust inventory**.
2. Choose the ingredient's ID.
3. Enter `a` to **add** stock or `r` to **remove** it.
4. Enter a positive adjustment quantity and, optionally, a reason.
5. Confirm. The new quantity is saved, and a transaction is recorded.

The program **does not allow stock to fall below zero**. If you try to remove more than what is available, the change is rejected and stock is left unchanged.

### Review low-stock alerts

Choose **10 — Review low-stock alerts** to see active alerts. A change that moves an ingredient below its threshold generates an alert if it has no active one. You can:

- Enter `r` to mark the selected alert **Reviewed** (it stays on the active list).
- Enter `c` to mark it **Closed** (it leaves the active list).
- Leave the alert ID blank to return without changing it.

When inventory is replenished to **at least** the reorder level, the application automatically closes active alerts for that ingredient. If you manually close an alert while stock is still low, another alert can be created after a later stock change.

## 6. Recipes and customer orders (options 6–9)

### Create a recipe (option 6)

1. Select **6 — Create/edit recipe**, then confirm that you want to create a new recipe.
2. Enter the recipe's name (such as `Tuna Mayo Onigiri`) and its menu price.
3. Choose an ingredient ID and specify **how much is needed for one serving**.
4. Repeat for each ingredient and leave the ingredient ID blank to finish.
5. Use **7 — View recipes** to inspect the saved recipe and its quantities.

To edit a recipe, choose **6**, answer **No** when asked to create a new recipe, then enter an existing recipe ID. Select an ingredient and either remove it from the recipe or enter a new per-serving quantity. **Editing a recipe's price is not available in the current menu**; the price is set when the recipe is created.

### Create and complete an order

1. Choose **8 — Create customer order**.
2. Select one or more **recipe IDs** and enter a whole-number serving count for each.
3. Leave the recipe ID blank to finish, then confirm **Save as Pending**.
4. Choose whether to **mark the order Completed now**.
   - **Yes:** stock is checked, required ingredients are deducted, transactions are recorded, and the order becomes Completed.
   - **No:** the order remains Pending and **no ingredients are deducted yet**.
5. To complete it later, choose **9**, select its order ID, enter `c`, and confirm.

If the order requires more of **any** ingredient than you have available, the completion is rejected. **Nothing is deducted and the order remains Pending**; this prevents a partly fulfilled inventory update. An order that has already been completed cannot be completed again, preventing a duplicate deduction.

**Example:** If one Tuna Mayo Onigiri uses 120 g of rice, 1 nori sheet, 55 g of tuna, 20 g of mayonnaise and 1 wrapper, completing an order for **two** uses **240 g of rice, 2 sheets, 110 g of tuna, 40 g of mayonnaise and 2 wrappers**. The menu item’s recipe defines these requirements.

Option **9** also allows you to **cancel** a Pending order using `x`; a cancelled order does not deduct inventory. External orders from other systems that have no recipe lines cannot be completed through this menu.

## 7. Suppliers, purchase orders and deliveries (options 5, 11, 12 and 14)

### Register suppliers (option 14)

Choose **14 — Manage suppliers** to list existing suppliers. Confirm that you want to add one, then enter its name and contact details. Supplier IDs are displayed when you receive a delivery.

### Create an inventory purchase order (option 11)

1. Choose **11 — Create inventory purchase order**.
2. Review the current low-stock ingredients listed as a reference. You can order ingredients **even if they are not currently low**.
3. Enter the ingredient ID and the positive quantity you want to order. Repeat as necessary.
4. Leave the next ingredient ID blank when finished.
5. Enter optional notes and confirm.

The purchase order is stored as **Confirmed**. **Creating the purchase order does not add stock to inventory**. Stock increases only after a delivery is recorded.

### Receive a delivery (option 5)

1. Choose **5 — Receive supplier delivery**.
2. Enter the Supplier ID (or leave it blank if the supplier is unknown).
3. Indicate whether the delivery belongs to a **confirmed purchase order**.
4. If Yes, enter the purchase order ID and select from its **outstanding** ingredients.
5. Enter how much of each ingredient actually arrived; leave the next ID blank to finish.
6. Confirm the delivery. Inventory and the purchase order are updated together.

If a delivery is linked to a purchase order, you cannot receive an ingredient that is not on the order or a quantity greater than its remaining balance. The purchase order status changes to **Partially Received** or **Received** as appropriate.

If the delivery is **not** linked to a purchase order, you can still select ingredients and record the stock receipt; it simply will not update a purchase order's received quantities.

Use **12 — View inventory purchase orders** to see each purchase order and its individual `Ordered`, `Received` and `Remaining` quantities.

Use **13 — View transaction history** to review the **40 most recent** inventory movements, newest first. Adding stock records a positive change; deductions record a negative change. Transaction types include Opening Stock, Manual Adjustment, Supplier Delivery and Customer Order.

## Owner account management (option 15)

After signing in as an **Owner**, enter **15** to display the User Management submenu. It **stays open** until you select **0 — Return to main menu**, so you can work on several users without starting again.

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

For existing installations, update the Python code **inside your existing project folder** but retain your own `btm495.db` and `backups` directory. On the next start, the program adds a single `accountActive` field to existing `User` records; it does **not** remove existing accounts or profile values. If you unzip to a different folder, it will instead create a new database there unless you move your existing `btm495.db` into that folder.

---

## Use Case #5: My Profile (option 18)

This addition implements **5a View Profile** (always included) and **5b Update Profile** (optional). It follows the supplied Use Case #5 description, activity diagram, class diagram and Profile CRC card.

1. Log in as an Owner, Employee or Customer using the existing credentials. Owners can create a Customer account using option **15**; customer self-registration was not specified and is not included.
2. Select **18 — My Profile**. The system retrieves **your own** linked profile and displays the profile ID, name, phone number and birth date, plus read-only username, role and email (if any).
3. Respond **n** to close the profile without changing it. Respond **y** to edit name, phone number or birth date.
4. For each field, press **Enter** to keep the existing value. Type a new value to change it. Type **`-`** to remove a phone number or birth date. Dates use **YYYY-MM-DD**.
5. The system validates the proposed values. It requires a nonempty name, checks phone number syntax, and prevents impossible or future birth dates. Invalid entries display an error and invite correction. You can decline to save and discard all pending edits.
6. Confirm **Save** to write changes atomically to the existing SQLite database. The updated name also appears in the shared `User` table and menu after successful saving. A save failure rolls back all pending changes.

**Customers** see a limited menu (`18 — My Profile`, `17 — Log out`, `0 — Exit`). They do not receive the stock/order administration menu. The application currently trusts the user ID returned by its existing login service; any future web/API integration must identify the user from an authenticated session and must not accept an arbitrary user ID from the client.

**For developers:** `ProfileService(db_path).view_profile(current_user_id)` returns an immutable `Profile` domain object. `update_profile(current_user_id, {'name': ..., 'phoneNumber': ..., 'dateOfBirth': ...}, expected_version=profile.version)` validates and commits the user's data. `Profile.validate_changes()` handles the CRC card's validation responsibility. Profile IDs are stable strings, as specified by that card. Future use cases should reuse the same `User.userID` and `Profile` row, not introduce another user/profile table. No loyalty points, payroll data, or authentication credentials are editable through this module.

---

## 8. Sample data, backups, resets and restore

**Option 16 is available to Owners only.** It opens its own sub-menu:

| Sub-option | Action | What is saved or replaced? |
|---|---|---|
| **1 — Populate an EMPTY inventory** | Adds the prepared Onigiri Shop scenario without first replacing the database. | **Adds sample records**; rejects existing inventory/sample data to avoid duplicates. |
| **2 — Create backup** | Copies the current database to `backups/`. | **Does not change** the active database. |
| **3 — Backup + reset + sample data** | Creates a backup, clears the live database and loads the supplied sample dataset. | **Preserves Customer/Employee/Owner login accounts and their profiles**; replaces business tables. Use when a consistent starting dataset is needed. |
| **4 — Backup + reset empty** | Creates a backup and prepares a blank set of business tables. | **Preserves login accounts and their profiles**; business records are cleared. |
| **5 — Restore a previous backup** | Lists backups, allows you to choose one and backs up the current state before restoring. | Replaces the **entire** live database with the selected backup, including accounts and unrelated tables. |
| **6 — Backup + factory reset** | Backs up the current database and clears everything. | Also **removes all accounts**; the next startup asks you to create a new Owner. |
| **0 — Back** | Returns to the main menu. | No changes. |

### Included sample data

The sample dataset includes:

- **14 ingredients**, with quantities and individually defined reorder levels.
- **7 recipes:** Tuna Mayo, Salmon, Umeboshi, Teriyaki Tofu, Cucumber Sesame, Spicy Tuna and Plain Onigiri.
- **3 fictional suppliers** and contact details.
- **5 customer orders:** 4 Completed (with ingredients already deducted) and 1 Pending.
- **1 partially received inventory purchase order**, with its remaining quantities.
- Inventory transactions and **3 initial low-stock alerts**.

All sample quantities, supplier contacts and menu prices are fictional.

**To load sample data:** choose **16 → 1** when the inventory is empty. To clear existing business data and reload the same sample dataset, use **16 → 3**. This resets the entire shared database, so back up or coordinate with any other applications using it first.

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

**Reset is broader than the inventory module.** If payroll, loyalty, accounting or analytics data is stored in the same SQLite file, those records and tables **will not be present in the fresh active database** after a reset. They remain in the dated backup. Do not reset a shared database without coordinating with other users or applications relying on it.

**Close other programs using `btm495.db` before resetting or restoring**, including database browser applications, or other Python applications. Keep an additional offline copy of any important project data.

### Restore procedure

1. Log in as Owner and select **16 → 5**.
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

The `RecipeIngredient` table stores the amount of an ingredient needed for one serving; `OrderRecipe` stores the number of servings on a customer order. These are supporting tables needed to implement recipe-based deductions reliably.

### Using an existing `btm495.db`

1. **Make a separate copy of the database before connecting it.**
2. Put the application's `.py` files alongside that `btm495.db`, or carefully arrange for `inventory_db.py` to point to your intended database location.
3. Run `inventory_cli.py` normally. It will use the existing file and add its missing inventory/profile-supporting columns and tables as needed, without resetting it on startup. Existing User records are given linked profiles if missing.
4. Test the connection using a **copy** of your real database first, especially if its existing schema differs from the supplied tables.

**Caution:** The database path is based on the folder containing `inventory_db.py`, **not** whatever folder your terminal happens to be in. If you accidentally run a second copy of the application from another extracted folder, it may create a second `btm495.db` there. Always run the correct copy.

Loyalty, payroll, analytics and accounting are **not included as functional modules in this application**. Updating an external order's status with raw SQL does **not** automatically deduct its ingredients. An external ordering system should call `InventoryService.complete_customer_order()` (with recipe lines and a valid user ID) when completing a customer order.

## 10. Troubleshooting

| Problem | What to check |
|---|---|
| `py` or `python` command not found | Confirm Python 3.10+ is installed, then try `py`, `python` or `python3` as appropriate. |
| `No module named inventory_service` or `demo_tools` | Extract **all** files to one folder; don't run only `inventory_cli.py` in isolation. |
| Application creates a new, empty database | Confirm you launched the copy of the application that sits beside the intended `btm495.db`. |
| Cannot log in after closing/restarting | Use the same username and password. If you switched to a different folder/database or restored a backup, its accounts may differ. |
| Password appears invisible | This is expected: the program deliberately hides password input. |
| Sample-data loading says existing records found | This prevents duplicates. Use **16 → 3** to reset and reload sample data, after reviewing the shared-database warning. |
| Ingredient shows `LOW` when quantity is not zero | `LOW` is based on **quantity below reorder level**, not quantity reaching zero. Change its threshold using option **3**. |
| Cannot complete a customer order | Check that the order is Pending, each recipe has ingredients, and there is enough stock for the **entire** order. |
| Purchase order does not increase stock | This is expected. Use option **5** to receive the ordered ingredients. |
| Cannot receive a purchase order line | Verify the purchase order is open, the ingredient belongs to it and the received amount does not exceed what remains outstanding. |
| Reset or restore reports that the database is in use | Close other Python programs, database browsers and other applications using the SQLite file, then try again. |
| Database save error | Recheck file/folder permissions and disk space. A failed inventory transaction is rolled back rather than half-saved. |

## 11. Optional automated tests

From the project folder, run:

```bat
py -m unittest -v test_inventory.py test_demo_tools.py
```

On macOS or Linux, replace `py` with `python3`. The tests exercise inventory operations plus Profile Management for every role, data validation, cancellation, database rollback, account-preserving reset and restore. **They create temporary test databases, not your live `btm495.db`.**

## 12. Updating from an older version

If you're updating from an earlier version and **already have saved data**:

1. Close the running application.
2. Back up your existing `btm495.db` to another folder first.
3. Replace the application `.py` files and `README.md` with the updated V2 files, or just replace `README.md` if you're only updating this guide.
4. **Do not overwrite or delete `btm495.db` or the `backups/` folder.**
5. Launch the application again and log in as normal.

The repository or source ZIP does not include an active database. Replacing the README or Python files does not reset an existing `btm495.db`.

---

**Current scope:** This is a local, single-location command-line application. It does not process payments, operate as a production POS, support multiple simultaneous locations or include payroll, loyalty, accounting or analytics modules.
