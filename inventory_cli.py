"""Run: python inventory_cli.py  (no third-party packages required)."""
from __future__ import annotations

from getpass import getpass
import sqlite3

from inventory_service import InventoryError, InventoryService, InsufficientStockError
from demo_tools import backup_database, list_backups, reset_database, restore_database
from profile_service import ProfileError, ProfileNotFoundError, ProfileService
from user_management_service import UserManagementService


def heading(text: str) -> None:
    print(f"\n{'=' * 65}\n{text}\n{'=' * 65}")


def table(rows: list[dict], columns: list[tuple[str, str]]) -> None:
    if not rows:
        print("  No records found.")
        return
    widths = [min(30, max(len(title), *(len(str(row.get(key, "") or "")) for row in rows)))
              for key, title in columns]
    print("  " + "  ".join(title.ljust(w) for (_, title), w in zip(columns, widths)))
    print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        values = []
        for (key, _), width in zip(columns, widths):
            value = row.get(key, "")
            if isinstance(value, float):
                value = f"{value:g}"
            shown = " ".join(str(value if value is not None else "").split())
            if len(shown) > width:
                shown = (shown[:width-3] + "...") if width >= 4 else shown[:width]
            values.append(shown.ljust(width))
        print("  " + "  ".join(values))


def prompt(text: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{text}{suffix}: ").strip()
    return value or (default if default is not None else "")


def ask_number(text: str, *, minimum: float = 0, allow_zero: bool = False,
               default: float | None = None) -> float:
    while True:
        raw = prompt(text, str(default) if default is not None else None)
        try:
            from math import isfinite
            qty = float(raw)
            if isfinite(qty) and qty >= minimum and (qty != 0 or allow_zero):
                return qty
        except ValueError:
            pass
        print("  Please enter a valid number", "(zero allowed)." if allow_zero else "greater than zero.")


def ask_id(text: str, optional: bool = False) -> int | None:
    while True:
        raw = prompt(text)
        if not raw and optional:
            return None
        try:
            result = int(raw)
            if result > 0:
                return result
        except ValueError:
            pass
        print("  Enter a valid positive whole-number ID.")


def confirm(text: str, default_yes: bool = False) -> bool:
    option = prompt(text + " (y/n)", "y" if default_yes else "n").casefold()
    return option in {"y", "yes"}


def inventory_view(svc: InventoryService) -> None:
    items = svc.inventory()
    for i in items:
        i["low"] = "LOW" if i["quantityOnHand"] < i["reorderLevel"] else "OK"
    table(items, [("ingredientID", "ID"), ("ingredientName", "Ingredient"),
                  ("quantityOnHand", "In stock"), ("unit", "Unit"),
                  ("reorderLevel", "Reorder at"), ("low", "Status")])


def create_ingredient(svc: InventoryService, user: dict) -> None:
    heading("Add ingredient")
    name = prompt("Ingredient name")
    unit = prompt("Unit (e.g. g, sheets, ml, pieces)")
    amount = ask_number("Starting quantity", allow_zero=True)
    level = ask_number("Reorder level", allow_zero=True)
    if confirm(f"Save {name} with {amount:g} {unit} in stock?", True):
        print(f"  Ingredient #{svc.add_ingredient(name, unit, amount, level, user['userID'])} created.")
        inventory_view(svc)


def set_reorder(svc: InventoryService) -> None:
    heading("Set reorder level")
    inventory_view(svc)
    item_id = ask_id("Ingredient ID")
    level = ask_number("New reorder level", allow_zero=True)
    svc.set_reorder_level(item_id, level)
    print("  Reorder level saved. Alerts updated.")
    inventory_view(svc)


def adjustment(svc: InventoryService, user: dict) -> None:
    heading("Manual inventory adjustment (S-5)")
    inventory_view(svc)
    item_id = ask_id("Ingredient ID")
    action = prompt("Add or remove inventory (a/r)").casefold()
    if action not in {"a", "r"}:
        print("  Cancelled: select a or r.")
        return
    qty = ask_number("Quantity to adjust")
    notes = prompt("Reason / notes")
    word = "add" if action == "a" else "remove"
    if confirm(f"Confirm: {word} {qty:g} from ingredient #{item_id}?"):
        new_level = svc.adjust_stock(item_id, word, qty, user["userID"], notes)
        print(f"  Saved. New stock level: {new_level:g}.")
        inventory_view(svc)


def suppliers_menu(svc: InventoryService) -> None:
    heading("Suppliers")
    table(svc.suppliers(), [("supplierID", "ID"), ("name", "Supplier"),
                            ("contactInfo", "Contact")])
    if confirm("Add a new supplier?"):
        supplier_id = svc.add_supplier(prompt("Supplier name"), prompt("Contact information"))
        print(f"  Supplier #{supplier_id} created.")


def collect_lines(svc: InventoryService, *, receipt_order_id: int | None = None) -> dict[int, float]:
    if receipt_order_id is None:
        inventory_view(svc)
    else:
        lines = [r for r in svc.purchase_order_lines(receipt_order_id) if r["remaining"] > 1e-8]
        if not lines:
            raise InventoryError("No outstanding ingredients for that purchase order.")
        table(lines, [("ingredientID", "ID"), ("ingredientName", "Ingredient"),
                      ("remaining", "Outstanding"), ("unit", "Unit")])
    print("  Enter each ingredient ID and quantity. Leave ID blank when finished.")
    quantities: dict[int, float] = {}
    while True:
        ingredient_id = ask_id("Ingredient ID (blank to finish)", optional=True)
        if ingredient_id is None:
            break
        qty = ask_number("Quantity")
        if ingredient_id in quantities:
            print("  Replacing the previously entered amount for this ingredient.")
        quantities[ingredient_id] = qty
    return quantities


def delivery(svc: InventoryService, user: dict) -> None:
    heading("Receive supplier delivery (S-6)")
    table(svc.suppliers(), [("supplierID", "ID"), ("name", "Supplier")])
    supplier_id = ask_id("Supplier ID (blank if unknown)", optional=True)
    po_id = None
    if confirm("Is this delivery linked to a confirmed inventory purchase order?"):
        show_purchase_orders(svc)
        po_id = ask_id("Purchase order ID")
    items = collect_lines(svc, receipt_order_id=po_id)
    if not items:
        print("  No items selected. Nothing saved.")
        return
    print("  Receiving:", ", ".join(f"#{key}: +{qty:g}" for key, qty in items.items()))
    if confirm("Confirm receipt?"):
        svc.receive_delivery(items, user["userID"], supplier_id, po_id)
        print("  Delivery recorded. Inventory updated.")
        inventory_view(svc)


def show_recipes(svc: InventoryService) -> None:
    table(svc.recipes(), [("recipeID", "ID"), ("name", "Recipe"), ("price", "Price")])


def edit_recipe(svc: InventoryService) -> None:
    heading("Create or edit recipe")
    show_recipes(svc)
    if confirm("Create a new recipe?"):
        recipe_id = svc.add_recipe(prompt("Recipe name"), ask_number("Menu price", allow_zero=True))
        print(f"  Recipe #{recipe_id} created.")
    else:
        recipe_id = ask_id("Existing recipe ID")
    inventory_view(svc)
    print("  Each quantity below is the amount needed to make ONE serving.")
    print("  Enter ingredient IDs one at a time. Blank ID finishes.")
    while True:
        ingredient_id = ask_id("Ingredient ID (blank to finish)", optional=True)
        if ingredient_id is None:
            break
        if confirm("Remove this ingredient from the recipe?"):
            svc.remove_recipe_ingredient(recipe_id, ingredient_id)
            print("  Removed.")
        else:
            qty = ask_number("Required quantity per serving")
            svc.set_recipe_ingredient(recipe_id, ingredient_id, qty)
            print("  Recipe ingredient saved.")
    show_recipe_details(svc, recipe_id)


def show_recipe_details(svc: InventoryService, recipe_id: int) -> None:
    table(svc.recipe_ingredients(recipe_id),
          [("ingredientID", "ID"), ("ingredientName", "Ingredient"),
           ("quantityRequired", "Per serving"), ("unit", "Unit"),
           ("quantityOnHand", "Available")])


def recipes_menu(svc: InventoryService) -> None:
    heading("Recipes")
    show_recipes(svc)
    if confirm("View a recipe's ingredients?"):
        show_recipe_details(svc, ask_id("Recipe ID"))


def order_create(svc: InventoryService, user: dict) -> None:
    heading("Create customer order")
    show_recipes(svc)
    print("  Add recipes. Leave recipe ID blank to finish.")
    items: dict[int, int] = {}
    while True:
        recipe_id = ask_id("Recipe ID (blank to finish)", optional=True)
        if recipe_id is None:
            break
        count = ask_number("Number of servings")
        if not count.is_integer():
            print("  Servings must be whole numbers.")
            continue
        items[recipe_id] = items.get(recipe_id, 0) + int(count)
    if not items:
        print("  Order cancelled.")
        return
    if confirm("Save customer order as Pending?", True):
        order_id = svc.create_customer_order(items, user["userID"])
        print(f"  Customer order #{order_id} saved as Pending. No stock deducted yet.")
        if confirm("Mark this order Completed now and deduct ingredients?", True):
            completed = svc.complete_customer_order(order_id, user["userID"])
            print(f"  Completed order #{completed['order_id']}. Stock deducted for all recipes.")
            inventory_view(svc)


def show_orders(svc: InventoryService) -> None:
    table(svc.customer_orders(), [("orderID", "Order ID"), ("orderDate", "Date"),
                                  ("status", "Status"), ("totalAmount", "Total"),
                                  ("recipesCount", "Recipe lines")])


def orders_menu(svc: InventoryService, user: dict) -> None:
    heading("Customer orders (S-7)")
    show_orders(svc)
    order_id = ask_id("Order ID (blank to return)", optional=True)
    if order_id is None:
        return
    table(svc.order_recipes(order_id), [("recipeID", "ID"), ("name", "Recipe"),
                                        ("quantity", "Servings"), ("price", "Unit price")])
    action = prompt("[c] Complete | [x] Cancel pending order | [enter] Back").lower()
    if action == "c" and confirm("Confirm completion and inventory deduction?"):
        completed = svc.complete_customer_order(order_id, user["userID"])
        print(f"  Completed order #{completed['order_id']}.")
        inventory_view(svc)
    elif action == "x" and confirm("Cancel order?"):
        svc.cancel_customer_order(order_id)
        print("  Order cancelled; no stock was deducted.")


def alerts_menu(svc: InventoryService) -> None:
    heading("Low-stock alerts (S-9)")
    print("  An alert is raised when stock is BELOW the reorder level.")
    table(svc.alerts(), [("alertID", "Alert ID"), ("ingredientName", "Ingredient"),
                         ("quantityOnHand", "In stock"), ("reorderLevel", "Reorder at"),
                         ("unit", "Unit"), ("status", "Status")])
    alert_id = ask_id("Alert ID (blank to return)", optional=True)
    if alert_id is None:
        return
    action = prompt("[r] Mark reviewed | [c] Close | [enter] Back").lower()
    if action in {"r", "c"}:
        svc.update_alert(alert_id, "Reviewed" if action == "r" else "Closed")
        print("  Alert updated.")
        if action == "c":
            print("  Note: if inventory changes while still low, a new alert can be raised.")


def purchase_create(svc: InventoryService) -> None:
    heading("Create inventory purchase order (S-9)")
    active = svc.alerts()
    if active:
        table(active, [("ingredientID", "ID"), ("ingredientName", "Low-stock ingredient"),
                       ("quantityOnHand", "In stock"), ("reorderLevel", "Reorder at")])
    else:
        print("  No active alerts. You may still order ingredients.")
    items = collect_lines(svc)
    if not items:
        print("  Nothing selected.")
        return
    notes = prompt("Notes")
    if confirm("Confirm and save this purchase order?"):
        po_id = svc.create_purchase_order(items, notes)
        print(f"  Inventory purchase order #{po_id} Confirmed and saved.")
        print("  Inventory will increase only when its delivery is received.")


def show_purchase_orders(svc: InventoryService) -> None:
    table(svc.purchase_orders(),
          [("inventoryOrderID", "PO ID"), ("orderDate", "Date"),
           ("status", "Status"), ("itemsCount", "Lines"), ("notes", "Notes")])


def purchase_menu(svc: InventoryService) -> None:
    heading("Inventory purchase orders")
    show_purchase_orders(svc)
    po_id = ask_id("Purchase order ID (blank to return)", optional=True)
    if po_id is not None:
        table(svc.purchase_order_lines(po_id),
              [("ingredientID", "ID"), ("ingredientName", "Ingredient"),
               ("quantityOrdered", "Ordered"), ("receivedQuantity", "Received"),
               ("remaining", "Remaining"), ("unit", "Unit")])


def transaction_history(svc: InventoryService) -> None:
    heading("Recent inventory transactions (newest first)")
    table(svc.transactions(), [("transactionID", "ID"), ("transactionDate", "Date"),
                               ("ingredientName", "Ingredient"), ("transactionType", "Type"),
                               ("quantity", "Change"), ("unit", "Unit"),
                               ("customerOrderID", "Order"), ("inventoryOrderID", "PO")])


def _owner_recheck(svc: InventoryService, user: dict) -> None:
    """Ask for the current password before changing the database file."""
    password = getpass("Re-enter your account password to continue: ")
    check = svc.login(user["username"], password)
    if check["userID"] != user["userID"] or check["role"] != "Owner":
        raise InventoryError("Owner verification failed.")


def _reset_confirmation() -> bool:
    print("  WARNING: ALL BUSINESS DATA in btm495.db will be replaced, including")
    print("  records belonging to other modules of your team's project.")
    print("  The full current database will be backed up automatically first.")
    return prompt("  Type RESET to confirm (anything else cancels)") == "RESET"


def demo_menu(svc: InventoryService, user: dict) -> bool:
    """Owner-only: return True if reset/restore requires a fresh login."""
    if user["role"] != "Owner":
        raise InventoryError("Only owners can manage demo data and database backups.")
    while True:
        heading("DEMO / DATABASE MANAGEMENT (OWNER ONLY)")
        print('''
   1. Populate an EMPTY inventory with realistic Onigiri shop demo data
   2. Create a backup of the current database (no data changed)
   3. BACKUP + RESET entire database + load fresh demo data
      (keep existing login accounts)
   4. BACKUP + RESET entire database to empty business tables
      (keep existing login accounts)
   5. Restore a previous database backup (current database backed up first)
   6. BACKUP + FACTORY RESET entire database (including login accounts)
   0. Back to main menu
''')
        choice = prompt("Select demo option")
        if choice == "0":
            return False
        if choice == "1":
            if confirm("Load 14 ingredients, 7 recipes, suppliers and sample orders?", True):
                summary = svc.load_demo_data(user["userID"])
                print("  Demo records saved:", ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in summary.items()))
                print("  Includes low stock, completed and pending customer orders, and a partial delivery.")
                inventory_view(svc)
        elif choice == "2":
            if confirm("Create a database backup now?", True):
                backup_path = backup_database(svc)
                print(f"  Backup created: {backup_path}")
        elif choice in {"3", "4", "6"}:
            if not _reset_confirmation():
                print("  Reset cancelled. No data changed.")
                continue
            _owner_recheck(svc, user)
            path = reset_database(svc, user["userID"], with_demo=choice == "3",
                                  preserve_accounts=choice != "6")
            print(f"  Backup of previous database: {path}")
            print("  Reset completed. Returning to login.")
            if choice == "6":
                print("  On the next login, you will create a new Owner account.")
            return True
        elif choice == "5":
            backups = list_backups(svc)
            if not backups:
                print("  There are no backups in the backups folder.")
                continue
            print("  Available backups (newest first):")
            for index, path in enumerate(backups, 1):
                print(f"   {index}. {path.name}")
            raw = prompt("Backup number to restore (blank to cancel)")
            if not raw:
                continue
            if not raw.isdigit() or not 1 <= int(raw) <= len(backups):
                print("  Invalid backup selection.")
                continue
            selected = backups[int(raw) - 1]
            print(f"  Restoring {selected.name} REPLACES all current database tables and accounts.")
            if prompt("Type RESTORE to confirm") != "RESTORE":
                print("  Restore cancelled.")
                continue
            _owner_recheck(svc, user)
            safety = restore_database(svc, user["userID"], selected)
            print(f"  Database restored. Backup of the just-replaced state: {safety}")
            print("  Returning to login. Use the credentials from the restored database.")
            return True
        else:
            print("  Invalid selection.")
        input("\nPress Enter to continue...")


