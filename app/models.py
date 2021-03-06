""" Database and storage related functions and classes """
import datetime
import sys
import redis
import copy
from flask import g
from peewee import IntegerField, DateTimeField, BooleanField, Proxy, Model, Database
from peewee import CharField, ForeignKeyField, TextField, PrimaryKeyField
from playhouse.db_url import connect as db_url_connect
from playhouse.flask_utils import FlaskDB
from .config import config

# Why not here? >_>
rconn = redis.from_url(config.app.redis_url)

def db_connect():
    dbconnect = config.database
    # Taken from peewee's flask_utils
    try:
        name = dbconnect.pop('name')
        engine = dbconnect.pop('engine')
    except KeyError:
        raise RuntimeError('DATABASE configuration must specify a '
                            '`name` and `engine`.')

    if '.' in engine:
        path, class_name = engine.rsplit('.', 1)
    else:
        path, class_name = 'peewee', engine

    try:
        __import__(path)
        module = sys.modules[path]
        database_class = getattr(module, class_name)
        assert issubclass(database_class, Database)
    except ImportError:
        raise RuntimeError('Unable to import %s' % engine)
    except AttributeError:
        raise RuntimeError('Database engine not found %s' % engine)
    except AssertionError:
        raise RuntimeError('Database engine not a subclass of '
                            'peewee.Database: %s' % engine)
    
    return database_class(name, **dbconnect)

dbm = db_connect()
dex = dbm.execute


def peewee_count_queries(*args, **kwargs):
    """ Used to count and display number of queries """
    try:
        if not hasattr(g, 'pqc'):
            g.pqc = 0
        g.pqc += 1
    except RuntimeError:
        pass
    return dex(*args, **kwargs)


dbm.execute = peewee_count_queries


db = Proxy()
db.initialize(dbm)


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    uid = CharField(primary_key=True, max_length=40)
    crypto = IntegerField()  # Password hash algo, 1 = bcrypt.
    email = CharField(null=True)
    joindate = DateTimeField(null=True)
    name = CharField(null=True, unique=True, max_length=64)
    password = CharField(null=True)

    score = IntegerField(default=0)  # AKA phuks taken
    given = IntegerField(default=0)  # AKA phuks given
    # status: 0 = OK; 10 = deleted
    status = IntegerField(default=0)
    resets = IntegerField(default=0)

    class Meta:
        table_name = 'user'


class Client(BaseModel):
    _default_scopes = TextField(null=True)
    _redirect_uris = TextField(null=True)
    client = CharField(db_column='client_id', primary_key=True, max_length=40)
    client_secret = CharField(unique=True, max_length=55)
    is_confidential = BooleanField(null=True)
    name = CharField(null=True, max_length=40)
    user = ForeignKeyField(db_column='user_id', null=True, model=User, field='uid')

    class Meta:
        table_name = 'client'


class Grant(BaseModel):
    _scopes = TextField(null=True)
    client = ForeignKeyField(db_column='client_id', model=Client, field='client')
    code = CharField(index=True)
    expires = DateTimeField(null=True)
    redirect_uri = CharField(null=True)
    user = ForeignKeyField(db_column='user_id', null=True, model=User,
                           field='uid')

    class Meta:
        table_name = 'grant'


class Message(BaseModel):
    content = TextField(null=True)
    mid = PrimaryKeyField()
    mlink = CharField(null=True)
    # mtype values: 
    # 1: sent, 4: post replies, 5: comment replies, 8: mentions, 9: saved message
    # 6: deleted, 41: ignored messages  => won't display anywhere
    # 2 (mod invite), 7 (ban notification), 11 (deletion): modmail
    mtype = IntegerField(null=True)
    posted = DateTimeField(null=True)
    read = DateTimeField(null=True)
    receivedby = ForeignKeyField(db_column='receivedby', null=True,
                                 model=User, field='uid')
    sentby = ForeignKeyField(db_column='sentby', null=True, model=User,
                             backref='user_sentby_set', field='uid')
    subject = CharField(null=True)

    class Meta:
        table_name = 'message'


