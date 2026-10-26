"""Loyalty program built on the shop's shared User/Customer/Order database.

This module is deliberately independent of the CLI. The future POS/accounting modules
can call preview_purchase() and process_eligible_purchase() once they confirm payment.
A completed inventory order is used as the prototype's paid-sale proxy: it is NOT
real payment processing. Values for point accrual are configurable demonstration rules.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from hashlib import pbkdf2_hmac
from pathlib import Path
import secrets
import sqlite3
from uuid import uuid4

from inventory_db import connect, initialize, transaction
from inventory_service import InventoryService, _ident, _validate_email
from accounting_service import post_source_transaction
from profile_service import _validate_dob, _validate_name, _validate_phone
from loyalty_models import LoyaltyAccount, LoyaltyTransaction, Reward, Redemption


class LoyaltyError(ValueError):
    """Invalid account, purchase, reward or loyalty business rule."""


class AccountNotFoundError(LoyaltyError):
    """The customer/loyalty account was not found."""


class InsufficientPointsError(LoyaltyError):
    """Not enough points for the chosen reward."""


class IneligiblePurchaseError(LoyaltyError):
    """The purchase (or part of it) earns no loyalty points."""


class DuplicatePurchaseError(LoyaltyError):
    """Do not record the same completed order in the loyalty ledger twice."""


@dataclass(frozen=True)
class LoyaltyQuote:
    customer_id: int
    order_id: int
    purchase_amount: Decimal
    eligible_amount: Decimal
    discount_amount: Decimal
    final_amount: Decimal
    reward_id: int | None
    points_earned: int
    points_redeemed: int
    previous_balance: int
    new_balance: int


def _money(value: object, label: str, *, zero_ok: bool = True) -> Decimal:
    """Normalize CAD amounts to cents without float arithmetic or silent rounding."""
    try:
        if isinstance(value, bool):
            raise ValueError()
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise LoyaltyError(f'{label} must be a valid monetary amount.') from exc
    if not amount.is_finite() or amount < 0 or (not zero_ok and amount == 0):
        raise LoyaltyError(f'{label} must be {"nonnegative" if zero_ok else "positive"}.')
    if amount != amount.quantize(Decimal('0.01')):
        raise LoyaltyError(f'{label} must be expressed to at most two decimal places.')
    return amount.quantize(Decimal('0.01'))


def _active_employee(db: sqlite3.Connection, employee_id: int) -> None:
    row = db.execute('''SELECT u.role,u.accountActive,u.passwordHash,e.isActive
                        FROM "User" u LEFT JOIN Employee e ON e.userID=u.userID
                        WHERE u.userID=?''', (_ident(employee_id, 'Employee ID'),)).fetchone()
    if (not row or row['accountActive'] != 1 or not row['passwordHash'] or
            row['role'] not in ('Owner', 'Employee') or
            (row['role'] == 'Employee' and row['isActive'] != 1)):
        raise LoyaltyError('An active Owner or Employee must confirm the loyalty action.')


def _account(db: sqlite3.Connection, customer_id: int) -> sqlite3.Row:
    row = db.execute('''SELECT a.loyaltyAccountID,a.loyaltyAccountID AS accountID,
                               a.customerID,a.pointsBalance,a.pointsBalance AS currentPoints,
                               a.joinedAt,a.status,a.publicUUID,
                               c.userID,u.name,u.username,u.email,u.accountActive,p.phoneNumber
                        FROM LoyaltyAccount a JOIN Customer c ON c.customerID=a.customerID
                        JOIN "User" u ON u.userID=c.userID
                        LEFT JOIN Profile p ON p.userID=u.userID
                        WHERE a.customerID=?''',
                     (_ident(customer_id, 'Customer ID'),)).fetchone()
    if row is None:
        raise AccountNotFoundError('No loyalty account for that customer ID. Check the ID or register first.')
    if not row['accountActive']:
        raise LoyaltyError('This customer account is inactive. Ask the Owner for assistance.')
    return row


def _account_model(row: sqlite3.Row) -> LoyaltyAccount:
    return LoyaltyAccount(accountID=row['loyaltyAccountID'], customerID=row['customerID'],
                          currentPoints=row['pointsBalance'], status=row['status'],
                          publicUUID=row['publicUUID'])


def _reward_model(row: sqlite3.Row) -> Reward:
    return Reward(rewardID=row['rewardID'], name=row['name'],
                  pointsRequired=row['pointsCost'], available=bool(row['isActive']),
                  discountAmount=Decimal(str(row['discountAmount'])),
                  publicUUID=row['publicUUID'])


# Optional, demonstration-only discount catalogue (CAD). The points and dollar
# values are configurable sample rules.
# Loading is deferred until a user opens the Loyalty Program (option 5).
# This gives a 5% nominal return: 10 points / $1, $5 for 1,000 points.
SAMPLE_REWARDS = (
    ('$5 Discount', 1000, '5.00'),
    ('$10 Discount', 2000, '10.00'),
    ('$15 Discount', 3000, '15.00'),
    ('$20 Discount', 4000, '20.00'),
)

# Previous release's built-in rewards. On first loyalty visit, update ONLY
# still-active rewards that exactly match their old built-in pricing and
# discount; leave customized prices and deactivated rewards untouched.
LEGACY_SAMPLE_REWARD_COSTS = {
    '$5 Discount': 500,
    '$10 Discount': 1000,
    '$15 Discount': 1500,
    '$20 Discount': 2000,
}


class LoyaltyService:
    """Registration, verification, reward catalogue, point balance and audited ledger.

    `points_per_dollar` is a configurable business rule. The CLI installs sample discount
    rewards on first entry to loyalty; Owners can add/deactivate other rewards.
    Eventually the POS will supply eligibility and apply actual discounts.
    """

    def __init__(self, db_path: str | Path | None = None, *, points_per_dollar: int = 10):
        if isinstance(points_per_dollar, bool) or not isinstance(points_per_dollar, int) or points_per_dollar < 1:
            raise LoyaltyError('Points per dollar must be a positive whole number.')
        self.db_path = db_path
        self.points_per_dollar = points_per_dollar
        initialize(db_path)

    # Customer registration reuses User, Customer and Profile.
    def register_customer(self, employee_id: int, name: str, *, email: str | None = None,
                          phone_number: str | None = None, username: str | None = None,
                          password: str | None = None,
                          date_of_birth: str | None = None) -> dict:
        try:
            name = _validate_name(name)
            email = _validate_email(email)
            phone_number = _validate_phone(phone_number)
            birth_date = _validate_dob(date_of_birth)
        except ValueError as exc:
            raise LoyaltyError(str(exc)) from exc
        if not email and not phone_number:
            raise LoyaltyError('Provide an email or phone number for account lookup.')
        if username is not None:
            username = username.strip()
            if not username or len(username) > 64 or any(c.isspace() or ord(c) < 32 for c in username):
                raise LoyaltyError('Username must be 1–64 characters without spaces.')
        if password is not None and (not isinstance(password, str) or len(password) < 8):
            raise LoyaltyError('Password must contain at least eight characters.')
        initial_password = password if password is not None else secrets.token_urlsafe(12)
        with transaction(self.db_path) as db:
            _active_employee(db, employee_id)
            # Prevent accidental double-enrolment of an existing customer.
            matches = db.execute('''SELECT u.userID FROM "User" u
                LEFT JOIN Profile p ON p.userID=u.userID
                WHERE u.role='Customer' AND
                ((? IS NOT NULL AND lower(u.email)=lower(?)) OR
                 (? IS NOT NULL AND p.phoneNumber=?))''',
                (email, email, phone_number, phone_number)).fetchall()
            if matches:
                raise LoyaltyError('A customer with that contact information already exists. '
                                   'Find their Customer ID and enroll the existing account instead.')
            if username and db.execute('SELECT 1 FROM "User" WHERE lower(username)=lower(?)',
                                       (username,)).fetchone():
                raise LoyaltyError('That username is already in use. Choose another.')
            salt = secrets.token_hex(16)
            digest = pbkdf2_hmac('sha256', initial_password.encode('utf-8'),
                                bytes.fromhex(salt), 220_000).hex()
            user_id = db.execute('''INSERT INTO "User"(name,email,role,passwordHash,passwordSalt)
                                    VALUES(?,?,?,?,?)''',
                                 (name, email, 'Customer', digest, salt)).lastrowid
            if username is None:
                username = f'walkin{user_id}'
                suffix = 1
                while db.execute('SELECT 1 FROM "User" WHERE lower(username)=lower(?) AND userID<>?',
                                 (username, user_id)).fetchone():
                    username = f'walkin{user_id}_{suffix}'
                    suffix += 1
            db.execute('UPDATE "User" SET username=? WHERE userID=?', (username, user_id))
            customer_id = db.execute('INSERT INTO Customer(userID) VALUES(?)', (user_id,)).lastrowid
            db.execute('INSERT INTO Profile(profileID,userID,name,phoneNumber,dateOfBirth) VALUES(?,?,?,?,?)',
                       (uuid4().hex, user_id, name, phone_number,
                        birth_date.isoformat() if birth_date else None))
            db.execute('INSERT INTO LoyaltyAccount(customerID,pointsBalance,publicUUID) VALUES(?,0,?)',
                       (customer_id, str(uuid4())))
            return {**dict(_account(db, customer_id)), 'initialPassword': initial_password}

    def enroll_existing_customer(self, customer_user_id: int, actor_id: int) -> dict:
        """Enroll an existing customer (by authorized staff or the customer)."""
        with transaction(self.db_path) as db:
            target = db.execute('''SELECT c.customerID,u.accountActive,u.role
                                   FROM "User" u LEFT JOIN Customer c ON c.userID=u.userID
                                   WHERE u.userID=?''',
                                (_ident(customer_user_id, 'User ID'),)).fetchone()
            if not target or target['role'] != 'Customer' or target['customerID'] is None:
                raise AccountNotFoundError('No Customer user with that User ID. Use 5 → 9 to find User IDs.')
            if not target['accountActive']:
                raise LoyaltyError('This Customer login is disabled. Ask an Owner to enable it under 20 → 6 first.')
            if actor_id != customer_user_id:
                _active_employee(db, actor_id)
            else:
                owner = db.execute('SELECT passwordHash FROM "User" WHERE userID=?',
                                   (actor_id,)).fetchone()
                if not owner or not owner['passwordHash']:
                    raise LoyaltyError('The customer must be signed in to self-enroll.')
            db.execute('''INSERT OR IGNORE INTO LoyaltyAccount(customerID,pointsBalance,publicUUID)
                          VALUES(?,0,?)''', (target['customerID'], str(uuid4())))
            return dict(_account(db, target['customerID']))

    def find_customers(self, employee_id: int, search: str) -> list[dict]:
        """Employee-verified lookup by exact email/phone; ID can be entered directly."""
        with closing(connect(self.db_path)) as db:
            _active_employee(db, employee_id)
            search = search.strip()
            if not search:
                raise LoyaltyError('Enter an email or phone number.')
            return [dict(r) for r in db.execute('''SELECT c.customerID,c.userID,u.name,u.email,
                                    p.phoneNumber,a.pointsBalance
                FROM Customer c JOIN "User" u ON u.userID=c.userID
                LEFT JOIN Profile p ON p.userID=u.userID
                LEFT JOIN LoyaltyAccount a ON a.customerID=c.customerID
                WHERE lower(u.email)=lower(?) OR p.phoneNumber=? ORDER BY c.customerID''',
                  (search, search))]

    def list_customers(self, employee_id: int) -> list[dict]:
        """Show every Customer user, including those not enrolled in loyalty."""
        with closing(connect(self.db_path)) as db:
            _active_employee(db, employee_id)
            return [dict(row) for row in db.execute('''
                SELECT c.customerID,u.userID,u.name,u.username,u.email,
                       CASE WHEN u.accountActive=1 THEN 'Active' ELSE 'Disabled' END AS userStatus,
                       CASE WHEN a.loyaltyAccountID IS NULL THEN 'Not enrolled'
                            ELSE a.status END AS loyaltyStatus, a.pointsBalance
                FROM "User" u JOIN Customer c ON c.userID=u.userID
                LEFT JOIN LoyaltyAccount a ON a.customerID=c.customerID
                WHERE u.role='Customer' ORDER BY u.userID''')]

    def customer_status(self, customer_id: int) -> dict:
        """Check account, enrollment, and activation before a pending order completes."""
        with closing(connect(self.db_path)) as db:
            row = db.execute('''SELECT c.customerID,u.userID,u.name,u.accountActive,
                              a.loyaltyAccountID,a.status AS loyaltyStatus,a.pointsBalance
                              FROM Customer c JOIN "User" u ON u.userID=c.userID
                              LEFT JOIN LoyaltyAccount a ON a.customerID=c.customerID
                              WHERE c.customerID=? AND u.role='Customer' ''',
                             (_ident(customer_id, 'Customer ID'),)).fetchone()
            if not row:
                raise AccountNotFoundError('Customer ID not found. See option 5 → 9 for the customer list.')
            return dict(row)

    def customer_id_for_user(self, customer_user_id: int) -> int:
        with closing(connect(self.db_path)) as db:
            row = db.execute('SELECT customerID FROM Customer WHERE userID=?',
                             (_ident(customer_user_id, 'User ID'),)).fetchone()
            if not row:
                raise AccountNotFoundError('This user has no Customer record.')
            return row['customerID']

    # 6a Validate Account Information / 6b Retrieve Customer Account.
    def retrieve_customer_account(self, customer_id: int) -> dict:
        with closing(connect(self.db_path)) as db:
            return dict(_account(db, customer_id))

    def account_model(self, customer_id: int) -> LoyaltyAccount:
        """Retrieve the loyalty account model with compatible balance fields."""
        with closing(connect(self.db_path)) as db:
            return _account_model(_account(db, customer_id))

    def set_loyalty_account_status(self, owner_id: int, customer_id: int, status: str) -> None:
        """Owner-only account suspension/reactivation; never deletes the ledger."""
        if status not in ('Active', 'Suspended'):
            raise LoyaltyError('Status must be Active or Suspended.')
        with transaction(self.db_path) as db:
            owner = db.execute('''SELECT role,accountActive,passwordHash FROM "User"
                                  WHERE userID=?''', (_ident(owner_id, 'Owner ID'),)).fetchone()
            if not owner or owner['role'] != 'Owner' or not owner['accountActive'] or not owner['passwordHash']:
                raise LoyaltyError('Only an active Owner can change loyalty account status.')
            acc = _account(db, customer_id)
            db.execute('UPDATE LoyaltyAccount SET status=? WHERE loyaltyAccountID=?',
                       (status, acc['loyaltyAccountID']))

    def view_loyalty_details(self, customer_id: int) -> dict:
        """Return current balance, order history, and available rewards."""
        return {'account': self.retrieve_customer_account(customer_id),
                'transactions': self.transaction_history(customer_id),
                'rewards': self.display_available_rewards(customer_id)}

    def transaction_history(self, customer_id: int) -> list[dict]:
        with closing(connect(self.db_path)) as db:
            account = _account(db, customer_id)
            return [dict(r) for r in db.execute('''SELECT t.loyaltyTransactionID,t.orderID,t.createdAt,
                   t.loyaltyTransactionID AS transactionID,t.publicUUID,t.transactionDate,
                   t.type,t.pointsChange,t.pointsChange AS points,
                   t.purchaseAmount,t.eligibleAmount,t.discountAmount,t.finalAmount,
                   t.pointsEarned,t.pointsRedeemed,t.balanceAfter,r.name AS rewardName
                   FROM LoyaltyTransaction t LEFT JOIN Reward r ON r.rewardID=t.rewardID
                   WHERE t.loyaltyAccountID=? ORDER BY t.loyaltyTransactionID DESC''',
                   (account['loyaltyAccountID'],))]

    def transaction_model(self, loyalty_transaction_id: int) -> LoyaltyTransaction:
        """Retrieve the loyalty transaction for a posted purchase.

        Service callers are responsible for authenticating access to records;
        the interactive CLI already restricts customer history to self.
        """
        with closing(connect(self.db_path)) as db:
            row = db.execute('''SELECT * FROM LoyaltyTransaction WHERE loyaltyTransactionID=?''',
                             (_ident(loyalty_transaction_id, 'Loyalty transaction ID'),)).fetchone()
            if row is None:
                raise LoyaltyError('Loyalty transaction not found.')
            return LoyaltyTransaction.create(
                accountID=row['loyaltyAccountID'], orderID=row['orderID'],
                employeeUserID=row['employeeUserID'],
                purchaseAmount=Decimal(str(row['purchaseAmount'])),
                eligibleAmount=Decimal(str(row['eligibleAmount'])),
                discountAmount=Decimal(str(row['discountAmount'])),
                finalAmount=Decimal(str(row['finalAmount'])),
                pointsEarned=row['pointsEarned'], pointsRedeemed=row['pointsRedeemed'],
                balanceAfter=row['balanceAfter'], rewardID=row['rewardID'],
                transactionID=row['loyaltyTransactionID'],
                transactionDate=row['transactionDate'], publicUUID=row['publicUUID'])

    def redemption_model(self, loyalty_transaction_id: int) -> Redemption | None:
        """Retrieve the optional Redemption (None means an earning-only sale)."""
        with closing(connect(self.db_path)) as db:
            row = db.execute('''SELECT * FROM Redemption WHERE loyaltyTransactionID=?''',
                             (_ident(loyalty_transaction_id, 'Loyalty transaction ID'),)).fetchone()
            if row is None:
                return None
            return Redemption(
                redemptionID=row['redemptionID'], transactionID=row['loyaltyTransactionID'],
                rewardID=row['rewardID'], pointsUsed=row['pointsUsed'],
                discountAmount=Decimal(str(row['discountAmount'])),
                status=row['status'], redemptionDate=row['redemptionDate'],
                publicUUID=row['publicUUID'])

    def ensure_sample_rewards(self) -> int:
        """Create the recommended CAD rewards and update untouched legacy examples.

        Safe to call when any role opens Loyalty. A reward matching the previous
        sample name, price, discount and active status is migrated in place to
        the new sample points cost, retaining its ID and redemption history.
        Owner-customized prices and deactivated rewards are not modified.
        NOTE: a custom reward identical to the old defaults cannot be reliably
        distinguished from a seeded one; it is also eligible for migration.
        No user, profile, or loyalty account is created. Inserts and migrations
        commit (or roll back) together. Returns *new* rows, not migrated rows.
        """
        created = 0
        with transaction(self.db_path) as db:
            for name, points_cost, discount in SAMPLE_REWARDS:
                exists = db.execute('SELECT rewardID,pointsCost,discountAmount,isActive FROM Reward WHERE name=? COLLATE NOCASE',
                                    (name,)).fetchone()
                if exists:
                    # Upgrade only pristine active examples from the old ZIP.
                    old_points = LEGACY_SAMPLE_REWARD_COSTS[name]
                    if (exists['isActive'] == 1 and exists['pointsCost'] == old_points
                            and Decimal(str(exists['discountAmount'])) == Decimal(discount)):
                        db.execute('UPDATE Reward SET pointsCost=? WHERE rewardID=?',
                                   (points_cost, exists['rewardID']))
                    continue
                db.execute('INSERT INTO Reward(name,pointsCost,discountAmount,publicUUID) VALUES(?,?,?,?)',
                           (name, points_cost, float(_money(discount, 'Discount')),
                            str(uuid4())))
                created += 1
        return created

    def display_available_rewards(self, customer_id: int) -> list[dict]:
        balance = self.retrieve_customer_account(customer_id)['pointsBalance']
        return [{**r, 'affordable': balance >= r['pointsCost']} for r in self.rewards()]

    def rewards(self, *, active_only: bool = True) -> list[dict]:
        with closing(connect(self.db_path)) as db:
            return [dict(row) for row in db.execute('''SELECT rewardID,name,pointsCost,
                             pointsCost AS pointsRequired,pointsCost AS requiredPoints,
                             isActive AS available,publicUUID,discountAmount,isActive
                             FROM Reward WHERE (?=0 OR isActive=1) ORDER BY pointsCost,rewardID''',
                             (int(active_only),))]

    def reward_model(self, reward_id: int) -> Reward:
        """Retrieve a Reward with availability and eligibility methods."""
        with closing(connect(self.db_path)) as db:
            row = db.execute('''SELECT rewardID,name,pointsCost,isActive,discountAmount,publicUUID
                                FROM Reward WHERE rewardID=?''',
                             (_ident(reward_id, 'Reward ID'),)).fetchone()
            if row is None:
                raise LoyaltyError('Reward not found.')
            return _reward_model(row)

    def create_reward(self, owner_id: int, name: str, points_cost: int,
                      discount_amount: object) -> int:
        name = name.strip() if isinstance(name, str) else ''
        if not name or len(name) > 100:
            raise LoyaltyError('Reward name must contain 1–100 characters.')
        points_cost = _ident(points_cost, 'Points cost')
        discount_amount = _money(discount_amount, 'Discount', zero_ok=False)
        with transaction(self.db_path) as db:
            actor = db.execute('''SELECT role,accountActive,passwordHash FROM "User"
                                  WHERE userID=?''', (_ident(owner_id, 'Owner ID'),)).fetchone()
            if not actor or actor['role'] != 'Owner' or not actor['accountActive'] or not actor['passwordHash']:
                raise LoyaltyError('Only an active Owner can configure rewards.')
            try:
                return db.execute('''INSERT INTO Reward(name,pointsCost,discountAmount,publicUUID)
                                     VALUES(?,?,?,?)''',
                                  (name, points_cost, float(discount_amount), str(uuid4()))).lastrowid
            except sqlite3.IntegrityError as exc:
                raise LoyaltyError('Reward name already exists.') from exc

    def set_reward_active(self, owner_id: int, reward_id: int, active: bool) -> None:
        if not isinstance(active, bool):
            raise LoyaltyError('Active must be a boolean.')
        with transaction(self.db_path) as db:
            actor = db.execute('''SELECT role,accountActive,passwordHash FROM "User" WHERE userID=?''',
                               (_ident(owner_id, 'Owner ID'),)).fetchone()
            if not actor or actor['role'] != 'Owner' or not actor['accountActive'] or not actor['passwordHash']:
                raise LoyaltyError('Only an active Owner can configure rewards.')
            if db.execute('UPDATE Reward SET isActive=? WHERE rewardID=?',
                          (int(active), _ident(reward_id, 'Reward ID'))).rowcount != 1:
                raise LoyaltyError('Reward not found.')

    # 6g Calculate Points Earned. Rate is a documented demo assumption.
    def calculate_points_earned(self, eligible_paid_amount: object) -> int:
        amount = _money(eligible_paid_amount, 'Eligible paid amount')
        return int((amount * self.points_per_dollar).to_integral_value(rounding=ROUND_DOWN))

    def _quote(self, db: sqlite3.Connection, customer_id: int, order_id: int,
               reward_id: int | None, eligible_amount: object | None,
               *, require_completed: bool = True) -> LoyaltyQuote:
        account = _account_model(_account(db, customer_id))
        if account.status != 'Active':
            raise LoyaltyError('This loyalty account is suspended. Contact the Owner.')
        order = db.execute('''SELECT orderID,totalAmount,status,customerID FROM "Order"
                              WHERE orderID=?''', (_ident(order_id, 'Order ID'),)).fetchone()
        if not order:
            raise LoyaltyError('Order not found.')
        if order['status'] != 'Completed' and (require_completed or order['status'] != 'Pending'):
            raise LoyaltyError('The order must be Pending for a preview, or Completed to record loyalty.')
        if order['customerID'] is not None and order['customerID'] != customer_id:
            raise LoyaltyError('That order is already assigned to another customer.')
        if db.execute('SELECT 1 FROM LoyaltyTransaction WHERE orderID=?', (order_id,)).fetchone():
            raise DuplicatePurchaseError('This order already has a loyalty transaction.')
        purchase = _money(order['totalAmount'], 'Order total')
        eligible = purchase if eligible_amount is None else _money(eligible_amount, 'Eligible purchase amount')
        if eligible > purchase:
            raise LoyaltyError('Eligible amount cannot exceed the completed order total.')
        discount = Decimal('0.00')
        point_cost = 0
        if reward_id is not None:
            reward = db.execute('''SELECT rewardID,name,pointsCost,discountAmount,isActive,publicUUID
                                 FROM Reward WHERE rewardID=?''',
                                (_ident(reward_id, 'Reward ID'),)).fetchone()
            if not reward or not _reward_model(reward).isAvailable():
                raise LoyaltyError('Reward is unavailable. Choose another reward or save points.')
            item = _reward_model(reward)
            point_cost = item.pointsRequired
            if not item.isEligible(account.currentPoints):
                raise InsufficientPointsError('Not enough points for this reward. Choose another or save points.')
            discount = _money(item.discountAmount, 'Reward discount')
            if discount > purchase:
                raise LoyaltyError('Reward discount exceeds this order total. Choose a smaller reward.')
        # Points are earned on eligible dollars actually paid after the reward.
        # The POS will eventually supply exact eligible lines and paid amount.
        earned = self.calculate_points_earned(max(Decimal('0.00'), eligible - discount))
        previous_points = account.currentPoints
        if point_cost and not account.redeemPoints(point_cost):
            raise InsufficientPointsError('Not enough points for this reward.')
        account.addPoints(earned)
        return LoyaltyQuote(customer_id, order_id, purchase, eligible, discount,
                            purchase - discount, reward_id, earned, point_cost,
                            previous_points, account.currentPoints)

    def preview_purchase(self, customer_id: int, order_id: int, *,
                         reward_id: int | None = None,
                         eligible_amount: object | None = None) -> LoyaltyQuote:
        """Read-only choice stage for Pending or Completed orders; no points change."""
        with closing(connect(self.db_path)) as db:
            return self._quote(db, customer_id, order_id, reward_id, eligible_amount,
                               require_completed=False)

    # 6e Process Eligible Purchase / 6d Redeem Reward / 6h Update Points Balance.
    def process_eligible_purchase(self, employee_id: int, customer_id: int, order_id: int,
                                  *, reward_id: int | None = None,
                                  eligible_amount: object | None = None) -> dict:
        """Atomic loyalty commit after employee/customer confirm; never touches stock.

        Separate transaction and redemption tables preserve reporting/audit trails.
        Entire operation rolls back on DB failures and on insufficient points.
        """
        with transaction(self.db_path) as db:
            _active_employee(db, employee_id)
            return self._record_purchase_in_transaction(db, employee_id, customer_id,
                                                        order_id, reward_id, eligible_amount)

    def _record_purchase_in_transaction(self, db: sqlite3.Connection, employee_id: int,
                                        customer_id: int, order_id: int,
                                        reward_id: int | None, eligible_amount: object | None) -> dict:
        quote = self._quote(db, customer_id, order_id, reward_id, eligible_amount)
        account = _account(db, customer_id)
        # Link an order to the customer without altering order pricing/status.
        db.execute('UPDATE "Order" SET customerID=? WHERE orderID=? AND customerID IS NULL',
                   (customer_id, quote.order_id))
        if db.execute('''UPDATE LoyaltyAccount SET pointsBalance=?
                             WHERE loyaltyAccountID=?''',
                      (quote.new_balance, account['loyaltyAccountID'])).rowcount != 1:
            raise LoyaltyError('Unable to update loyalty balance.')
        entry = LoyaltyTransaction.create(
            accountID=account['loyaltyAccountID'], orderID=quote.order_id,
            employeeUserID=employee_id, purchaseAmount=quote.purchase_amount,
            eligibleAmount=quote.eligible_amount, discountAmount=quote.discount_amount,
            finalAmount=quote.final_amount, pointsEarned=quote.points_earned,
            pointsRedeemed=quote.points_redeemed, balanceAfter=quote.new_balance,
            rewardID=quote.reward_id)
        tx_id = entry.record(db)
        if quote.reward_id is not None:
            redemption = Redemption(transactionID=tx_id, rewardID=quote.reward_id,
                                    pointsUsed=quote.points_redeemed,
                                    discountAmount=quote.discount_amount)
            redemption.confirmRedemption()
            redemption.record(db)
        # This also updates an existing gross sale if loyalty was recorded after
        # order completion. It never creates a second sale for the same Order ID.
        order_date = db.execute('SELECT orderDate FROM "Order" WHERE orderID=?',
                                (order_id,)).fetchone()['orderDate']
        sale_id = post_source_transaction(
            db, kind='Sale', when=order_date or date.today().isoformat(),
            description=f'Completed customer order #{order_id}',
            reference=f'ORDER-{order_id}', amount=quote.final_amount,
            source_type='Order', source_id=order_id, update_existing=True,
        )
        return {'loyaltyTransactionID': tx_id, 'customerID': customer_id,
                'orderID': order_id, 'pointsEarned': quote.points_earned,
                'pointsRedeemed': quote.points_redeemed, 'balanceAfter': quote.new_balance,
                'discountAmount': float(quote.discount_amount),
                'finalAmount': float(quote.final_amount), 'eligibleAmount': float(quote.eligible_amount),
                'rewardID': quote.reward_id, 'accounting_transaction_id': sale_id}

    def complete_order_with_loyalty(self, employee_id: int, customer_id: int, order_id: int,
                                    *, reward_id: int | None = None) -> dict:
        """Deduct stock, complete the order, and post loyalty in ONE transaction."""
        inventory = InventoryService(self.db_path)
        with transaction(self.db_path) as db:
            _active_employee(db, employee_id)
            order = db.execute('SELECT customerID,status FROM "Order" WHERE orderID=?',
                               (_ident(order_id, 'Order ID'),)).fetchone()
            if not order or order['status'] != 'Pending':
                raise LoyaltyError('Only an existing Pending order can be completed.')
            if order['customerID'] != _ident(customer_id, 'Customer ID'):
                raise LoyaltyError('Assign this Customer ID to the Pending order before completing it.')
            # Validate the loyalty choice before inventory is touched.
            self._quote(db, customer_id, order_id, reward_id, None, require_completed=False)
            completed = inventory._complete_order_in_transaction(db, order_id, employee_id)
            recorded = self._record_purchase_in_transaction(db, employee_id, customer_id,
                                                             order_id, reward_id, None)
            return {**completed, **recorded}

    def redeem_reward(self, employee_id: int, customer_id: int, order_id: int,
                      reward_id: int, *, eligible_amount: object | None = None) -> dict:
        """6d Redeem Reward: confirm the purchase with one selected reward.

        Delegates to the same atomic transaction path as earning-only orders.
        Redemption cannot be posted independently of a completed purchase.
        """
        if reward_id is None:
            raise LoyaltyError('Choose a reward to redeem.')
        return self.process_eligible_purchase(employee_id, customer_id, order_id,
                                              reward_id=reward_id,
                                              eligible_amount=eligible_amount)

    # 6f Provide Transaction Confirmation / 6i Generate Receipt.
    def generate_receipt(self, loyalty_transaction_id: int) -> str:
        """Text-only loyalty confirmation; NOT a proof of payment/tax receipt."""
        with closing(connect(self.db_path)) as db:
            result = db.execute('''SELECT t.*,u.name,r.name AS rewardName
                    FROM LoyaltyTransaction t JOIN LoyaltyAccount a
                    ON t.loyaltyAccountID=a.loyaltyAccountID
                    JOIN Customer c ON c.customerID=a.customerID
                    JOIN "User" u ON u.userID=c.userID
                    LEFT JOIN Reward r ON r.rewardID=t.rewardID
                    WHERE t.loyaltyTransactionID=?''',
                (_ident(loyalty_transaction_id, 'Loyalty transaction ID'),)).fetchone()
            if not result:
                raise LoyaltyError('Loyalty transaction not found.')
            return ('THE ONIGIRI SHOP | LOYALTY CONFIRMATION\n'
                    f'Order #{result["orderID"]} | Loyalty #{result["loyaltyTransactionID"]}\n'
                    f'Customer: {result["name"]}\n'
                    f'Order amount: ${result["purchaseAmount"]:.2f} CAD\n'
                    f'Eligible amount: ${result["eligibleAmount"]:.2f} CAD\n'
                    f'Reward: {result["rewardName"] or "None"}\n'
                    f'Reward discount: ${result["discountAmount"]:.2f} CAD\n'
                    f'Amount after reward (informational): ${result["finalAmount"]:.2f} CAD\n'
                    f'Points earned: {result["pointsEarned"]}\n'
                    f'Points redeemed: {result["pointsRedeemed"]}\n'
                    f'New points balance: {result["balanceAfter"]}\n'
                    'Loyalty record only. Payment is handled separately.')