def profile_menu(svc: ProfileService, user: dict) -> None:
    """Use Case 5: view -> optionally edit -> validate -> save/cancel."""
    try:
        profile = svc.view_profile(user['userID'])
    except ProfileNotFoundError as exc:
        print(f"  {exc}")
        return
    while True:
        heading('PROFILE MANAGEMENT | My Profile')
        print(f"  Profile ID:    {profile.profile_id}")
        print(f"  Username:      {profile.username} (read-only)")
        print(f"  Role:          {profile.role} (read-only)")
        print(f"  Email:         {profile.email or 'Not provided'} (read-only)")
        print(f"  Name:          {profile.name}")
        print(f"  Phone number:  {profile.phone_number or 'Not provided'}")
        print(f"  Date of birth: {profile.date_of_birth or 'Not provided'}")
        if not confirm('Would you like to update your profile?'):
            return  # view-only happy path: no database write
        print("  Press Enter to keep a field, or type '-' to clear phone/date of birth.")
        changes = {}
        for key, label, original in (
            ('name', 'Name', profile.name),
            ('phoneNumber', 'Phone number', profile.phone_number),
            ('dateOfBirth', 'Date of birth (YYYY-MM-DD)',
             profile.date_of_birth.isoformat() if profile.date_of_birth else None),
        ):
            typed = input(f"{label} [{original or 'Not provided'}]: ").strip()
            if typed:
                changes[key] = '' if typed == '-' else typed
        if not changes:
            print('  Nothing changed. The profile remains unchanged.')
            return
        try:
            profile.validate_changes(changes)
        except ProfileError as exc:
            print(f'  Please correct the information: {exc}')
            continue  # exceptional flow 5A.4A: display error and retry
        if not confirm('Save these changes?'):
            print('  Update cancelled. Unsaved changes were discarded.')
            return  # exceptional flow 5A.3A
        profile = svc.update_profile(user['userID'], changes, expected_version=profile.version)
        user['name'] = profile.name  # menu heading uses shared User.name
        print('  Profile successfully updated and saved.')
        return


