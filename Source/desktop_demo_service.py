"""Complete optional sample scenario built and checked before publishing it."""
from contextlib import closing
from datetime import date, timedelta
import hashlib
import math
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from inventory_db import connect, transaction
from inventory_service import InventoryService, InventoryError
from sample_users import load_sample_users
from loyalty_service import LoyaltyService
from feedback_service import FeedbackService
from payroll_service import PayrollService
from accounting_service import AccountingLedger
from demo_timestamps import snapshot_demo_events, randomize_new_demo_events
from demo_tools import (populate_demo_data, populate_trend_history, populate_accounting_activity,
                        populate_payroll_activity, backup_database, _safe_swap, _require_demo_owner,
                        INGREDIENTS, RECIPES, SUPPLIERS)


def load_complete_demo(svc, actor):
    live=Path(svc.db_path).resolve()
    with closing(connect(live)) as db:
        _require_demo_owner(db,actor)
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='DemoDataSet'").fetchone() and db.execute(
            "SELECT 1 FROM DemoDataSet WHERE dataset='complete_desktop_v1'").fetchone():
            return {'already_loaded':True}
    original=hashlib.sha256(live.read_bytes()).digest()
    with TemporaryDirectory(prefix='.onigiri_demo_',dir=live.parent) as folder:
        stage=Path(folder)/'shop.db'
        with closing(sqlite3.connect(live.as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(stage)) as target:
            source.backup(target)
        sample=InventoryService(stage)
        with closing(connect(stage)) as db:
            event_boundary=snapshot_demo_events(db)
        if not sample.inventory():populate_demo_data(sample,actor)
        else:
            # Add missing sample setup without replacing existing menu or stock.
            ingredients={r['ingredientName'].casefold():r['ingredientID'] for r in sample.inventory()}
            for name,unit,quantity,reorder in INGREDIENTS:
                if name.casefold() not in ingredients:
                    ingredients[name.casefold()]=sample.add_ingredient(name,unit,quantity,reorder,actor)
            recipes={r['name'].casefold() for r in sample.recipes()}
            for name,price,components in RECIPES:
                if name.casefold() not in recipes:
                    rid=sample.add_recipe(name,price)
                    for ingredient,quantity in components.items():sample.set_recipe_ingredient(rid,ingredients[ingredient.casefold()],quantity)
            suppliers={r['name'].casefold() for r in sample.suppliers()}
            for name,contact in SUPPLIERS:
                if name.casefold() not in suppliers:sample.add_supplier(name,contact)
        load_sample_users(sample,actor)
        def loaded(key):
            with closing(connect(stage)) as db:
                return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='DemoDataSet'").fetchone() and
                    db.execute('SELECT 1 FROM DemoDataSet WHERE dataset=?',(key,)).fetchone())
        # Existing individually imported packages are retained.
        if not loaded('trend_12day_v1'):populate_trend_history(sample,actor)
        if not loaded('accounting_examples_v1'):populate_accounting_activity(sample,actor)
        sample_names={r[0].casefold() for r in INGREDIENTS}
        sample_items=[r for r in sample.inventory() if r['ingredientName'].casefold() in sample_names]
        sample_suppliers=[r for r in sample.suppliers() if r['name'] in {s[0] for s in SUPPLIERS}]
        for index,supplier in enumerate(sample_suppliers[:3]):
            item=sample_items[index % len(sample_items)]
            po=sample.create_purchase_order({item['ingredientID']:20},'Complete fictional sample PO',
                supplier_id=supplier['supplierID'],unit_costs={item['ingredientID']:.1})
            if index<2:
                qty=20 if index==0 else 5
                sample.receive_delivery({item['ingredientID']:qty},actor,purchase_order_id=po,
                    purchase_amount=qty*.1,invoice_reference=f'DEMO-COMPLETE-PO-{index}')
        item=sample_items[0]
        sample.adjust_stock(item['ingredientID'],'remove',1,actor,'Complete sample spoilage',accounting_amount=2)
        with closing(connect(stage)) as db:
            employees=[dict(r) for r in db.execute('''SELECT e.employeeID FROM Employee e
                JOIN DemoUserImport d ON d.userID=e.userID JOIN "User" u ON u.userID=e.userID
                WHERE u.accountActive=1 AND e.isActive=1 ORDER BY u.userID''')]
            customers=[dict(r) for r in db.execute('''SELECT c.customerID,c.userID FROM Customer c
                JOIN DemoUserImport d ON d.userID=c.userID JOIN "User" u ON u.userID=c.userID
                WHERE u.accountActive=1 ORDER BY u.userID''')]
        pay=PayrollService(stage)
        rates={e.employeeID:e.hourlyRate for e in pay.employees(actor)}
        for employee in employees:
            if rates.get(employee['employeeID'],0)<=0:pay.set_hourly_rate(actor,employee['employeeID'],18)
        if not loaded('payroll_examples_v1'):populate_payroll_activity(sample,actor)
        for offset in (1,2):
            day=date.today()-timedelta(days=offset)
            existing={p['payDate'] for p in pay.payrolls(actor)}
            while day.isoformat() in existing:day-=timedelta(days=1)
            pid=pay.open_payroll(actor,day.isoformat())
            for employee in employees:pay.enter_hours(actor,pid,employee['employeeID'],8)
            if offset==2:pay.calculate(actor,pid);pay.approve(actor,pid)
        loyalty=LoyaltyService(stage);loyalty.ensure_sample_rewards()
        feedback=FeedbackService(stage)
        recipe=next((r for r in sample.recipes() if r['name'] in {v[0] for v in RECIPES}
            and r['price']>0 and sample.recipe_ingredients(r['recipeID'])),None)
        if not recipe or not customers:raise InventoryError('Complete demo needs sample recipes and active sample customers. No changes were applied.')
        def order_for(customer, servings):
            needs={r['ingredientID']:r['quantityRequired']*servings for r in sample.recipe_ingredients(recipe['recipeID'])}
            stock={r['ingredientID']:r['quantityOnHand'] for r in sample.inventory()}
            shortages={iid:qty-stock[iid]+1 for iid,qty in needs.items() if qty>stock[iid]}
            if shortages:sample.receive_delivery(shortages,actor,purchase_amount=100,invoice_reference='DEMO-COMPLETE-RESTOCK')
            return sample.create_customer_order({recipe['recipeID']:servings},actor,customer['customerID'])
        for index,customer in enumerate(customers):
            loyalty.enroll_existing_customer(customer['userID'],actor)
            balance=AccountingLedger(stage).calculateSummary().balance
            servings=max(2,math.ceil((max(0,-balance)+2000)/recipe['price'])) if index==0 else 2
            oid=order_for(customer,servings)
            loyalty.complete_order_with_loyalty(actor,customer['customerID'],oid)
            entry=feedback.submit_feedback(customer['userID'],'Sample feedback: delicious onigiri and friendly service.',5)
            if index%2:feedback.review_feedback(actor,entry.feedbackID)
        first=customers[0];reward=loyalty.rewards()[0]
        oid=order_for(first,2)
        loyalty.complete_order_with_loyalty(actor,first['customerID'],oid,reward_id=reward['rewardID'])
        pending=sample.create_customer_order({recipe['recipeID']:1},actor,first['customerID'])
        sample.cancel_customer_order(pending)
        for index,item in enumerate([r for r in sample.inventory() if r['ingredientName'].casefold() in sample_names][:3]):
            sample.set_reorder_level(item['ingredientID'],item['quantityOnHand']+1)
            alert=next(a for a in sample.alerts() if a['ingredientID']==item['ingredientID'])
            if index:sample.update_alert(alert['alertID'],'Reviewed' if index==1 else 'Closed')
        AccountingLedger(stage).reconcile_with_report()
        with transaction(stage) as db:
            randomize_new_demo_events(db,event_boundary)
            db.execute("INSERT INTO DemoDataSet(dataset) VALUES('complete_desktop_v1')")
            if db.execute('PRAGMA foreign_key_check').fetchall():raise InventoryError('Sample data failed relationship checks.')
        if hashlib.sha256(live.read_bytes()).digest()!=original:
            raise InventoryError('The database changed during sample preparation. Close other sessions and retry; nothing was replaced.')
        safety=backup_database(svc,'before_complete_demo')
        _safe_swap(stage,live)
    return {'already_loaded':False,'backup':str(safety)}