class SiteLog(BaseModel):
    action = IntegerField(null=True)
    desc = CharField(null=True)
    lid = PrimaryKeyField()
    link = CharField(null=True)
    time = DateTimeField(default=datetime.datetime.utcnow)
    uid = ForeignKeyField(db_column='uid', null=True, model=User, field='uid')
    target = ForeignKeyField(db_column='target_uid', null=True, model=User, field='uid')

    class Meta:
        table_name = 'site_log'


class SiteMetadata(BaseModel):
    key = CharField(null=True)
    value = CharField(null=True)
    xid = PrimaryKeyField()

    class Meta:
        table_name = 'site_metadata'


class Sub(BaseModel):
    name = CharField(null=True, unique=True, max_length=32)
    nsfw = BooleanField(default=False)
    sid = CharField(primary_key=True, max_length=40)
    sidebar = TextField(default='')
    status = IntegerField(null=True)
    title = CharField(null=True, max_length=50)
    sort = CharField(null=True, max_length=32)
    creation = DateTimeField(default=datetime.datetime.utcnow)
    subscribers = IntegerField(default=1)
    posts = IntegerField(default=0)

    class Meta:
        table_name = 'sub'
    
    def get_metadata(self, key):
        """ Returns `key` for submetadata or `None` if it does not exist.
        Only works for single keys """
        try:
            m = SubMetadata.get((SubMetadata.sid == self.sid) & (SubMetadata.key == key))
            return m.value
        except SubMetadata.DoesNotEXist:
            return None

    def update_metadata(self, key, value):
        if value == True:
            value = '1'
        elif value == False:
            value = '0'
        restr = SubMetadata.get_or_create(sid=self.sid, key=key)[0]
        if restr.value != value:
            restr.value = value
            restr.save()


class SubFlair(BaseModel):
    sid = ForeignKeyField(db_column='sid', null=True, model=Sub,
                          field='sid')
    text = CharField(null=True)
    xid = PrimaryKeyField()

    class Meta:
        table_name = 'sub_flair'


class SubLog(BaseModel):
    action = IntegerField(null=True)
    desc = CharField(null=True)
    lid = PrimaryKeyField()
    link = CharField(null=True)
    sid = ForeignKeyField(db_column='sid', null=True, model=Sub, field='sid')
    uid = ForeignKeyField(db_column='uid', null=True, model=User, field='uid')
    target = ForeignKeyField(db_column='target_uid', null=True, model=User, field='uid')
    admin = BooleanField(default=False)  # True if action was performed by an admin override.
    time = DateTimeField(default=datetime.datetime.utcnow)

    class Meta:
        table_name = 'sub_log'


class SubMetadata(BaseModel):
    key = CharField(null=True)
    sid = ForeignKeyField(db_column='sid', null=True, model=Sub,
                          field='sid')
    value = CharField(null=True)
    xid = PrimaryKeyField()

    class Meta:
        table_name = 'sub_metadata'


class SubPost(BaseModel):
    content = TextField(null=True)
    deleted = IntegerField(null=True)
    link = CharField(null=True)
    nsfw = BooleanField(null=True)
    pid = PrimaryKeyField()
    posted = DateTimeField(null=True)
    edited = DateTimeField(null=True)
    ptype = IntegerField(null=True) # 1=text, 2=link, 3=poll
    
    score = IntegerField(null=True)  # XXX: Deprecated
    upvotes = IntegerField(default=0)
    downvotes = IntegerField(default=0)

    sid = ForeignKeyField(db_column='sid', null=True, model=Sub, field='sid')
    thumbnail = CharField(null=True)
    title = CharField(null=True)
    comments = IntegerField()
    uid = ForeignKeyField(db_column='uid', null=True, model=User, field='uid', backref='posts')
    flair = CharField(null=True, max_length=25)

    class Meta:
        table_name = 'sub_post'


class SubPostPollOption(BaseModel):
    """ List of options for a poll """
    pid = ForeignKeyField(db_column='pid', model=SubPost, field='pid')
    text = CharField()

    class Meta:
        table_name = 'sub_post_poll_option'


