"""Vary newly imported fictional event times without changing business dates."""
from datetime import datetime, timedelta
from random import SystemRandom


# Calendar-only fields (birthdays and payroll pay dates) are not event times.
EVENTS = {
    'Order': ('orderDate',), 'InventoryOrder': ('orderDate',),
    'InventoryTransaction': ('transactionDate',),
    'InventoryAdjustment': ('adjustmentDate',), 'LowStockAlert': ('createdAt',),
    'AccountingTransaction': ('date', 'transactionDate'),
    'LoyaltyAccount': ('joinedAt',),
    'LoyaltyTransaction': ('createdAt', 'transactionDate'),
    'Redemption': ('redemptionDate',), 'Feedback': ('submissionDate',),
    'Payroll': (),
}
UTC_FIELDS = {'createdAt', 'joinedAt'}


def snapshot_demo_events(db):
    """Remember boundaries so existing restaurant and sample rows stay untouched."""
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {table:db.execute(f'SELECT COALESCE(MAX(rowid),0) FROM "{table}"').fetchone()[0]
            for table in EVENTS if table in tables}


def randomize_new_demo_events(db, before):
    """Run inside the import transaction (or the unpublished complete-demo stage).

    Related order consumption, loyalty and Sales share the completion time.
    Keep the original date prefix so daily reports and forecasts do not change.
    """
    random=SystemRandom()
    completion={};deliveries={};movements=[];purchases={}
    for table,fields in EVENTS.items():
        if table not in before:continue
        columns={r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
        fields=[field for field in fields if field in columns]
        for row in db.execute(f'SELECT rowid AS _demo_rowid,* FROM "{table}" WHERE rowid>? ORDER BY rowid',
                              (before[table],)).fetchall():
            values={};row=dict(row)
            seconds=random.randrange(9*3600,17*3600)
            if table=='Payroll':
                stamp=None
                if row.get('accountingTransactionID'):
                    date_column=next(c for c in EVENTS['AccountingTransaction'] if c in
                        {r[1] for r in db.execute('PRAGMA table_info(AccountingTransaction)')})
                    linked=db.execute(f'SELECT "{date_column}" FROM AccountingTransaction WHERE transactionID=?',
                                      (row['accountingTransactionID'],)).fetchone()
                    if linked:stamp=linked[0]
                pay_time=str(stamp)[11:19] if stamp and len(str(stamp))>=19 else (datetime(2000,1,1)+timedelta(seconds=seconds)).strftime('%H:%M:%S')
                db.execute('UPDATE Payroll SET payTime=? WHERE rowid=?',(pay_time,row['_demo_rowid']))
                continue
            for field in fields:
                raw=row[field]
                if not raw:continue
                try:day=datetime.fromisoformat(str(raw)[:10])
                except ValueError:continue
                local=day+timedelta(seconds=seconds)
                if table=='Order':
                    completion[row['orderID']]=local+timedelta(minutes=random.randrange(5,25))
                elif table=='InventoryOrder':purchases[row['inventoryOrderID']]=local
                elif table=='InventoryTransaction':
                    local=completion.get(row.get('customerOrderID'),
                        purchases.get(row.get('inventoryOrderID'),local)+timedelta(minutes=30))
                elif table=='AccountingTransaction':
                    if row.get('sourceType')=='Order':local=completion.get(row.get('sourceID'),local)
                    elif row.get('sourceType')=='Delivery':local=deliveries.get(row.get('sourceID'),local)
                elif table=='LoyaltyTransaction':local=completion.get(row.get('orderID'),local)
                elif table=='Redemption':
                    linked=db.execute('SELECT transactionDate FROM LoyaltyTransaction WHERE loyaltyTransactionID=?',
                                      (row.get('loyaltyTransactionID'),)).fetchone()
                    if linked and linked[0]:local=datetime.fromisoformat(linked[0])
                # Use the same event instant for the UTC audit column and local business column.
                stored=local+timedelta(hours=5) if field in UTC_FIELDS else local
                values[field]=stored.isoformat(timespec='seconds')
            if values:
                db.execute(f'UPDATE "{table}" SET '+','.join(f'"{field}"=?' for field in values)+
                           ' WHERE rowid=?',(*values.values(),row['_demo_rowid']))
                if table=='InventoryTransaction':
                    stamp=values['transactionDate'];deliveries[row['transactionID']]=datetime.fromisoformat(stamp)
                    movements.append(stamp)
        if table=='InventoryAdjustment':
            ids=[r[0] for r in db.execute('SELECT rowid FROM InventoryAdjustment WHERE rowid>? ORDER BY rowid',
                                         (before[table],))]
            if len(ids)==len(movements):
                db.executemany('UPDATE InventoryAdjustment SET adjustmentDate=? WHERE rowid=?',zip(movements,ids))
