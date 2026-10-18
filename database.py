
import sqlite3

# Connect to SQLite database
# Creates the file automatically if it does not exist
connection = sqlite3.connect("btm495.db")
cursor = connection.cursor()

# Enable foreign key support
cursor.execute("PRAGMA foreign_keys = ON")

# USER MANAGEMENT

cursor.execute("""
CREATE TABLE IF NOT EXISTS User (
    userID INTEGER PRIMARY KEY,
    name TEXT,
    email TEXT,
    username TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS Profile (
    profileID TEXT PRIMARY KEY,
    phoneNumber TEXT,
    dateOfBirth TEXT,
    userID INTEGER,
    FOREIGN KEY (userID) REFERENCES User(userID)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS Customer (
    customerID INTEGER PRIMARY KEY,
    userID INTEGER,
    FOREIGN KEY (userID) REFERENCES User(userID)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS Employee (
    employeeID INTEGER PRIMARY KEY,
    userID INTEGER,
    hourlyRate REAL,
    isActive INTEGER,
    FOREIGN KEY (userID) REFERENCES User(userID)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS Owner (
    ownerID INTEGER PRIMARY KEY,
    userID INTEGER,
    FOREIGN KEY (userID) REFERENCES User(userID)
)
""")

# CUSTOMER LOYALTY

cursor.execute("""
CREATE TABLE IF NOT EXISTS LoyaltyAccount (
    accountID INTEGER PRIMARY KEY,
    currentPoints INTEGER,
    joinDate TEXT,
    status TEXT,
    customerID INTEGER,
    FOREIGN KEY (customerID) REFERENCES Customer(customerID)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS LoyaltyTransaction (
    transactionID INTEGER PRIMARY KEY,
    points INTEGER,
    type TEXT,
    transactionDate TEXT,
    accountID INTEGER,
    FOREIGN KEY (accountID) REFERENCES LoyaltyAccount(accountID)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS Reward (
    rewardID INTEGER PRIMARY KEY,
    name TEXT,
    pointsRequired INTEGER,
    value REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS Redemption (
    redemptionID INTEGER PRIMARY KEY,
    pointsUsed INTEGER,
    redemptionDate TEXT,
    status TEXT,
    accountID INTEGER,
    rewardID INTEGER,
    FOREIGN KEY (accountID) REFERENCES LoyaltyAccount(accountID),
    FOREIGN KEY (rewardID) REFERENCES Reward(rewardID)
)
""")

# ORDERS AND FEEDBACK

cursor.execute("""
CREATE TABLE IF NOT EXISTS "Order" (
    orderID INTEGER PRIMARY KEY,
    orderDate TEXT,
    totalAmount REAL,
    status TEXT,
    customerID INTEGER,
    FOREIGN KEY (customerID) REFERENCES Customer(customerID)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS Feedback (
    feedbackID INTEGER PRIMARY KEY,
    feedbackText TEXT,
    submissionDate TEXT,
    status TEXT,
    customerID INTEGER,
    FOREIGN KEY (customerID) REFERENCES Customer(customerID)
)
""")

# PAYROLL

cursor.execute("""
CREATE TABLE IF NOT EXISTS Payroll (
    payrollID INTEGER PRIMARY KEY,
    periodStart TEXT,
    periodEnd TEXT,
    status TEXT,
    ownerID INTEGER,
    FOREIGN KEY (ownerID) REFERENCES Owner(ownerID)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS PayrollEntry (
    entryID INTEGER PRIMARY KEY,
    regularHours REAL,
    overtimeHours REAL,
    grossPay REAL,
    netPay REAL,
    payrollID INTEGER,
    employeeID INTEGER,
    FOREIGN KEY (payrollID) REFERENCES Payroll(payrollID),
    FOREIGN KEY (employeeID) REFERENCES Employee(employeeID)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS Deduction (
    deductionID INTEGER PRIMARY KEY,
    type TEXT,
    rate REAL,
    amount REAL,
    entryID INTEGER,
    FOREIGN KEY (entryID) REFERENCES PayrollEntry(entryID)
)
""")

# INVENTORY

cursor.execute("""
CREATE TABLE IF NOT EXISTS InventoryItem (
    ingredientID INTEGER PRIMARY KEY,
    ingredientName TEXT,
    quantityOnHand REAL,
    reorderLevel REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS InventoryAdjustment (
    adjustmentID INTEGER PRIMARY KEY,
    quantityChange REAL,
    reason TEXT,
    adjustmentDate TEXT,
    ingredientID INTEGER,
    FOREIGN KEY (ingredientID) REFERENCES InventoryItem(ingredientID)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS InventoryOrder (
    inventoryOrderID INTEGER PRIMARY KEY,
    orderDate TEXT,
    status TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS InventoryOrderLine (
    orderLineID INTEGER PRIMARY KEY,
    quantityOrdered REAL,
    inventoryOrderID INTEGER,
    ingredientID INTEGER,
    FOREIGN KEY (inventoryOrderID) REFERENCES InventoryOrder(inventoryOrderID),
    FOREIGN KEY (ingredientID) REFERENCES InventoryItem(ingredientID)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS LowStockAlert (
    alertID INTEGER PRIMARY KEY,
    createdAt TEXT,
    status TEXT,
    ingredientID INTEGER,
    FOREIGN KEY (ingredientID) REFERENCES InventoryItem(ingredientID)
)
""")

# BUSINESS ANALYTICS

cursor.execute("""
CREATE TABLE IF NOT EXISTS BusinessData (
    dataID INTEGER PRIMARY KEY,
    date TEXT,
    dataType TEXT,
    value REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS TrendPrediction (
    predictionID INTEGER PRIMARY KEY,
    trendType TEXT,
    predictedValue REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS TrendPredictingDashboard (
    dashboardID INTEGER PRIMARY KEY,
    selectedType TEXT
)
""")

# ACCOUNTING

cursor.execute("""
CREATE TABLE IF NOT EXISTS AccountingTransaction (
    transactionID INTEGER PRIMARY KEY,
    transactionType TEXT,
    amount REAL,
    transactionDate TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS AccountingLedger (
    ledgerID INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS AccountingSummary (
    summaryID INTEGER PRIMARY KEY,
    totalSales REAL,
    totalPurchases REAL,
    totalExpenses REAL,
    balance REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS AccountingDiscrepancy (
    discrepancyID INTEGER PRIMARY KEY,
    description TEXT,
    amount REAL,
    status TEXT,
    transactionID INTEGER,
    FOREIGN KEY (transactionID)
        REFERENCES AccountingTransaction(transactionID)
)
""")

# SAVE CHANGES
connection.commit()

# CHECK TABLES
cursor.execute("""
SELECT name FROM sqlite_master
WHERE type = 'table'
ORDER BY name
""")

tables = cursor.fetchall()

print("SQLite database created successfully!")
print("Number of tables:", len(tables))

for table in tables:
    print("-", table[0])

connection.close()