class SubPostPollVote(BaseModel):
    """ List of options for a poll """ 
    pid = ForeignKeyField(db_column='pid', model=SubPost, field='pid')
    uid = ForeignKeyField(db_column='uid', model=User)
    vid = ForeignKeyField(db_column='vid', model=SubPostPollOption, backref='votes')

    class Meta:
        table_name = 'sub_post_poll_vote'


class SubPostComment(BaseModel):
    cid = CharField(primary_key=True, max_length=40)
    content = TextField(null=True)
    lastedit = DateTimeField(null=True)
    parentcid = ForeignKeyField(db_column='parentcid', null=True,
                                model='self', field='cid')
    pid = ForeignKeyField(db_column='pid', null=True, model=SubPost,
                          field='pid')
    score = IntegerField(null=True)
    upvotes = IntegerField(default=0)
    downvotes = IntegerField(default=0)
    status = IntegerField(null=True)
    time = DateTimeField(null=True)
    uid = ForeignKeyField(db_column='uid', null=True, model=User,
                          field='uid', backref='comments')

    class Meta:
        table_name = 'sub_post_comment'


class SubPostCommentVote(BaseModel):
    datetime = DateTimeField(null=True, default=datetime.datetime.utcnow)
    cid = CharField(null=True)
    positive = IntegerField(null=True)
    uid = ForeignKeyField(db_column='uid', null=True, model=User,
                          field='uid')
    xid = PrimaryKeyField()

    class Meta:
        table_name = 'sub_post_comment_vote'


class SubPostMetadata(BaseModel):
    key = CharField(null=True)
    pid = ForeignKeyField(db_column='pid', null=True, model=SubPost,
                          field='pid')
    value = CharField(null=True)
    xid = PrimaryKeyField()

    class Meta:
        table_name = 'sub_post_metadata'


class SubPostVote(BaseModel):
    datetime = DateTimeField(null=True, default=datetime.datetime.utcnow)
    pid = ForeignKeyField(db_column='pid', null=True, model=SubPost,
                          field='pid', backref='votes')
    positive = IntegerField(null=True)
    uid = ForeignKeyField(db_column='uid', null=True, model=User,
                          field='uid')
    xid = PrimaryKeyField()

    class Meta:
        table_name = 'sub_post_vote'


class SubStylesheet(BaseModel):
    content = TextField(null=True)
    source = TextField()
    sid = ForeignKeyField(db_column='sid', null=True, model=Sub,
                          field='sid')
    xid = PrimaryKeyField()

    class Meta:
        table_name = 'sub_stylesheet'


class SubSubscriber(BaseModel):
    """ Stores subscribed and blocked subs """
    order = IntegerField(null=True)
    sid = ForeignKeyField(db_column='sid', null=True, model=Sub, field='sid')
    # status is 1 for subscribed, 2 for blocked and 4 for saved (displayed in the top bar)
    status = IntegerField(null=True)
    time = DateTimeField(default=datetime.datetime.utcnow)
    uid = ForeignKeyField(db_column='uid', null=True, model=User, field='uid')
    xid = PrimaryKeyField()

    class Meta:
        table_name = 'sub_subscriber'


class Token(BaseModel):
    _scopes = TextField(null=True)
    access_token = CharField(null=True, unique=True, max_length=100)
    client = ForeignKeyField(db_column='client_id', model=Client,
                             field='client')
    expires = DateTimeField(null=True)
    refresh_token = CharField(null=True, unique=True, max_length=100)
    token_type = CharField(null=True, max_length=40)
    user = ForeignKeyField(db_column='user_id', null=True, model=User,
                           field='uid')

    class Meta:
        table_name = 'token'


class UserMetadata(BaseModel):
    key = CharField(null=True)
    uid = ForeignKeyField(db_column='uid', null=True, model=User,
                          field='uid')
    value = CharField(null=True)
    xid = PrimaryKeyField()

    class Meta:
        table_name = 'user_metadata'


