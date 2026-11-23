"""Account-specific desktop preferences, separate from restaurant records."""
from contextlib import closing
import json

from inventory_db import connect, transaction


DEFAULT_ACCESSIBILITY = {'text_size':100, 'contrast':'Standard', 'cursor':'Standard',
                         'narration':False, 'reduced_motion':False}


class DesktopPreferences:
    def __init__(self, db_path):
        self.db_path=db_path
        with transaction(db_path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS DesktopPreferences (
                accountKey TEXT PRIMARY KEY, options TEXT NOT NULL)''')

    def get(self, user_id=None):
        with closing(connect(self.db_path)) as db:
            row=db.execute('SELECT options FROM DesktopPreferences WHERE accountKey=?',
                           (self.key(user_id),)).fetchone()
        try:
            data=json.loads(row[0]) if row else {}
        except (ValueError,TypeError):data={}
        return data if isinstance(data,dict) else {}

    @staticmethod
    def key(user_id):
        return f'user:{int(user_id)}' if user_id is not None else 'guest'

    def save(self, user_id=None, **options):
        with transaction(self.db_path) as db:
            row=db.execute('SELECT options FROM DesktopPreferences WHERE accountKey=?',
                           (self.key(user_id),)).fetchone()
            try:data=json.loads(row[0]) if row else {}
            except (ValueError,TypeError):data={}
            if not isinstance(data,dict):data={}
            data.update(options)
            db.execute('INSERT OR REPLACE INTO DesktopPreferences VALUES(?,?)',
                       (self.key(user_id),json.dumps(data)))

    def accessibility(self,user_id=None):
        saved=self.get(user_id).get('accessibility',{})
        result=dict(DEFAULT_ACCESSIBILITY)
        if isinstance(saved,dict):
            for key,choices in {'text_size':(100,115,130,150),
                                'contrast':('Standard','Colourblind Friendly','High Contrast'),
                                'cursor':('Standard','Crosshair','Hand'),
                                'narration':(False,True),'reduced_motion':(False,True)}.items():
                if saved.get(key) in choices:result[key]=saved[key]
        return result

    def quick_actions(self,user_id,defaults):
        saved=self.get(user_id).get('quick_actions',[])
        if not isinstance(saved,list):saved=[]
        by_page={page:label for label,page in defaults}
        pages=[]
        for page in saved+list(by_page):
            if isinstance(page,str) and page in by_page and page not in pages:pages.append(page)
        return [(by_page[page],page) for page in pages]
