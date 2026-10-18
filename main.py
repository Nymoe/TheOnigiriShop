import database
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# ==========================================
# 1. USER MANAGEMENT
# ==========================================

@dataclass
class Profile:
    profileID: str
    phoneNumber: str
    dateOfBirth: date

    def validateChanges(self) -> bool:
        return bool(self.profileID and self.phoneNumber)

    def updateProfile(self) -> None:
        pass


@dataclass
class User:
    userID: int
    name: str
    email: str
    username: str
    profile: Optional[Profile] = None

    def viewProfile(self) -> Optional[Profile]:
        return self.profile


@dataclass
class Customer(User):
    customerID: int = 0

    def submitFeedback(self, text: str):
        return Feedback(
            feedbackID=0,
            feedbackText=text,
            submissionDate=date.today(),
            status="Submitted"
        )

    def viewSubmittedFeedback(self) -> list:
        return []

    def viewPoints(self) -> int:
        return 0


@dataclass
class Employee(User):
    employeeID: int = 0
    hourlyRate: float = 0.0
    isActive: bool = True

    def reviewFeedback(self, id: int) -> None:
        pass

    def processOrder(self, id: int) -> None:
        pass


@dataclass
class Owner(User):
    ownerID: int = 0

    def openPayroll(self, start: date, end: date):
        return Payroll(
            payrollID=0,
            periodStart=start,
            periodEnd=end,
            status="Open"
        )

    def reviewFeedback(self, id: int) -> None:
        pass


# ==========================================
# 2. CUSTOMER LOYALTY SYSTEM
# ==========================================

@dataclass
class LoyaltyAccount:
    accountID: int
    currentPoints: int
    joinDate: date
    status: str

    def addPoints(self, points: int) -> None:
        if points < 0:
            raise ValueError("Points must be nonnegative")
        self.currentPoints += points

    def deductPoints(self, points: int) -> None:
        if points < 0 or points > self.currentPoints:
            raise ValueError("Invalid points")
        self.currentPoints -= points


@dataclass
class LoyaltyTransaction:
    transactionID: int
    points: int
    type: str
    transactionDate: date

    def create(self) -> None:
        pass

    def getDetails(self) -> str:
        return f"{self.type}: {self.points} points on {self.transactionDate}"


@dataclass
class Reward:
    rewardID: int
    name: str
    pointsRequired: int
    value: float

    def isAvailable(self) -> bool:
        return self.pointsRequired >= 0

    def getDetails(self) -> str:
        return f"{self.name} ({self.pointsRequired} points)"


@dataclass
class Redemption:
    redemptionID: int
    pointsUsed: int
    redemptionDate: date
    status: str

    def confirmRedemption(self) -> None:
        self.status = "Confirmed"

    def cancelRedemption(self) -> None:
        self.status = "Cancelled"


# ==========================================
# 3. ORDERS AND FEEDBACK
# ==========================================

@dataclass
class Order:
    orderID: int
    orderDate: date
    totalAmount: float
    status: str

    def calculateTotal(self) -> float:
        return self.totalAmount

    def completeOrder(self) -> None:
        self.status = "Completed"


@dataclass
class Feedback:
    feedbackID: int
    feedbackText: str
    submissionDate: date
    status: str

    def validateFeedback(self) -> bool:
        return bool(self.feedbackText.strip())

    def storeFeedback(self) -> None:
        pass

    def getFeedback(self) -> str:
        return self.feedbackText

    def updateStatus(self, status: str) -> None:
        self.status = status


# ==========================================
# 4. PAYROLL MANAGEMENT
# ==========================================

@dataclass
class Deduction:
    type: str
    rate: float
    amount: float

    def calculate(self, grossPay: float) -> float:
        self.amount = grossPay * self.rate
        return self.amount


@dataclass
class PayrollEntry:
    regularHours: float
    overtimeHours: float
    grossPay: float
    netPay: float
    deductions: list[Deduction] = field(default_factory=list)

    def calculateGross(self, rate: float) -> float:
        self.grossPay = (
            self.regularHours * rate
            + self.overtimeHours * rate * 1.5
        )
        return self.grossPay

    def calculateNet(self) -> float:
        self.netPay = self.grossPay - sum(
            d.calculate(self.grossPay)
            for d in self.deductions
        )
        return self.netPay

    def generatePayStub(self) -> str:
        return f"Gross: {self.grossPay:.2f}; Net: {self.netPay:.2f}"


@dataclass
class Payroll:
    payrollID: int
    periodStart: date
    periodEnd: date
    status: str
    entries: list[PayrollEntry] = field(default_factory=list)

    def calculatePay(self) -> None:
        for entry in self.entries:
            entry.calculateNet()

    def approve(self) -> None:
        self.status = "Approved"

    def save(self) -> None:
        pass