class UserSaved(BaseModel):
    pid = IntegerField(null=True)
    uid = ForeignKeyField(db_column='uid', null=True, model=User,
                          field='uid')
    xid = PrimaryKeyField()

    class Meta:
        table_name = 'user_saved'


class UserUploads(BaseModel):
    xid = PrimaryKeyField()
    pid = ForeignKeyField(db_column='pid', null=True, model=SubPost,
                          field='pid')
    uid = ForeignKeyField(db_column='uid', null=True, model=User,
                          field='uid')
    fileid = CharField(null=True)
    thumbnail = CharField(null=True)
    status = IntegerField()

    class Meta:
        table_name = 'user_uploads'


class SubUploads(BaseModel):
    sid = ForeignKeyField(db_column='sid', model=Sub, field='sid')
    fileid = CharField()
    thumbnail = CharField()
    name = CharField()
    size = IntegerField()

    class Meta:
        table_name = 'sub_uploads'


class SubPostReport(BaseModel):
    pid = ForeignKeyField(db_column='pid', model=SubPost, field='pid')
    uid = ForeignKeyField(db_column='uid', model=User, field='uid')
    datetime = DateTimeField(default=datetime.datetime.now)
    reason = CharField(max_length=128)

    class Meta:
        table_name = 'sub_post_report'


class SubPostCommentReport(BaseModel):
    cid = ForeignKeyField(db_column='cid', model=SubPostComment, field='cid')
    uid = ForeignKeyField(db_column='uid', model=User, field='uid')
    datetime = DateTimeField(default=datetime.datetime.now)
    reason = CharField(max_length=128)

    class Meta:
        table_name = 'sub_post_comment_report'


class SubPostCommentHistory(BaseModel):
    cid = ForeignKeyField(db_column='cid', model=SubPostComment, field='cid')
    datetime = DateTimeField(default=datetime.datetime.now)
    content = TextField(null=True)
    class Meta:
        table_name = "sub_post_comment_history"


class UserIgnores(BaseModel):
    uid = ForeignKeyField(db_column='uid', model=User, field='uid')
    target = CharField(max_length=40)
    date = DateTimeField(default=datetime.datetime.now)

    class Meta:
        table_name = 'user_ignores'


class APIToken(BaseModel):
    user = ForeignKeyField(db_column='uid', model=User, field='uid')
    token = CharField(unique=True)
    can_post = BooleanField()
    can_mod = BooleanField()
    can_message = BooleanField()
    can_upload = BooleanField()
    is_active = BooleanField(default=True)
    is_ip_restricted = BooleanField(default=False)

    class Meta:
        table_name = 'api_token'


class APITokenSettings(BaseModel):
    """ API Token settings. Mainly used for IP whitelisting """
    token = ForeignKeyField(model=APIToken, field='id')
    key = CharField()
    value = CharField()

    class Meta:
        table_name = 'api_token_settings'


class SubMod(BaseModel):
    user = ForeignKeyField(db_column='uid', model=User, field='uid')
    sub = ForeignKeyField(db_column='sid', model=Sub, field='sid')
    # Power level: 0=owner, 1=mod, 2=janitor
    power_level = IntegerField()

    invite = BooleanField(default=False)  # if True, mod is invited and not effective

    class Meta:
        table_name = "sub_mod"


class SubBan(BaseModel):
    user = ForeignKeyField(db_column='uid', model=User, field='uid')
    sub = ForeignKeyField(db_column='sid', model=Sub, field='sid')

    created = DateTimeField(default=datetime.datetime.utcnow)
    reason = CharField(max_length=128)
    expires = DateTimeField(null=True)
    effective = BooleanField(default=True)

    created_by = ForeignKeyField(db_column='created_by_id', model=User, field='uid')

    class Meta:
        table_name = "sub_ban"


class InviteCode(BaseModel):
    user = ForeignKeyField(db_column='uid', model=User, field='uid')

    code = CharField(max_length=64)

    created = DateTimeField(default=datetime.datetime.utcnow)
    expires = DateTimeField(null=True)
    uses = IntegerField(default=0)
    max_uses = IntegerField()

    class Meta:
        table_name = "invite_code"