def employees_menu(svc: InventoryService, user: dict) -> None:
    """Option 15: owner-only CRUD-style management of shared user accounts."""
    admin = UserManagementService(svc.db_path)
    actor_id = user['userID']  # passed from the authenticated login
    while True:
        heading('USER MANAGEMENT | Owner only')
        table(admin.list_accounts(actor_id), [('userID', 'ID'), ('name', 'Name'),
                                               ('username', 'Username'), ('role', 'Role'),
                                               ('status', 'Status')])
        print("""
   1. View user details              5. Reset user's password
   2. Create new user                6. Disable / enable user
   3. Edit user information          7. Delete user (if no linked records)
   4. Change user's role             0. Return to main menu
""")
        choice = prompt('Select user management option')
        if choice == '0':
            return
        try:
            if choice == '1':
                uid = ask_id('User ID')
                details = admin.get_account(actor_id, uid)
                heading(f'Account #{uid} | {details["username"]}')
                print(f"  Name:          {details['name']}")
                print(f"  Username:      {details['username']}")
                print(f"  Role:          {details['role']}")
                print(f"  Status:        {'Active' if details['accountActive'] else 'Disabled'}")
                print(f"  Email:         {details['email'] or 'Not provided'}")
                print(f"  Phone:         {details['phoneNumber'] or 'Not provided'}")
                print(f"  Date of birth: {details['dateOfBirth'] or 'Not provided'}")
            elif choice == '2':
                roles = {'e': 'Employee', 'o': 'Owner', 'c': 'Customer'}
                selection = (prompt('Role: [e] Employee, [o] Owner or [c] Customer') or 'e').lower()
                if selection not in roles:
                    print('  Invalid role; no account created.')
                    continue
                role = roles[selection]
                if role == 'Owner' and not confirm('Allow another user Owner-level access to accounts and backups?'):
                    print('  Cancelled.')
                    continue
                name = prompt('Name')
                username = prompt('Username')
                email = prompt('Email address (optional)')
                phone_number = prompt('Phone number (optional)')
                date_of_birth = prompt('Date of birth (YYYY-MM-DD, optional)')
                pw = getpass('Password (8+ characters): ')
                pw2 = getpass('Repeat password: ')
                if pw != pw2:
                    raise InventoryError('Passwords do not match. No account was created.')
                new_id = admin.create_account(actor_id, name, username, pw, role,
                                              email=email, phone_number=phone_number,
                                              date_of_birth=date_of_birth)
                print(f'  {role} account #{new_id} created successfully.')
            elif choice == '3':
                uid = ask_id('User ID to edit')
                details = admin.get_account(actor_id, uid)
                print("  Press Enter to keep an existing value; type '-' to clear email, phone or birth date.")
                changes = {}
                for key, label, original in (
                    ('name', 'Name', details['name']),
                    ('username', 'Username', details['username']),
                    ('email', 'Email address', details['email']),
                    ('phoneNumber', 'Phone number', details['phoneNumber']),
                    ('dateOfBirth', 'Date of birth (YYYY-MM-DD)', details['dateOfBirth']),
                ):
                    typed = input(f"{label} [{original or 'Not provided'}]: ").strip()
                    if typed:
                        changes[key] = '' if typed == '-' else typed
                if not changes:
                    print('  No changes made.')
                    continue
                if not confirm('Save the edited information?'):
                    print('  Cancelled; nothing was saved.')
                    continue
                updated = admin.edit_account(actor_id, uid, changes)
                if uid == actor_id:
                    user['name'], user['username'] = updated['name'], updated['username']
                print('  Account and profile updated successfully.')
            elif choice == '4':
                uid = ask_id('User ID to change role')
                details = admin.get_account(actor_id, uid)
                roles = {'e': 'Employee', 'o': 'Owner', 'c': 'Customer'}
                selection = prompt('New role: [e] Employee, [o] Owner or [c] Customer').lower()
                if selection not in roles:
                    print('  Invalid role; no changes made.')
                    continue
                role = roles[selection]
                if role == 'Owner':
                    print('  WARNING: This grants full account and database management access.')
                if not confirm(f"Change {details['username']} from {details['role']} to {role}?"):
                    print('  Cancelled.')
                    continue
                admin.change_role(actor_id, uid, role)
                print('  User role updated.')
            elif choice == '5':
                uid = ask_id('User ID for password reset')
                details = admin.get_account(actor_id, uid)
                print(f"  Resetting password for {details['username']} (#{uid}).")
                _owner_recheck(svc, user)
                pw = getpass('New password (8+ characters): ')
                pw2 = getpass('Repeat new password: ')
                if pw != pw2:
                    raise InventoryError('Passwords do not match. Nothing was changed.')
                admin.reset_password(actor_id, uid, pw)
                print('  Password changed; the user can log in with the new password.')
            elif choice == '6':
                uid = ask_id('User ID to disable / enable')
                details = admin.get_account(actor_id, uid)
                enable = not bool(details['accountActive'])
                action = 'Enable' if enable else 'Disable'
                if not confirm(f"{action} login for {details['username']} (#{uid})?"):
                    print('  Cancelled.')
                    continue
                admin.set_active(actor_id, uid, enable)
                print(f'  User account {"enabled" if enable else "disabled"}. Historical records retained.')
            elif choice == '7':
                uid = ask_id('User ID to permanently delete')
                details = admin.get_account(actor_id, uid)
                print(f"  WARNING: Delete {details['username']} (#{uid}) and their profile permanently.")
                print('  Accounts linked to orders, inventory or other business records CANNOT be deleted.')
                if prompt('Type DELETE to confirm') != 'DELETE':
                    print('  Cancelled.')
                    continue
                _owner_recheck(svc, user)
                admin.delete_account(actor_id, uid)
                print('  User and profile deleted.')
            else:
                print('  Invalid selection. Choose 0–7.')
        except (InventoryError, ProfileError, sqlite3.Error, OSError) as exc:
            print(f'  Could not complete user management action: {exc}')
            if isinstance(exc, sqlite3.IntegrityError):
                print('  This account is referenced elsewhere; consider disabling it instead.')