# ==========================================
# 5. INVENTORY MANAGEMENT
# ==========================================

@dataclass
class InventoryItem:
    ingredientID: int
    ingredientName: str
    quantityOnHand: float
    reorderLevel: float

    def adjustQuantity(self, change: float) -> None:
        if self.quantityOnHand + change < 0:
            raise ValueError("Insufficient inventory")
        self.quantityOnHand += change

    def isBelowReorderLevel(self) -> bool:
        return self.quantityOnHand < self.reorderLevel


@dataclass
class InventoryAdjustment:
    adjustmentID: int
    quantityChange: float
    reason: str
    adjustmentDate: date

    def validateAdjustment(self) -> bool:
        return bool(self.reason.strip())

    def applyAdjustment(self) -> None:
        pass


@dataclass
class InventoryOrder:
    inventoryOrderID: int
    orderDate: date
    status: str

    def createOrder(self) -> None:
        self.status = "Created"

    def confirmOrder(self) -> None:
        self.status = "Confirmed"


@dataclass
class InventoryOrderLine:
    orderLineID: int
    quantityOrdered: float

    def updateQuantity(self, qty: float) -> None:
        if qty < 0:
            raise ValueError("Quantity must be nonnegative")
        self.quantityOrdered = qty


@dataclass
class LowStockAlert:
    alertID: int
    createdAt: date
    status: str

    def generateAlert(self) -> None:
        self.status = "Open"

    def markReviewed(self) -> None:
        self.status = "Reviewed"


# ==========================================
# 6. BUSINESS ANALYTICS
# ==========================================

@dataclass
class BusinessData:
    dataID: int
    date: date
    dataType: str
    value: float

    def retrieveData(self) -> None:
        pass


@dataclass
class TrendPrediction:
    predictionID: int
    trendType: str
    predictedValue: float

    def generateTrend(self) -> None:
        pass

    def generatePrediction(self) -> None:
        pass


@dataclass
class TrendPredictingDashboard:
    dashboardID: int
    selectedType: str

    def displayTrends(self) -> None:
        pass

    def displayPrediction(self) -> None:
        pass


# ==========================================
# 7. ACCOUNTING MANAGEMENT
# ==========================================

@dataclass
class AccountingTransaction:
    transactionID: int
    transactionType: str
    amount: float
    transactionDate: date

    def validateTransaction(self) -> bool:
        return bool(self.transactionType) and self.amount >= 0

    def updateTransaction(self) -> None:
        pass


@dataclass
class AccountingDiscrepancy:
    discrepancyID: int
    description: str
    amount: float
    status: str

    def flag(self) -> None:
        self.status = "Flagged"

    def resolve(self) -> None:
        self.status = "Resolved"


@dataclass
class AccountingSummary:
    totalSales: float
    totalPurchases: float
    totalExpenses: float
    balance: float

    def calculateSummary(self) -> None:
        self.balance = (
            self.totalSales
            - self.totalPurchases
            - self.totalExpenses
        )

    def displaySummary(self) -> None:
        print(f"Balance: {self.balance:.2f}")


@dataclass
class AccountingLedger:
    ledgerID: int
    transactions: list[AccountingTransaction] = field(default_factory=list)

    def addTransaction(self, t: AccountingTransaction) -> None:
        self.transactions.append(t)

    def reconcile(self) -> bool:
        return all(
            t.validateTransaction()
            for t in self.transactions
        )


# ==========================================
# 8. TEST THE PROTOTYPE
# ==========================================

if __name__ == "__main__":

    print("BTM 495 - Python Prototype")
    print("==========================")

    customer = Customer(
        userID=1,
        name="John Smith",
        email="john@example.com",
        username="johnsmith",
        customerID=101
    )

    print("Customer:", customer.name)

    loyalty = LoyaltyAccount(
        accountID=1,
        currentPoints=100,
        joinDate=date.today(),
        status="Active"
    )

    loyalty.addPoints(20)
    print("Loyalty points:", loyalty.currentPoints)

    order = Order(
        orderID=1,
        orderDate=date.today(),
        totalAmount=45.50,
        status="Pending"
    )

    order.completeOrder()
    print("Order status:", order.status)

    inventory = InventoryItem(
        ingredientID=1,
        ingredientName="Rice",
        quantityOnHand=5,
        reorderLevel=10
    )

    print("Low stock:", inventory.isBelowReorderLevel())

    dashboard = TrendPredictingDashboard(
        dashboardID=1,
        selectedType="Sales"
    )

    prediction = TrendPrediction(
        predictionID=1,
        trendType="Sales",
        predictedValue=140.0
    )

    print("Dashboard:", dashboard.selectedType)
    print("Predicted value:", prediction.predictedValue)

    print("==========================")
    print("Prototype executed successfully!")
