"""Loyalty domain objects shared by the loyalty service.

Persisted integer primary keys stay intact for the shop's existing database and
foreign keys; publicUUID is a stable additional external identifier. The classes
expose compatibility aliases without duplicating
points columns in storage. Point mutations are in-memory business calculations:
only LoyaltyService can commit them, with purchase validation and staff approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import sqlite3


def _points(value: int, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if allow_zero else 1):
        raise ValueError('Points must be a nonnegative whole number.' if allow_zero else
                         'Points must be a positive whole number.')
    return value


@dataclass
class LoyaltyAccount:
    """One optional account per Customer; owns many loyalty transactions."""
    accountID: int
    customerID: int
    currentPoints: int = 0
    status: str = 'Active'
    publicUUID: str | None = None

    def __post_init__(self) -> None:
        _points(self.currentPoints, allow_zero=True)
        if self.status not in ('Active', 'Suspended'):
            raise ValueError('Invalid loyalty account status.')

    @property
    def pointsBalance(self) -> int:
        return self.currentPoints

    @property
    def accountId(self) -> str | int:
        return self.publicUUID or self.accountID

    def addPoints(self, points: int) -> None:
        if self.status != 'Active':
            raise ValueError('This loyalty account is suspended.')
        self.currentPoints += _points(points, allow_zero=True)

    def deductPoints(self, points: int) -> bool:
        if self.status != 'Active':
            raise ValueError('This loyalty account is suspended.')
        points = _points(points)
        if self.currentPoints < points:
            return False
        self.currentPoints -= points
        return True

    def redeemPoints(self, points: int) -> bool:
        """Detailed-diagram synonym for merged-diagram deductPoints()."""
        return self.deductPoints(points)


@dataclass(frozen=True)
class Reward:
    """Available reward. Eligibility is determined from point balance."""
    rewardID: int
    name: str
    pointsRequired: int
    available: bool
    discountAmount: Decimal
    publicUUID: str | None = None

    @property
    def requiredPoints(self) -> int:
        return self.pointsRequired

    @property
    def pointsCost(self) -> int:
        return self.pointsRequired

    @property
    def isActive(self) -> bool:
        return self.available

    @property
    def rewardId(self) -> str | int:
        return self.publicUUID or self.rewardID

    def isAvailable(self) -> bool:
        return self.available

    def isEligible(self, balance: int) -> bool:
        return self.isAvailable() and _points(balance, allow_zero=True) >= self.pointsRequired


@dataclass
class LoyaltyTransaction:
    """A purchase-linked points ledger entry, optionally associated with a Reward.

    A transaction with no reward may still earn points. The record() method is
    meant only for LoyaltyService's already-authorized, atomic DB transaction.
    """
    accountID: int
    orderID: int
    employeeUserID: int
    purchaseAmount: Decimal
    eligibleAmount: Decimal
    discountAmount: Decimal
    finalAmount: Decimal
    pointsEarned: int
    pointsRedeemed: int
    balanceAfter: int
    rewardID: int | None = None
    transactionID: int | None = None
    transactionDate: str | None = None
    publicUUID: str | None = None

    @classmethod
    def create(cls, **fields: object) -> 'LoyaltyTransaction':
        """Merged-diagram create(): construct an unsaved transaction."""
        tx = cls(**fields)
        _points(tx.pointsEarned, allow_zero=True)
        _points(tx.pointsRedeemed, allow_zero=True)
        _points(tx.balanceAfter, allow_zero=True)
        return tx

    @property
    def points(self) -> int:
        return self.pointsEarned - self.pointsRedeemed

    @property
    def pointsChange(self) -> int:
        return self.points

    @property
    def type(self) -> str:
        if self.pointsEarned and self.pointsRedeemed:
            return 'EarnAndRedeem'
        if self.pointsRedeemed:
            return 'Redeem'
        if self.pointsEarned:
            return 'Earn'
        return 'NoPoints'

    @property
    def transactionId(self) -> str | int | None:
        return self.publicUUID or self.transactionID

    def record(self, db: sqlite3.Connection) -> int:
        """Diagram record(): insert into the existing shared SQLite transaction."""
        from uuid import uuid4
        if self.transactionID is not None:
            raise ValueError('This loyalty transaction was already recorded.')
        public_uuid = self.publicUUID or str(uuid4())
        cur = db.execute('''INSERT INTO LoyaltyTransaction(
            loyaltyAccountID,orderID,employeeUserID,purchaseAmount,eligibleAmount,
            discountAmount,finalAmount,pointsEarned,pointsRedeemed,balanceAfter,rewardID,
            pointsChange,type,transactionDate,publicUUID)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,?)''',
            (self.accountID, self.orderID, self.employeeUserID,
             float(self.purchaseAmount), float(self.eligibleAmount),
             float(self.discountAmount), float(self.finalAmount),
             self.pointsEarned, self.pointsRedeemed, self.balanceAfter, self.rewardID,
             self.pointsChange, self.type, public_uuid))
        self.transactionID = cur.lastrowid
        self.publicUUID = public_uuid
        self.transactionDate = db.execute('''SELECT transactionDate FROM LoyaltyTransaction
                                             WHERE loyaltyTransactionID=?''',
                                          (self.transactionID,)).fetchone()['transactionDate']
        return self.transactionID


@dataclass
class Redemption:
    """Optional reward redemption associated with exactly one loyalty transaction.

    A confirmed redemption cannot be cancelled by changing its status alone,
    because that would leave the account points ledger inconsistent. Cancelling
    a pending (not yet posted) redemption is allowed. Reversals of confirmed
    transactions need a future POS refund/reversal use case.
    """
    transactionID: int
    rewardID: int
    pointsUsed: int
    discountAmount: Decimal
    redemptionID: int | None = None
    redemptionDate: str | None = None
    status: str = 'Pending'
    publicUUID: str | None = None

    def confirmRedemption(self) -> None:
        if self.status != 'Pending':
            raise ValueError('Only a pending redemption can be confirmed.')
        _points(self.pointsUsed)
        self.status = 'Confirmed'

    def cancelRedemption(self) -> None:
        if self.status != 'Pending':
            raise ValueError('A confirmed redemption cannot be cancelled without reversing its ledger entry.')
        self.status = 'Cancelled'

    def record(self, db: sqlite3.Connection) -> int:
        from uuid import uuid4
        if self.status != 'Confirmed' or self.redemptionID is not None:
            raise ValueError('Only a new confirmed redemption may be recorded.')
        public_uuid = self.publicUUID or str(uuid4())
        cur = db.execute('''INSERT INTO Redemption(
            loyaltyTransactionID,rewardID,pointsUsed,discountAmount,status,
            redemptionDate,publicUUID)
            VALUES(?,?,?,?,?,CURRENT_TIMESTAMP,?)''',
            (self.transactionID, self.rewardID, self.pointsUsed,
             float(self.discountAmount), self.status, public_uuid))
        self.redemptionID = cur.lastrowid
        self.publicUUID = public_uuid
        self.redemptionDate = db.execute('''SELECT redemptionDate FROM Redemption
                                            WHERE redemptionID=?''',
                                         (self.redemptionID,)).fetchone()['redemptionDate']
        return self.redemptionID