def menu(svc: InventoryService, user: dict) -> None:
    while True:
        # Do not let an already-open session retain privileges after an Owner
        # disables the account or changes its role in another session.
        live = svc._read('''SELECT name,username,role FROM "User"
                            WHERE userID=? AND accountActive=1 AND passwordHash IS NOT NULL''',
                         (user['userID'],))
        if not live:
            print('  Your account is no longer active. Returning to login.')
            return
        user.update(live[0])
        if user['role'] == 'Customer':
            heading(f"ONIGIRI SHOP | Customer | {user['name']}")
            print("  18. My Profile    17. Log out    0. Exit")
            selection = prompt("Select an option")
            if selection == "0":
                raise SystemExit(0)
            if selection == "17":
                print("  Logged out.")
                return
            if selection != "18":
                print("  Invalid selection. Customer inventory administration is not available.")
                continue
            try:
                profile_menu(ProfileService(svc.db_path), user)
            except (ProfileError, sqlite3.Error, OSError) as exc:
                print(f"  Profile could not be saved: {exc}")
            input("\nPress Enter to return to the menu...")
            continue
        heading(f"ONIGIRI SHOP | Inventory Management | {user['name']} ({user['role']})")
        print('''
   1. View inventory                  10. Review low-stock alerts
   2. Add ingredient                  11. Create inventory purchase order
   3. Set reorder level               12. View inventory purchase orders
   4. Manually adjust inventory       13. View transaction history
   5. Receive supplier delivery       14. Manage suppliers
   6. Create/edit recipe              15. Manage users (Owner)
   7. View recipes                    16. Demo / backup / reset (Owner)
   8. Create customer order           17. Log out
   9. View/complete customer orders   18. My Profile
                                      0. Exit
''')
        selection = prompt("Select an option")
        if selection == "0":
            raise SystemExit(0)
        if selection == "17":
            print("  Logged out.")
            return
        actions = {
            "1": lambda: inventory_view(svc),
            "2": lambda: create_ingredient(svc, user),
            "3": lambda: set_reorder(svc),
            "4": lambda: adjustment(svc, user),
            "5": lambda: delivery(svc, user),
            "6": lambda: edit_recipe(svc),
            "7": lambda: recipes_menu(svc),
            "8": lambda: order_create(svc, user),
            "9": lambda: orders_menu(svc, user),
            "10": lambda: alerts_menu(svc),
            "11": lambda: purchase_create(svc),
            "12": lambda: purchase_menu(svc),
            "13": lambda: transaction_history(svc),
            "14": lambda: suppliers_menu(svc),
            "15": lambda: employees_menu(svc, user),
            "16": lambda: demo_menu(svc, user),
            "18": lambda: profile_menu(ProfileService(svc.db_path), user),
        }
        action = actions.get(selection)
        if not action:
            print("  Invalid selection. Choose one of the displayed numbers.")
            continue
        try:
            needs_login = action()
            if needs_login is True:
                return
        except (InventoryError, ProfileError, sqlite3.Error, OSError) as exc:
            print(f"\n  Not saved: {exc}")
            if isinstance(exc, sqlite3.Error):
                print("  The database operation was rolled back. Please try again.")
        input("\nPress Enter to return to the menu...")


def main() -> None:
    heading("BTM 495 | Onigiri Shop Inventory Proof of Concept")
    svc = InventoryService()
    from inventory_db import DEFAULT_DB
    if svc.created_database:
        print("  Created persistent database once:", DEFAULT_DB)
    else:
        print("  Using existing database (data preserved):", DEFAULT_DB)
    while True:
        if not svc.has_logins():
            print("\n  FIRST-TIME SETUP: No active logins exist.")
            print("  Create an owner account. Existing broad-system users are not deleted.")
            while True:
                try:
                    name = prompt("Owner's name")
                    username = prompt("Owner username")
                    pw = getpass("Owner password (8+ characters): ")
                    svc.create_user(name, username, pw, "Owner")
                    print("  Owner account created. You can now log in.")
                    break
                except InventoryError as exc:
                    print("  ", exc)
        heading("Login")
        username = prompt("Username (or 'exit' to quit)")
        if username.lower() == "exit":
            return
        password = getpass("Password: ")
        try:
            user = svc.login(username, password)
        except InventoryError as exc:
            print("  ", exc)
            continue
        print(f"  Welcome, {user['name']}.")
        menu(svc, user)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n  Exiting. All committed data remains in the database.")
