""" /do/ views (AJAX stuff) """

import json
import re
import time
import datetime
import uuid
import bcrypt
import requests
import magic
import hashlib
import os
import random
import pyexiv2
from PIL import Image
from bs4 import BeautifulSoup
from flask import Blueprint, redirect, url_for, session, abort, jsonify
from flask import render_template, request
from flask_login import login_user, login_required, logout_user, current_user
from ..config import config
from .. import forms, misc, caching
from ..socketio import socketio
from ..forms import LogOutForm, CreateSubFlair, DummyForm
from ..forms import CreateSubForm, EditSubForm, EditUserForm, EditSubCSSForm, ChangePasswordForm
from ..forms import CreateUserBadgeForm, EditModForm, BanUserSubForm, DeleteAccountForm
from ..forms import CreateSubTextPost, EditSubTextPostForm, AssignUserBadgeForm
from ..forms import PostComment, CreateUserMessageForm, DeletePost
from ..forms import EditSubLinkPostForm, SearchForm, EditMod2Form
from ..forms import DeleteSubFlair, BanDomainForm
from ..forms import CreateMulti, EditMulti, DeleteMulti
from ..forms import UseInviteCodeForm, SecurityQuestionForm
from ..badges import badges
from ..misc import cache, sendMail, allowedNames, get_errors, engine
from ..models import SubPost, SubPostComment, Sub, Message, User, UserIgnores, SubLog, SiteLog, SubMetadata, UserSaved
from ..models import SubMod, SubBan, SubPostCommentHistory, InviteCode
from ..models import SubStylesheet, SubSubscriber, SubUploads, UserUploads, SiteMetadata, SubPostMetadata, SubPostReport
from ..models import SubPostVote, SubPostCommentVote, UserMetadata, SubFlair, SubPostPollOption, SubPostPollVote, SubPostCommentReport
from peewee import fn, JOIN

do = Blueprint('do', __name__)

# allowedCSS = re.compile("\'(^[0-9]{1,5}[a-zA-Z ]+$)|none\'")


@do.route("/do/logout", methods=['POST'])
@login_required
def logout():
    """ Logout endpoint """
    form = LogOutForm()
    if form.validate():
        if session.get('usid'):
            socketio.emit('uinfo', {'loggedin': False}, namespace='/alt',
                          room=session['usid'])
        logout_user()
    if request.get_json() and request.get_json().get('j'):
        return jsonify(status='ok')
    else:
        return redirect(url_for('index'))


@do.route("/do/search", defaults={'stype': 'search'}, methods=['POST'])
@do.route("/do/search/<stype>", methods=['POST'])
def search(stype):
    """ Search endpoint """
    if stype not in ('search', 'subs', 'admin_users', 'admin_post_voting', 'admin_subs', 'admin_post'):
        abort(404)
    if not stype.endswith('search'):
        stype += '_search'

    if not current_user.is_admin() and stype.startswith('admin'):
        abort(403)
    form = SearchForm()
    term = re.sub(r'[^A-Za-z0-9.,\-_\'" ]+', '', form.term.data)
    return redirect(url_for(stype, term=term))


@do.route("/do/edit_user/password", methods=['POST'])
@login_required
def edit_user_password():
    form = ChangePasswordForm()
    if form.validate():
        usr = User.get(User.uid == current_user.uid)
        if not misc.validate_password(usr, form.oldpassword.data):
            return json.dumps({'status': 'error', 'error': ['Wrong password']})
        
        password = bcrypt.hashpw(form.password.data.encode('utf-8'), bcrypt.gensalt())
        if isinstance(password, bytes):
            password = password.decode('utf-8')

        usr.password = password
        usr.crypto = 1
        usr.save()
        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/delete_account", methods=['POST'])
@login_required
def delete_user():
    form = DeleteAccountForm()
    if form.validate():
        usr = User.get(User.uid == current_user.uid)
        if not misc.validate_password(usr, form.password.data):
            return jsonify(status='error', error=['Wrong password'])

        if form.consent.data != 'YES':
            return jsonify(status='error', error=['Type "YES" in the box'])
        
        usr.status = 10
        usr.save()
        logout_user()

        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/edit_user", methods=['POST'])
@login_required
def edit_user():
    """ Edit user endpoint """
    form = EditUserForm()
    if form.validate():
        if form.subtheme.data != '':
            try:
                sub = Sub.get(fn.Lower(Sub.name) == form.subtheme.data.lower())
            except Sub.DoesNotExist:
                return jsonify(status='error', error=['Sub does not exist'])

        usr = User.get(User.uid == current_user.uid)
        usr.email = form.email.data
        usr.save()
        current_user.update_prefs('labrat', form.experimental.data)
        current_user.update_prefs('nostyles', form.disable_sub_style.data)
        current_user.update_prefs('nsfw', form.show_nsfw.data)
        current_user.update_prefs('noscroll', form.noscroll.data)
        current_user.update_prefs('nochat', form.nochat.data)
        current_user.update_prefs('subtheme', form.subtheme.data, False)

        cache.delete_memoized(current_user.get_global_stylesheet)

        return json.dumps({'status': 'ok'})
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/delete_post", methods=['POST'])
@login_required
def delete_post():
    """ Post deletion endpoint """
    form = DeletePost()

    if form.validate():
        try:
            post = SubPost.get(SubPost.pid == form.post.data)
        except SubPost.DoesNotExist:
            return jsonify(status='error', error=['Post does not exist'])

        if post.deleted != 0:
            return jsonify(status='error', error=['Post was already deleted'])

        sub = Sub.get(Sub.sid == post.sid)
        subI = misc.getSubData(post.sid)

        if not current_user.is_mod(sub.sid) and not current_user.is_admin() and not post.uid_id == current_user.uid:
            return jsonify(status='error', error=['Not authorized'])

        if post.uid_id == current_user.uid:
            deletion = 1
        else:
            if not form.reason.data:
                return jsonify(status="error", error=["Cannot delete without reason"])
            deletion = 2
            # notify user.
            misc.create_message(mfrom=current_user.uid, to=post.uid.uid,
                                subject='Your post on /s/' + sub.name + ' has been deleted.',
                                content='Reason: ' + form.reason.data,
                                link=sub.name, mtype=11)
            
            misc.create_sublog(misc.LOG_TYPE_SUB_DELETE_POST, current_user.uid, post.sid,
                    comment=form.reason.data, link=url_for('view_post_inbox', pid=post.pid),
                    admin=True if (not current_user.is_mod(post.sid) and current_user.is_admin()) else False)



        # time limited to prevent socket spam
        if (datetime.datetime.utcnow() - post.posted.replace(tzinfo=None)).seconds < 86400:
            socketio.emit('deletion', {'pid': post.pid}, namespace='/snt', room='/all/new')

        # check if the post is an announcement. Unannounce if it is.
        try:
            ann = SiteMetadata.select().where(SiteMetadata.key == 'announcement').where(SiteMetadata.value == post.pid).get()
            ann.delete_instance()
            cache.delete_memoized(misc.getAnnouncementPid)
        except SiteMetadata.DoesNotExist:
            pass

        sub.posts -= 1
        sub.save()

        post.deleted = deletion
        post.save()

        return jsonify(status='ok')
    return jsonify(status='ok', error=get_errors(form))


@do.route("/do/create_sub", methods=['POST'])
@login_required
def create_sub():
    """ Sub creation endpoint """
    form = CreateSubForm()
    if form.validate():
        if not allowedNames.match(form.subname.data):
            return jsonify(status='error', error=['Sub name has invalid characters'])

        if len(form.subname.data) < 2:
            return jsonify(status='error', error=['Sub name too short'])

        if len(form.subname.data) > 32:
            return jsonify(status='error', error=['Sub name too long'])

        if form.subname.data.lower() in ('all', 'new', 'hot', 'top', 'admin', 'home'):
            return jsonify(status='error', error=['Invalid sub name'])

        try:
            Sub.get(fn.Lower(Sub.name) == form.subname.data.lower())
            return jsonify(status='error', error=['Sub is already registered'])
        except Sub.DoesNotExist:
            pass

        level = misc.get_user_level(current_user.uid)[0]
        if not config.app.testing:
            if (level <= 1) and (not current_user.admin):
                return jsonify(status='error', error=['You must be at least level 2.'])

            owned = SubMod.select().where(SubMod.uid == current_user.uid).where((SubMod.power_level == 0) & (SubMod.invite == False)).count()

            if owned >= 20 and (not current_user.admin):
                return jsonify(status='error', error=['You cannot own more than 20 subs.'])

            if owned >= (level - 1) and (not current_user.admin):
                return jsonify(status='error', error=['You cannot own more than {0} subs. Try leveling up your account'.format(level - 1)])

        sub = Sub.create(sid=uuid.uuid4(), name=form.subname.data, title=form.title.data)
        SubMetadata.create(sid=sub.sid, key='mod', value=current_user.uid)
        SubMod.create(sid=sub.sid, uid=current_user.uid, power_level=0)
        SubStylesheet.create(sid=sub.sid, content='', source='/* CSS here */')

        # admin/site log
        misc.create_sublog(misc.LOG_TYPE_SUB_CREATE, uid=current_user.uid, sid=sub.sid, admin=True)

        SubSubscriber.create(uid=current_user.uid, sid=sub.sid, status=1)

        return jsonify(status='ok', addr=url_for('sub.view_sub', sub=form.subname.data))

    return jsonify(status='error', error=get_errors(form))


@do.route("/do/edit_sub_css/<sub>", methods=['POST'])
@login_required
def edit_sub_css(sub):
    """ Edit sub endpoint """
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=["Sub does not exist"])

    if not current_user.is_mod(sub.sid, 1) and not current_user.is_admin():
        return jsonify(status='error', error=["Not authorized"])

    form = EditSubCSSForm()
    if form.validate():
        styles = SubStylesheet.get(SubStylesheet.sid == sub.sid)
        dcss = misc.validate_css(form.css.data, sub.sid)
        if dcss[0] != 0:
            return jsonify(status='error', error=['Error on {0}:{1}: {2}'.format(dcss[1], dcss[2], dcss[0])])

        styles.content = dcss[1]
        styles.source = form.css.data
        styles.save()
        SubLog.create(sid=sub.sid, action=4, link=url_for('sub.view_sub', sub=sub.name), time=datetime.datetime.utcnow(),
                      desc='{0} modified the sub\'s stylesheet'.format(current_user.name))

        return json.dumps({'status': 'ok',
                           'addr': url_for('sub.view_sub', sub=sub.name)})
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/edit_sub/<sub>", methods=['POST'])
@login_required
def edit_sub(sub):
    """ Edit sub endpoint """
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=["Sub does not exist"])
    if current_user.is_mod(sub.sid, 1) or current_user.is_admin():
        form = EditSubForm()
        if form.validate():
            sub.title = form.title.data
            sub.sidebar = form.sidebar.data
            sub.nsfw = form.nsfw.data 
            sub.save()
            
            sub.update_metadata('restricted', form.restricted.data)
            sub.update_metadata('ucf', form.usercanflair.data)
            sub.update_metadata('videomode', form.videomode.data)
            sub.update_metadata('allow_polls', form.polling.data)

            if form.subsort.data != "None":
                sub.update_metadata('sort', form.subsort.data)

            misc.create_sublog(misc.LOG_TYPE_SUB_SETTINGS, current_user.uid, sub.sid)

            if not current_user.is_mod(sub.sid, 1) and current_user.is_admin():
                misc.create_sitelog(misc.LOG_TYPE_SUB_SETTINGS, current_user.uid,
                                    comment='/s/' + sub.name,
                                    link=url_for('sub.view_sub', sub=sub.name))

            return jsonify(status="ok", addr=url_for('sub.view_sub', sub=sub.name))
        return jsonify(status="error", error=get_errors(form))
    else:
        abort(403)


@do.route("/do/flair/<sub>/<pid>/<fl>", methods=['POST'])
@login_required
def assign_post_flair(sub, pid, fl):
    """ Assign a post's flair """
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=["Sub does not exist"])

    try:
        post = SubPost.get(SubPost.pid == pid)
    except SubPost.DoesNotExist:
        return jsonify(status='error', error=['Post does not exist'])

    form = DummyForm()
    if form.validate():
        if current_user.is_mod(sub.sid) or (post.uid_id == current_user.uid and sub.get_metadata('ucf')):
            try:
                flair = SubFlair.get((SubFlair.xid == fl) & (SubFlair.sid == sub.sid))
            except SubFlair.DoesNotExist:
                return jsonify(status='error', error='Flair does not exist')

            post.flair = flair.text
            post.save()


            return jsonify(status='ok')
        else:
            return jsonify(status='error', error='Not authorized')
    return jsonify(status="error", error=get_errors(form))


@do.route("/do/remove_post_flair/<sub>/<pid>", methods=['POST'])
def remove_post_flair(sub, pid):
    """ Deletes a post's flair """
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=["Sub does not exist"])

    try:
        post = SubPost.get(SubPost.pid == pid)
    except SubPost.DoesNotExist:
        return jsonify(status='error', error=['Post does not exist'])

    if current_user.is_mod(sub.sid) or (post.uid_id == current_user.uid and sub.get_metadata('ucf')):
        if not post.flair:
            return jsonify(status='error', error='Post has no flair')
        else:
            post.flair = None
            post.save()

        return jsonify(status='ok')
    else:
        abort(403)


@do.route("/do/edit_mod", methods=['POST'])
@login_required
def edit_mod():
    """ Admin endpoint used for sub transfers. """
    if not current_user.is_admin():
        abort(403)
    form = EditModForm()

    try:
        sub = Sub.get(fn.Lower(Sub.name) == form.sub.data.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=["Sub does not exist"])
    
    try:
        user = User.get(fn.Lower(User.name) == form.user.data.lower())
    except User.DoesNotExist:
        return jsonify(status='error', error=["User does not exist"])

    if form.validate():
        try:
            sm = SubMod.get((SubMod.sid == sub.sid) & (SubMod.uid == user.uid))
            sm.power_level = 0
            sm.invite = False
            sm.save()
        except SubMod.DoesNotExist:
            SubMod.create(sid=sub.sid, uid=user.uid, power_level=0)

        misc.create_sublog(misc.LOG_TYPE_SUB_TRANSFER, current_user.uid, sub.sid,
                           comment=user.name, admin=True)

        return jsonify(status='ok')
    return jsonify(status="error", error=get_errors(form))


@do.route("/do/assign_userbadge", methods=['POST'])
@login_required
def assign_userbadge():
    """ Admin endpoint used for assigning a user badge. """
    if not current_user.is_admin():
        abort(403)
    form = AssignUserBadgeForm()

    l = []
    for bg in badges:
        l.append(badges[bg]['nick'])

    if form.badge.data not in l:
        return jsonify(status='error', error=["Badge does not exist"])

    try:
        user = User.get(fn.Lower(User.name) == form.user.data.lower())
    except User.DoesNotExist:
        return jsonify(status='error', error=["User does not exist"])

    if form.validate():

        UserMetadata.create(uid=user.uid, key='badge',
                            value=form.badge.data)

        # TODO log it, create new log type and save to sitelog ??

        return jsonify(status='ok')
    return jsonify(status="error", error=get_errors(form))


@do.route("/do/subscribe/<sid>", methods=['POST'])
@login_required
def subscribe_to_sub(sid):
    """ Subscribe to sub """
    try:
        sub = Sub.get(Sub.sid == sid)
    except Sub.DoesNotExist:
        return jsonify(status='error', error='sub not found')

    if current_user.has_subscribed(sid):
        return jsonify(status='ok', message='already subscribed')

    form = DummyForm()
    if form.validate():
        if current_user.has_blocked(sid):
            ss = SubSubscriber.get((SubSubscriber.uid == current_user.uid) & (SubSubscriber.sid == sid) & (SubSubscriber.status == 2))
            ss.delete_instance()

        SubSubscriber.create(time=datetime.datetime.utcnow(), uid=current_user.uid, sid=sid, status=1)
        sub.subscribers += 1
        sub.save()
        return jsonify(status='ok')
    return jsonify(status='error', error=get_errors(form))


@do.route("/do/unsubscribe/<sid>", methods=['POST'])
@login_required
def unsubscribe_from_sub(sid):
    """ Unsubscribe from sub """
    try:
        sub = Sub.get(Sub.sid == sid)
    except Sub.DoesNotExist:
        return jsonify(status='error', error='sub not found')

    if not current_user.has_subscribed(sid):
        return jsonify(status='ok', message='not subscribed')

    form = DummyForm()
    if form.validate():
        ss = SubSubscriber.get((SubSubscriber.uid == current_user.uid) & (SubSubscriber.sid == sid) & (SubSubscriber.status == 1))
        ss.delete_instance()

        sub.subscribers -= 1
        sub.save()
        return jsonify(status='ok')
    return jsonify(status='error', error=get_errors(form))


@do.route("/do/block/<sid>", methods=['POST'])
@login_required
def block_sub(sid):
    """ Block sub """
    try:
        sub = Sub.get(Sub.sid == sid)
    except Sub.DoesNotExist:
        return jsonify(status='error', error='sub not found')

    if current_user.has_blocked(sid):
        return jsonify(status='ok', message='already blocked')

    form = DummyForm()
    if form.validate():
        if current_user.has_subscribed(sub.name):
            sub.subscribers -= 1
            sub.save()
            ss = SubSubscriber.get((SubSubscriber.uid == current_user.uid) & (SubSubscriber.sid == sid) & (SubSubscriber.status == 1))
            ss.delete_instance()

        SubSubscriber.create(time=datetime.datetime.utcnow(), uid=current_user.uid, sid=sid, status=2)
        return jsonify(status='ok')
    return jsonify(status='error', error=get_errors(form))


@do.route("/do/unblock/<sid>", methods=['POST'])
@login_required
def unblock_sub(sid):
    """ Unblock sub """
    try:
        sub = Sub.get(Sub.sid == sid)
    except Sub.DoesNotExist:
        return jsonify(status='error', error='sub not found')

    if not current_user.has_blocked(sid):
        return jsonify(status='ok', message='sub not blocked')

    form = DummyForm()
    if form.validate():
        ss = SubSubscriber.get((SubSubscriber.uid == current_user.uid) & (SubSubscriber.sid == sub.sid) & (SubSubscriber.status == 2))
        ss.delete_instance()
        return jsonify(status='ok')
    return jsonify(status='error', error=get_errors(form))


@do.route("/do/get_txtpost/<pid>", methods=['GET'])
def get_txtpost(pid):
    """ Sub text post expando get endpoint """
    try:
        try:
            post = misc.getSinglePost(pid)
        except SubPost.DoesNotExist:
            abort(404)
        
        if post['deleted']:
            abort(404)
        cont = misc.our_markdown(post['content'])
        if post['ptype'] == 3:
            pollData = {'has_voted': False}
            postmeta = misc.metadata_to_dict(SubPostMetadata.select().where(SubPostMetadata.pid == pid))
            # poll. grab options and votes.
            options = SubPostPollOption.select(SubPostPollOption.id, SubPostPollOption.text, fn.Count(SubPostPollVote.id).alias('votecount'))
            options = options.join(SubPostPollVote, JOIN.LEFT_OUTER, on=(SubPostPollVote.vid == SubPostPollOption.id))
            options = options.where(SubPostPollOption.pid == pid).group_by(SubPostPollOption.id)
            pollData['options'] = options
            total_votes = SubPostPollVote.select().where(SubPostPollVote.pid == pid).count()
            pollData['total_votes'] = total_votes
            if current_user.is_authenticated:
                # Check if user has already voted on this poll.
                try:
                    u_vote = SubPostPollVote.get((SubPostPollVote.pid == pid) & (SubPostPollVote.uid == current_user.uid))
                    pollData['has_voted'] = True
                    pollData['voted_for'] = u_vote.vid_id
                except SubPostPollVote.DoesNotExist:
                    pollData['has_voted'] = False
                
            # Check if the poll is open
            pollData['poll_open'] = True
            if 'poll_closed' in postmeta:
                pollData['poll_open'] = False

            if 'poll_closes_time' in postmeta:
                pollData['poll_closes'] = datetime.datetime.utcfromtimestamp(int(postmeta['poll_closes_time'])).isoformat()
                if int(postmeta['poll_closes_time']) < time.time():
                    pollData['poll_open'] = False

            cont = engine.get_template('sub/postpoll.html').render({'post': post, 'pollData': pollData, 'postmeta': postmeta})

        return jsonify(status='ok', content=cont)
    except SubPost.DoesNotExist:
        return jsonify(status='error', error=['No longer available'])


@do.route("/do/edit_txtpost/<pid>", methods=['POST'])
@login_required
def edit_txtpost(pid):
    """ Sub text post creation endpoint """
    form = EditSubTextPostForm()
    if form.validate():
        try:
            post = SubPost.get(SubPost.pid == pid)
        except SubPost.DoesNotExist:
            return jsonify(status='error', error=['Post not found'])

        if post.deleted != 0:
            return jsonify(status='error', error=['Post was deleted'])

        if current_user.is_subban(post.sid):
            return jsonify(status='error', error=['You are banned on this sub.'])

        post.content = form.content.data
        # Only save edited time if it was posted more than five minutes ago
        if (datetime.datetime.utcnow() - post.posted.replace(tzinfo=None)).seconds > 300:
            post.edited = datetime.datetime.utcnow()
        post.save()
        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/grabtitle", methods=['POST'])
@login_required
def grab_title():
    """ Safely grabs the <title> from a page """
    url = request.json.get('u')
    if not url:
        abort(400)
    try:
        req = misc.safeRequest(url)
    except (requests.exceptions.RequestException, ValueError):
        return jsonify(status='error', error=['Couldn\'t get title'])

    og = BeautifulSoup(req[1], 'lxml', from_encoding='utf-8')
    try:
        title = og('title')[0].text
    except (OSError, ValueError, IndexError):
        return jsonify(status='error', error=['Couldn\'t get title'])
    
    title = title.strip(misc.WHITESPACE)
    title = re.sub(' - Youtube$', '', title)
    return jsonify(status='ok', title=title)


def post_over_limit(limit):
    form = CreateSubTextPost()
    return render_template('createpost.html', txtpostform=form, error='Wait a bit before posting.')


@do.route("/do/post", methods=['POST'])
@login_required
@misc.ratelimit(1, per=30, over_limit=post_over_limit)
def create_post():
    """ Sub link post creation endpoint """
    if misc.get_user_level(current_user.uid)[0] <= 4:
        form = forms.CreteSubPostCaptcha()
        if not form.validate():
            if not misc.validate_captcha(form.ctok.data, form.captcha.data):
                return render_template('createpost.html', txtpostform=form, error="Invalid captcha."), 400
            return render_template('createpost.html', txtpostform=form, error=get_errors(form)[0])
    form = CreateSubTextPost()
    if form.validate():
        # Put pre-posting checks here
        if not current_user.is_admin():
            try:
                enable_posting = SiteMetadata.get(SiteMetadata.key == 'enable_posting')
                if enable_posting.value in ('False', '0'):
                    return render_template('createpost.html', txtpostform=form, error="Posting has been temporarily disabled"), 400
            except SiteMetadata.DoesNotExist:
                pass
        
        try:
            sub = Sub.get(fn.Lower(Sub.name) == form.sub.data.lower())
        except:
            return render_template('createpost.html', txtpostform=form, error="Sub does not exist"), 400
        
        subdata = misc.getSubData(sub.sid)

        if sub.name.lower() in ('all', 'new', 'hot', 'top', 'admin', 'home'):
            return render_template('createpost.html', txtpostform=form, error="You cannot post in this sub."), 400
        if current_user.is_subban(sub):
            return render_template('createpost.html', txtpostform=form, error="You're banned from posting on this sub"), 400
        
        submods = misc.getSubMods(sub.sid)
        if subdata.get('restricted', 0) == '1' and not (current_user.uid in submods['all']):
            return render_template('createpost.html', txtpostform=form, error="Only mods can post on this sub"), 400

        if misc.get_user_level(current_user.uid)[0] < 7:
            today = datetime.datetime.utcnow() - datetime.timedelta(days=1)
            lposts = SubPost.select().where(SubPost.uid == current_user.uid).where(SubPost.sid == sub.sid).where(SubPost.posted > today).count()
            tposts = SubPost.select().where(SubPost.uid == current_user.uid).where(SubPost.posted > today).count()
            if lposts > 10 or tposts > 25:
                return render_template('createpost.html', txtpostform=form, error="You have posted too much today"), 400
        if len(form.title.data.strip(misc.WHITESPACE)) < 3:
            return render_template('createpost.html', txtpostform=form, error="Title is too short and/or contains whitespace characters"), 400
        fileid = False
        if form.ptype.data == 'link':
            fupload = misc.upload_file()
            if fupload:
                form.link.data = config.storage.uploads.url + fupload
                fileid = fupload

            if not form.link.data:
                return render_template('createpost.html', txtpostform=form, error="No link provided"), 400

            try:
                lx = SubPost.select(SubPost.pid).where(SubPost.sid == sub.sid)
                lx = lx.where(SubPost.link == form.link.data).where(SubPost.deleted == 0)
                monthago = datetime.datetime.utcnow() - datetime.timedelta(days=30)
                lx = lx.where(SubPost.posted > monthago).get()
                return render_template('createpost.html', txtpostform=form, error="This link was recently posted on this sub"), 400

            except SubPost.DoesNotExist:
                pass
            
            if misc.is_domain_banned(form.link.data.lower()):
                return render_template('createpost.html', txtpostform=form, error="This domain is banned"), 400

            img = misc.get_thumbnail(form.link.data)
        if form.ptype.data == 'poll':
            ptype = 3
            # Check if this sub allows polls...
            if not subdata.get('allow_polls', False):
                return render_template('createpost.html', txtpostform=form, error="This sub does not allow polling"), 400
            # check if we got at least three options
            options = request.form.getlist('op[]')
            options = [x for x in options if len(x.strip(misc.WHITESPACE)) > 0]  # Remove empty strings
            if len(options) < 2:
                return render_template('createpost.html', txtpostform=form, error="Not enough poll options provided"), 400
            
            for p in options:
                if len(p) > 128:
                    return render_template('createpost.html', txtpostform=form, error="Poll option text is too long."), 400
            
            if form.closetime.data:
                try:
                    closetime = datetime.datetime.strptime(form.closetime.data, "%Y-%m-%dT%H:%M:%S.%fZ")
                    if (closetime - datetime.datetime.utcnow()) > datetime.timedelta(days=60):
                        return render_template('createpost.html', txtpostform=form, error="Poll closing time is too far in the future."), 400
                except ValueError:
                    return render_template('createpost.html', txtpostform=form, error="Invalid closing time."), 400
                
                if datetime.datetime.utcnow() > closetime:
                    return render_template('createpost.html', txtpostform=form, error="The closing time is in the past!"), 400
        elif form.ptype.data == 'link':
            ptype = 1
        else:
            ptype = 0

        post = SubPost.create(sid=sub.sid,
                              uid=current_user.uid,
                              title=form.title.data,
                              content=form.content.data if ptype != 1 else '',
                              link=form.link.data if ptype == 1 else None,
                              posted=datetime.datetime.utcnow(),
                              score=1, upvotes=1, downvotes=0,
                              deleted=0,
                              comments=0,
                              ptype=ptype,
                              nsfw=form.nsfw.data if not sub.nsfw else 1,
                              thumbnail=img if ptype == 1 else '')
        
        if ptype == 3:
            # Create SubPostPollOption objects...
            poll_options = [{'pid': post.pid, 'text': x} for x in options]
            SubPostPollOption.insert_many(poll_options).execute()
            # apply all poll options..
            if form.hideresults.data:
                SubPostMetadata.create(pid=post.pid, key='hide_results', value=1)
            
            if form.closetime.data:
                SubPostMetadata.create(pid=post.pid, key='poll_closes_time', value=int(closetime.replace(tzinfo=datetime.timezone.utc).timestamp()))
        
        Sub.update(posts=Sub.posts + 1).where(Sub.sid == sub.sid).execute()
        addr = url_for('sub.view_post', sub=sub.name, pid=post.pid)
        posts = misc.getPostList(misc.postListQueryBase(nofilter=True).where(SubPost.pid == post.pid), 'new', 1).dicts()
        socketio.emit('thread',
                      {'addr': addr, 'sub': sub.name, 'type': form.ptype.data,
                       'user': current_user.name, 'pid': post.pid, 'sid': sub.sid,
                       'html': engine.get_template('shared/post.html').render({'posts': posts, 'sub': False})},
                      namespace='/snt',
                      room='/all/new')

        # XXX: The auto-upvote is placed *after* broadcasting the post via socketio so that the upvote arrow
        # does not appear highlighted to everybody.
        SubPostVote.create(uid=current_user.uid, pid=post.pid, positive=True)
        User.update(given=User.given + 1).where(User.uid == current_user.uid).execute()
        # We send a yourvote message so that the upvote arrow *does* appear highlighted to the creator.
        socketio.emit('yourvote', {'pid': post.pid, 'status': 1, 'score': post.score}, namespace='/snt',
                      room='user' + current_user.uid)

        if fileid:
            UserUploads.create(pid=post.pid, uid=current_user.uid, fileid=fileid, thumbnail=img if img else '', status=0)

        misc.workWithMentions(form.content.data, None, post, sub)
        misc.workWithMentions(form.title.data, None, post, sub)
        return redirect(addr)
    return render_template('createpost.html', txtpostform=form, error=get_errors(form)[0]), 400


@do.route('/do/sendcomment/<pid>', methods=['POST'])
@login_required
@misc.ratelimit(1, per=30)  # Once every 30 secs
def create_comment(pid):
    """ Here we send comments. """
    form = PostComment()
    if form.validate():
        if pid == '0':
            pid = form.post.data

        try:
            post = SubPost.get(SubPost.pid == pid)
        except SubPost.DoesNotExist:
            return jsonify(status='error', error=['Post does not exist']), 400
        if post.deleted:
            return jsonify(status='error', error=['Post was deleted']), 400

        if (datetime.datetime.utcnow() - post.posted.replace(tzinfo=None)) > datetime.timedelta(days=60):
            return jsonify(status='error', error=["Post is archived"]), 400

        try:
            sub = Sub.get(Sub.sid == post.sid_id)
        except:
            return jsonify(status='error', error='Internal error'), 400
        if current_user.is_subban(sub):
            return jsonify(status='error', error=['You are currently banned from commenting']), 400

        if form.parent.data != '0':
            try:
                parent = SubPostComment.get(SubPostComment.cid == form.parent.data)
            except SubPostComment.DoesNotExist:
                return jsonify(status='error', error=["Parent comment does not exist"]), 400

            # XXX: We check both for None and 0 because I've found both on a Phuks snapshot...
            if (parent.status is not None and parent.status != 0) or parent.pid.pid != post.pid:
                return jsonify(status='error', error=["Parent comment does not exist"]), 400

        comment = SubPostComment.create(pid=pid, uid=current_user.uid,
                                        content=form.comment.data.encode(),
                                        parentcid=form.parent.data if form.parent.data != '0' else None,
                                        time=datetime.datetime.utcnow(),
                                        cid=uuid.uuid4(), score=0, upvotes=0, downvotes=0)
        
        SubPost.update(comments=SubPost.comments + 1).where(SubPost.pid == post.pid).execute()
        comment.save()

        socketio.emit('threadcomments',
                      {'pid': post.pid,
                       'comments': post.comments + 1},
                      namespace='/snt',
                      room=post.pid)

        # 5 - send pm to parent
        if form.parent.data != "0":
            parent = SubPostComment.get(SubPostComment.cid == form.parent.data)
            to = parent.uid.uid
            subject = 'Comment reply: ' + post.title
            mtype = 5
        else:
            to = post.uid.uid
            subject = 'Post reply: ' + post.title
            mtype = 4
        if to != current_user.uid and current_user.uid not in misc.get_ignores(to):
            misc.create_message(mfrom=current_user.uid,
                                to=to,
                                subject=subject,
                                content='',
                                link=comment.cid,
                                mtype=mtype)
            socketio.emit('notification',
                          {'count': misc.get_notification_count(to)},
                          namespace='/snt',
                          room='user' + to)

        # 6 - Process mentions
        misc.workWithMentions(form.comment.data, to, post, sub, cid=comment.cid)
        renderedComment = engine.get_template('sub/postcomments.html').render({
            'post': misc.getSinglePost(post.pid),
            'comments': misc.get_comment_tree([{'cid': str(comment.cid), 'parentcid': None}], uid=current_user.uid),
            'subInfo': misc.getSubData(sub.sid),
            'subMods': misc.getSubMods(sub.sid),
            'highlight': str(comment.cid)
        })

        return json.dumps({'status': 'ok', 'addr': url_for('sub.view_perm', sub=sub.name, pid=pid, cid=comment.cid),
                           'comment': renderedComment, 'cid': str(comment.cid)})
    return json.dumps({'status': 'error', 'error': get_errors(form)}), 400


@do.route("/do/sendmsg", methods=['POST'])
@login_required
def create_sendmsg():
    """ User PM message creation endpoint """
    form = CreateUserMessageForm()
    if form.validate():
        try:
            user = User.get(fn.Lower(User.name) == form.to.data.lower())
        except:
            return json.dumps({'status': 'error', 'error': ['User does not exist']})
        misc.create_message(mfrom=current_user.uid,
                            to=user.uid,
                            subject=form.subject.data,
                            content=form.content.data,
                            link=None,
                            mtype=1 if current_user.uid not in misc.get_ignores(user.uid) else 41)
        socketio.emit('notification',
                      {'count': misc.get_notification_count(user.uid)},
                      namespace='/snt',
                      room='user' + user.uid)
        return json.dumps({'status': 'ok',
                           'sentby': current_user.get_id()})
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/ban_user_sub/<sub>", methods=['POST'])
@login_required
def ban_user_sub(sub):
    """ Ban user from sub endpoint """
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=['Sub does not exist'])
        
    if not current_user.is_mod(sub.sid, 2):
        return jsonify(status='error', error=['Not authorized'])
    form = BanUserSubForm()
    if form.validate():
        try:
            user = User.get(fn.Lower(User.name) == form.user.data.lower())
        except User.DoesNotExist:
            return jsonify(status='error', error=['User does not exist'])

        # XXX: This is all SDBH does so it stays commented out for now
        #try:
        #    SubMod.get((SubMod.sid == sub.sid) & (SubMod.uid == user.uid))
        #    return jsonify(status='error', error=['User is a moderator'])
        #except SubMod.DoesNotExist:
        #    pass
        
        expires = None
        if form.expires.data:
            try:
                expires = datetime.datetime.strptime(form.expires.data, "%Y-%m-%dT%H:%M:%S.%fZ")
                if (expires - datetime.datetime.utcnow()) > datetime.timedelta(days=365):
                    return jsonify(status='error', error=['Expiration time too far into the future'])
            except ValueError:
                return jsonify(status='error', error=['Invalid expiration time'])
            
            if datetime.datetime.utcnow() > expires:
                return jsonify(status='error', error=['Expiration date is in the past'])

        if expires is None:
            if not current_user.is_mod(sub.sid, 1):
                return jsonify(status='error', error=['Janitors may only create temporary bans'])

        if misc.is_sub_banned(sub, uid=user.uid):
            return jsonify(status='error', error=['Already banned'])
            
        misc.create_message(mfrom=current_user.uid,
                            to=user.uid,
                            subject='You have been banned from /s/' + sub.name,
                            content='Reason: ' + form.reason.data,
                            link=sub.name,
                            mtype=7)
        socketio.emit('notification',
                      {'count': misc.get_notification_count(user.uid)},
                      namespace='/snt',
                      room='user' + user.uid)
        
        SubBan.create(sid=sub.sid, uid=user.uid, reason=form.reason.data, created_by=current_user.uid, expires=expires)

        misc.create_sublog(misc.LOG_TYPE_SUB_BAN, current_user.uid, sub.sid, target=user.uid, comment=form.reason.data)
        cache.delete_memoized(misc.is_sub_banned, sub, uid=user.uid)
        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/inv_mod/<sub>", methods=['POST'])
@login_required
def inv_mod(sub):
    """ User PM for Mod2 invite endpoint """
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=['Sub does not exist'])

    try:
        SubMod.get((SubMod.sid == sub.sid) & (SubMod.uid == current_user.uid) & (SubMod.power_level == 0) & (SubMod.invite == False))
        is_owner = True
    except SubMod.DoesNotExist:
        is_owner = False

    if is_owner or current_user.is_admin():
        form = EditMod2Form()
        if form.validate():
            try:
                user = User.get(fn.Lower(User.name) == form.user.data.lower())
            except User.DoesNotExist:
                return jsonify(status='error', error=['User does not exist'])

            try:
                SubMod.get((SubMod.sid == sub.sid) & (SubMod.uid == user.uid) & (SubMod.invite == False))
                return jsonify(status='error', error=['User is already a mod'])
            except SubMod.DoesNotExist:
                pass

            try:
                SubMod.get((SubMod.sid == sub.sid) & (SubMod.uid == user.uid) & (SubMod.invite == True))
                return jsonify(status='error', error=['User has a pending invite'])
            except SubMod.DoesNotExist:
                pass
            
            if form.level.data in ('1', '2'):
                power_level = int(form.level.data)
            else:
                return jsonify(status='error', error=['Invalid power level'])

            moddedCount = SubMod.select().where((SubMod.uid == user.uid) & (1 <= SubMod.power_level <= 2) & (SubMod.invite == False)).count()
            if moddedCount >= 20:
                # TODO: Adjust by level
                return jsonify(status='error', error=["User can't mod more than 20 subs"])
            misc.create_message(mfrom=current_user.uid,
                                to=user.uid,
                                subject='You have been invited to mod a sub.',
                                content=current_user.name + ' has invited you to be a ' + ('moderator' if power_level == 1 else 'janitor') + ' in ' + sub.name,
                                link=sub.name,
                                mtype=2)
            socketio.emit('notification',
                          {'count': misc.get_notification_count(user.uid)},
                          namespace='/snt',
                          room='user' + user.uid)
            
            SubMod.create(sid=sub.sid, user=user.uid, power_level=power_level, invite=True)

            misc.create_sublog(misc.LOG_TYPE_SUB_MOD_INVITE, current_user.uid, sub.sid, target=user.uid,
                               admin=True if (not is_owner and current_user.is_admin()) else False)

            return jsonify(status='ok')
        return json.dumps({'status': 'error', 'error': get_errors(form)})
    else:
        abort(403)


@do.route("/do/remove_sub_ban/<sub>/<user>", methods=['POST'])
@login_required
def remove_sub_ban(sub, user):
    try:
        user = User.get(fn.Lower(User.name) == user.lower())
    except User.DoesNotExist:
        return jsonify(status='error', error=['User does not exist'])
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=['Sub does not exist'])
    form = DummyForm()
    if form.validate():
        if current_user.is_mod(sub.sid, 2) or current_user.is_admin():
            try:
                sb = SubBan.get((SubBan.sid == sub.sid) & 
                                (SubBan.uid == user.uid) & 
                                ((SubBan.effective == True) & ((SubBan.expires.is_null(True)) | (SubBan.expires > datetime.datetime.utcnow()) )) )
            except SubBan.DoesNotExist:
                return jsonify(status='error', error=['User is not banned'])
            
            if not current_user.is_mod(sub.sid, 1) and sb.created_by_id != current_user.uid:
                return jsonify(status='error', error=['Janitors may only remove bans placed by themselves'])

            sb.effective = False
            sb.expires = datetime.datetime.utcnow()
            sb.save()

            misc.create_message(mfrom=current_user.uid,
                                to=user.uid,
                                subject='You have been unbanned from /s/' + sub.name,
                                content='', mtype=7,
                                link=sub.name)
            socketio.emit('notification',
                          {'count': misc.get_notification_count(user.uid)},
                          namespace='/snt',
                          room='user' + user.uid)
            
            misc.create_sublog(misc.LOG_TYPE_SUB_UNBAN, current_user.uid, sub.sid, target=user.uid,
                               admin=True if (not current_user.is_mod(sub.sid, 1) and current_user.is_admin()) else False)
            cache.delete_memoized(misc.is_sub_banned, sub, uid=user.uid)
            return jsonify(status='ok', msg='Ban removed')
        else:
            abort(403)
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/remove_mod2/<sub>/<user>", methods=['POST'])
@login_required
def remove_mod2(sub, user):
    """ Remove Mod2 """
    try:
        user = User.get(fn.Lower(User.name) == user.lower())
    except User.DoesNotExist:
        return jsonify(status='error', error=['User does not exist'])
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=['Sub does not exist'])
    form = DummyForm()
    if form.validate():
        isTopMod = current_user.is_mod(sub.sid, 0)
        if isTopMod or current_user.is_admin() or (current_user.uid == user.uid and current_user.is_mod(sub.sid)):
            try:
                mod = SubMod.get((SubMod.sid == sub.sid) & (SubMod.uid == user.uid) & (SubMod.power_level != 0) & (SubMod.invite == False))
            except SubMod.DoesNotExist:
                return jsonify(status='error', error=['User is not mod'])
            
            mod.delete_instance()
            SubMetadata.create(sid=sub.sid, key='xmod2', value=user.uid).save()

            misc.create_sublog(misc.LOG_TYPE_SUB_MOD_REMOVE, current_user.uid, sub.sid, target=user.uid,
                               admin=True if (not isTopMod and current_user.is_admin()) else False)

            return jsonify(status='ok', resign=True if current_user.uid == user.uid else False)
        else:
            return jsonify(status='error', error=['Access denied'])
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/revoke_mod2inv/<sub>/<user>", methods=['POST'])
@login_required
def revoke_mod2inv(sub, user):
    """ revoke Mod2 inv """
    try:
        user = User.get(fn.Lower(User.name) == user.lower())
    except User.DoesNotExist:
        return jsonify(status='error', error=['User does not exist'])
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=['Sub does not exist'])
    form = DummyForm()
    if form.validate():
        isTopMod = current_user.is_mod(sub.sid, 0)
        if isTopMod or current_user.is_admin():
            try:
                x = SubMod.get((SubMod.sid == sub.sid) & (SubMod.uid == user.uid) & (SubMod.invite == True))
            except SubMetadata.DoesNotExist:
                return jsonify(status='error', error=['User has not been invited to moderate the sub'])
            x.delete_instance()

            misc.create_sublog(misc.LOG_TYPE_SUB_MOD_INV_CANCEL, current_user.uid, sub.sid, target=user.uid,
                               admin=True if (not isTopMod and current_user.is_admin()) else False)

            return jsonify(status='ok')
        else:
            return jsonify(status='error', error=['Access denied'])
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/accept_modinv/<sub>/<user>", methods=['POST'])
@login_required
def accept_modinv(sub, user):
    """ Accept mod invite """
    try:
        user = User.get(fn.Lower(User.name) == user.lower())
    except User.DoesNotExist:
        return jsonify(status='error', error=['User does not exist'])
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=['Sub does not exist'])
    form = DummyForm()
    if form.validate():
        try:
            modi = SubMod.get((SubMod.sid == sub.sid) & (SubMod.uid == user.uid) & (SubMod.invite == True))
        except SubMod.DoesNotExist:
            return jsonify(status='error', error='You have not been invited to mod this sub')

        moddedCount = SubMod.select().where((SubMod.uid == user.uid) & (1 <= SubMod.power_level <= 2) & (SubMod.invite == False)).count()
        if moddedCount >= 20:
            return jsonify(status='error', error=["You can't mod more than 20 subs"])

        modi.invite = False
        modi.save()
        SubMetadata.delete().where((SubMetadata.sid == sub.sid) & (SubMetadata.key == 'xmod2') & (SubMetadata.value == user.uid)).execute()

        misc.create_sublog(misc.LOG_TYPE_SUB_MOD_ACCEPT, current_user.uid, sub.sid, target=user.uid)

        if not current_user.has_subscribed(sub.name):
            SubSubscriber.create(uid=current_user.uid, sid=sub.sid, status=1)
        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/refuse_mod2inv/<sub>", methods=['POST'])
@login_required
def refuse_mod2inv(sub):
    """ refuse Mod2 """
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=['Sub does not exist'])

    form = DummyForm()
    if form.validate():
        try:
            modi = SubMod.get((SubMod.sid == sub.sid) & (SubMod.uid == current_user.uid) & (SubMod.invite == True))
        except SubMetadata.DoesNotExist:
            return jsonify(status='error', error='You have not been invited to mod this sub')

        modi.delete_instance()
        misc.create_sublog(misc.LOG_TYPE_SUB_MOD_INV_REJECT, current_user.uid, sub.sid, target=current_user.uid)
        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/read_pm/<mid>", methods=['POST'])
@login_required
def read_pm(mid):
    """ Mark PM as read """
    try:
        message = Message.get(Message.mid == mid)
    except Message.DoesNotExist:
        return jsonify(status='error', error=['Message not found'])

    if current_user.uid == message.receivedby_id:
        if message.read is not None:
            return jsonify(status='ok')
        message.read = datetime.datetime.utcnow()
        message.save()
        socketio.emit('notification',
                      {'count': current_user.notifications},
                      namespace='/snt',
                      room='user' + current_user.uid)
        return jsonify(status='ok', mid=mid)
    else:
        return jsonify(status='error')


@do.route("/do/readall_msgs/<boxid>", methods=['POST'])
@login_required
def readall_msgs(boxid):
    """ Mark all messages in a box as read """
    now = datetime.datetime.utcnow()
    q = Message.update(read=now).where(Message.read.is_null()).where(Message.receivedby == current_user.uid)
    q.where(Message.mtype == boxid).execute()
    socketio.emit('notification',
                  {'count': current_user.notifications},
                  namespace='/snt',
                  room='user' + current_user.uid)
    return jsonify(status='ok')


@do.route("/do/delete_pm/<mid>", methods=['POST'])
@login_required
def delete_pm(mid):
    """ Delete PM """
    try:
        message = Message.get(Message.mid == mid)
        if message.receivedby_id != current_user.uid:
            return jsonify(status='error', error="Message does not exist")
        
        message.mtype = 6
        message.save()
        return jsonify(status='ok')
    except Message.DoesNotExist:
        return jsonify(status='error', error="Message does not exist")


@do.route("/do/edit_title", methods=['POST'])
@login_required
def edit_title():
    form = DeletePost()
    if form.validate():
        if not form.reason.data:
            return jsonify(status="error", error="Missing title")

        if len(form.reason.data.strip(misc.WHITESPACE)) < 3:
            return jsonify(status="error", error="Title too short.")

        try:
            post = SubPost.get(SubPost.pid == form.post.data)
        except SubPost.DoesNotExist:
            return jsonify(status="error", error="Post does not exist")
        sub = Sub.get(Sub.sid == post.sid)
        if current_user.is_subban(sub):
            return jsonify(status='error', error='You are banned on this sub.')

        if (datetime.datetime.utcnow() - post.posted.replace(tzinfo=None)) > datetime.timedelta(seconds=config.site.title_edit_timeout):
            return jsonify(status="error", error="You cannot edit the post title anymore")

        if post.uid.uid != current_user.uid:
            return jsonify(status="error", error="You did not post this!")

        post.title = form.reason.data
        post.save()
        socketio.emit('threadtitle', {'pid': post.pid, 'title': form.reason.data},
                      namespace='/snt', room=post.pid)

        return jsonify(status="ok")
    return jsonify(status="error", error="Bork bork")


@do.route("/do/save_pm/<mid>", methods=['POST'])
@login_required
def save_pm(mid):
    """ Save/Archive PM """
    try:
        message = Message.get(Message.mid == mid)
        if message.receivedby_id != current_user.uid:
            return jsonify(status='error', error="Message does not exist")
        
        message.mtype = 9
        message.save()
        return jsonify(status='ok')
    except Message.DoesNotExist:
        return jsonify(status='error', error="Message does not exist")


@do.route("/do/admin/deleteannouncement")
@login_required
def deleteannouncement():
    """ Removes the current announcement """
    if not current_user.is_admin():
        abort(403)

    try:
        ann = SiteMetadata.get(SiteMetadata.key == 'announcement')
        post = SubPost.get(SubPost.pid == ann.value)
    except SiteMetadata.DoesNotExist:
        return redirect(url_for('admin_area'))

    ann.delete_instance()
    misc.create_sitelog(misc.LOG_TYPE_UNANNOUNCE, uid=current_user.uid, link=url_for('sub.view_post', sub=post.sid.name, pid=post.pid))

    cache.delete_memoized(misc.getAnnouncementPid)
    socketio.emit('rmannouncement', {}, namespace='/snt')
    return redirect(url_for('admin_area'))


@do.route("/do/makeannouncement", methods=['POST'])
def make_announcement():
    """ Flagging post as announcement - not api """
    if not current_user.is_admin():
        abort(403)

    form = DeletePost()

    if form.validate():
        try:
            curr_ann = SiteMetadata.get(SiteMetadata.key == 'announcement')
            if curr_ann.value == form.post.data:
                return jsonify(status='error', error='Post already announced')
            deleteannouncement()
        except SiteMetadata.DoesNotExist:
            pass

        try:
            post = SubPost.get(SubPost.pid == form.post.data)
        except SubPost.DoesNotExist:
            return jsonify(status='error', error='Post does not exist')

        SiteMetadata.create(key='announcement', value=post.pid)

        misc.create_sitelog(misc.LOG_TYPE_ANNOUNCEMENT, uid=current_user.uid, link=url_for('sub.view_post', sub=post.sid.name, pid=post.pid))

        cache.delete_memoized(misc.getAnnouncementPid)
        socketio.emit('announcement',
                      {"cont": engine.get_template('shared/announcement.html').render({"ann": misc.getAnnouncement()})},
                      namespace='/snt')
        return jsonify(status='ok')
    return jsonify(status='error', error=get_errors(form))


@do.route("/do/ban_domain", methods=['POST'])
def ban_domain():
    """ Add domain to ban list """
    if not current_user.is_admin():
        abort(403)

    form = BanDomainForm()

    if form.validate():
        try:
            sm = SiteMetadata.get((SiteMetadata.key == 'banned_domain') & (SiteMetadata.value == form.domain.data))
            return jsonify(status='error', error=['Domain is already banned'])
        except SiteMetadata.DoesNotExist:
            sm = SiteMetadata.create(key='banned_domain', value=form.domain.data)
            sm.save()
            misc.create_sitelog(misc.LOG_TYPE_DOMAIN_BAN, current_user.uid, comment=form.domain.data)
            return jsonify(status='ok')

    return jsonify(status='error', error=get_errors(form))


@do.route("/do/remove_banned_domain/<domain>", methods=['POST'])
def remove_banned_domain(domain):
    """ Remove domain if ban list """
    if not current_user.is_admin():
        abort(403)

    try:
        sm = SiteMetadata.get((SiteMetadata.key == 'banned_domain') & (SiteMetadata.value == domain))
        sm.delete_instance()
    except:
        return jsonify(status='error', error='Domain is not banned')

    misc.create_sitelog(misc.LOG_TYPE_DOMAIN_UNBAN, current_user.uid, comment=domain)

    return json.dumps({'status': 'ok'})


@do.route("/do/admin/enable_posting/<value>")
def enable_posting(value):
    """ Emergency Mode: disable posting """
    if not current_user.is_admin():
        abort(404)
    
    if value == 'True':
        state = '1'
    elif value == 'False':
        state = '0'
    else:
        abort(400)

    try:
        sm = SiteMetadata.get(SiteMetadata.key == 'enable_posting')
        sm.value = state
        sm.save()
    except SiteMetadata.DoesNotExist:
        SiteMetadata.create(key='enable_posting', value=state)

    if value == 'True':
        misc.create_sitelog(misc.LOG_TYPE_ENABLE_POSTING, current_user.uid)
    else:
        misc.create_sitelog(misc.LOG_TYPE_DISABLE_POSTING, current_user.uid)

    return redirect(url_for('admin_area'))


@do.route("/do/save_post/<pid>", methods=['POST'])
def save_post(pid):
    """ Save a post to your Saved Posts """
    try:
        SubPost.get(SubPost.pid == pid)
    except:
        return jsonify(status='error', error=['Post does not exist'])
    try:
        UserSaved.get((UserSaved.uid == current_user.uid) & (UserSaved.pid == pid))
        return jsonify(status='error', error=['Already saved'])
    except UserSaved.DoesNotExist:
        UserSaved.create(uid=current_user.uid, pid=pid)
        return jsonify(status='ok')


@do.route("/do/remove_saved_post/<pid>", methods=['POST'])
def remove_saved_post(pid):
    """ Remove a saved post """
    try:
        SubPost.get(SubPost.pid == pid)
    except:
        return jsonify(status='error', error=['Post does not exist'])

    try:
        sp = UserSaved.get((UserSaved.uid == current_user.uid) & (UserSaved.pid == pid))
        sp.delete_instance()
        return jsonify(status='ok')
    except UserSaved.DoesNotExist:
        return jsonify(status='error', error=['Post was not saved'])


@do.route("/do/useinvitecode", methods=['POST'])
def use_invite_code():
    """ Enable invite code to register """
    if not current_user.is_admin():
        abort(404)

    form = UseInviteCodeForm()
    
    if form.validate():
        try:
            sm = SiteMetadata.get(SiteMetadata.key == 'useinvitecode')
            sm.value = '1' if form.enableinvitecode.data else '0'
            sm.save()
        except SiteMetadata.DoesNotExist:
            SiteMetadata.create(key='useinvitecode', value='1' if form.enableinvitecode.data else '0')

        try:
            sm = SiteMetadata.get(SiteMetadata.key == 'invite_level')
            sm.value = form.minlevel.data
            sm.save()
        except SiteMetadata.DoesNotExist:
            SiteMetadata.create(key='invite_level', value=form.minlevel.data)
        
        try:
            sm = SiteMetadata.get(SiteMetadata.key == 'invite_max')
            sm.value = form.maxcodes.data
            sm.save()
        except SiteMetadata.DoesNotExist:
            SiteMetadata.create(key='invite_max', value=form.maxcodes.data)
        
        cache.delete_memoized(misc.enableInviteCode)

        if form.enableinvitecode.data:
            misc.create_sitelog(misc.LOG_TYPE_ENABLE_INVITE, current_user.uid)
        else:
            misc.create_sitelog(misc.LOG_TYPE_DISABLE_INVITE, current_user.uid)
    return jsonify(status="ok")


@do.route("/do/create_invite")
@login_required
def invite_codes():
    if not misc.enableInviteCode():
        return redirect('/settings')
    
    created = InviteCode.select().where(InviteCode.user == current_user.uid).count()
    maxcodes = int(misc.getMaxCodes(current_user.uid))
    if (maxcodes - created) <= 0:
        return redirect('/settings/invite')
    
    code = ''.join(random.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(32))
    InviteCode.create(user=current_user.uid, code=code, expires=None, max_uses=1)
    return redirect('/settings/invite')

@do.route("/do/stick/<int:post>", methods=['POST'])
def toggle_sticky(post):
    """ Toggles post stickyness """
    try:
        post = SubPost.get(SubPost.pid == post)
    except SubPost.DoesNotExist:
        return jsonify(status='error', error='Post does not exist')
    

    if not current_user.is_mod(post.sid_id):
        abort(403)

    form = DeletePost()

    if form.validate():
        try:
            is_sticky = SubMetadata.get((SubMetadata.sid == post.sid_id) & (SubMetadata.key == 'sticky') & (SubMetadata.value == post.pid))
            is_sticky.delete_instance()
            misc.create_sublog(misc.LOG_TYPE_SUB_STICKY_DEL, current_user.uid, post.sid,
                               link=url_for('sub.view_post', sub=post.sid.name, pid=post.pid))
        except SubMetadata.DoesNotExist:
            post.sid.update_metadata('sticky', post.pid)
            misc.create_sublog(misc.LOG_TYPE_SUB_STICKY_ADD, current_user.uid, post.sid,
                    link=url_for('sub.view_post', sub=post.sid.name, pid=post.pid))

        cache.delete_memoized(misc.getStickyPid, post.sid_id)
    return jsonify(status='ok')


@do.route("/do/wikipost/<int:post>", methods=['POST'])
def toggle_wikipost(post):
    """ Toggles post to the sub wiki page """
    try:
        post = SubPost.get(SubPost.pid == post)
    except SubPost.DoesNotExist:
        return jsonify(status='error', error='Post does not exist')


    if not current_user.is_mod(post.sid_id):
        abort(403)

    form = DeletePost()

    if form.validate():
        try:
            is_wiki = SubMetadata.get((SubMetadata.sid == post.sid_id) & (SubMetadata.key == 'wiki') & (SubMetadata.value == post.pid))
            is_wiki.delete_instance()
            #  TODO Log it
            #misc.create_sublog(misc.LOG_TYPE_SUB_STICKY_DEL, current_user.uid, post.sid,
            #                   link=url_for('sub.view_post', sub=post.sid.name, pid=post.pid))
        except SubMetadata.DoesNotExist:
            post.sid.update_metadata('wiki', post.pid)
            #  TODO Log it
            #misc.create_sublog(misc.LOG_TYPE_SUB_STICKY_ADD, current_user.uid, post.sid,
            #        link=url_for('sub.view_post', sub=post.sid.name, pid=post.pid))

        cache.delete_memoized(misc.getWikiPid, post.sid_id)
    return jsonify(status='ok')


@do.route("/do/flair/<sub>/delete", methods=['POST'])
@login_required
def delete_flair(sub):
    """ Removes a flair (from edit flair page) """
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        return jsonify(status='error', error=['Sub does not exist'])

    if not current_user.is_mod(sub.sid, 1) and not current_user.is_admin():
        abort(403)

    form = DeleteSubFlair()
    if form.validate():
        try:
            flair = SubFlair.get((SubFlair.sid == sub.sid) & (SubFlair.xid == form.flair.data))
        except SubFlair.DoesNotExist:
            return jsonify(status='error', error=['Flair does not exist'])
        
        flair.delete_instance()
        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/flair/<sub>/create", methods=['POST'])
@login_required
def create_flair(sub):
    """ Creates a new flair (from edit flair page) """
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        abort(404)

    if not current_user.is_mod(sub.sid, 1) and not current_user.is_admin():
        abort(403)

    form = CreateSubFlair()
    if form.validate():
        allowed_flairs = re.compile("^[a-zA-Z0-9._ -]+$")
        if not allowed_flairs.match(form.text.data):
            return jsonify(status='error', error=['Flair has invalid characters'])

        SubFlair.create(sid=sub.sid, text=form.text.data)
        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/recovery", methods=['POST'])
def recovery():
    """ Password recovery page. Email+captcha and sends recovery email """
    if current_user.is_authenticated:
        abort(403)

    form = forms.PasswordRecoveryForm()
    form.cap_key, form.cap_b64 = misc.create_captcha()
    if form.validate():
        if not misc.validate_captcha(form.ctok.data, form.captcha.data):
            # XXX: Fix this
            return jsonify(status='error', error=["Invalid captcha (refresh page.)"])
        try:
            user = User.get(User.email == form.email.data)
        except User.DoesNotExist:
            return jsonify(status="ok")  # Silently fail every time.

        # User exists, check if they don't already have a key sent
        try:
            key = UserMetadata.get((UserMetadata.uid == user.uid) & (UserMetadata.key == 'recovery-key'))
            keyExp = UserMetadata.get((UserMetadata.uid == user.uid) & (UserMetadata.key == 'recovery-key-time'))
            expiration = float(keyExp.value)
            if (time.time() - expiration) > 86400:  # 1 day
                # Key is old. remove it and proceed
                key.delete_instance()
                keyExp.delete_instance()
            else:
                return jsonify(status="ok")
        except UserMetadata.DoesNotExist:
            pass

        # checks done, doing the stuff.
        rekey = uuid.uuid4()
        UserMetadata.create(uid=user.uid, key='recovery-key', value=rekey)
        UserMetadata.create(uid=user.uid, key='recovery-key-time', value=time.time())

        sendMail(
            subject='Password recovery',
            to=user.email,
            content="""<h1><strong>{0}</strong></h1>
            <p>Somebody (most likely you) has requested a password reset for
            your account</p>
            <p>To proceed, visit the following address (valid for the next 24hs)</p>
            <a href="{1}">{1}</a>
            <hr>
            <p>If you didn't request a password recovery, please ignore this
            email</p>
            """.format(config.site.lema, url_for('password_reset', key=rekey,
                                            uid=user.uid, _external=True))
        )

        return jsonify(status="ok")
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/reset", methods=['POST'])
def reset():
    """ Password reset. Takes key and uid and changes password """
    if current_user.is_authenticated:
        abort(403)

    form = forms.PasswordResetForm()
    if form.validate():
        try:
            user = User.get(User.uid == form.user.data)
        except User.DoesNotExist:
            return jsonify(status='error')

        # User exists, check if they don't already have a key sent
        try:
            key = UserMetadata.get((UserMetadata.uid == user.uid) & (UserMetadata.key == 'recovery-key'))
            keyExp = UserMetadata.get((UserMetadata.uid == user.uid) & (UserMetadata.key == 'recovery-key-time'))
            expiration = float(keyExp.value)
            if (time.time() - expiration) > 86400:  # 1 day
                # key has expired. Remove
                key.delete_instance()
                keyExp.delete_instance()
                return jsonify(status='error')
        except UserMetadata.DoesNotExist:
            return jsonify(status='error')

        if key.value != form.key.data:
            return jsonify(status='error')

        key.delete_instance()
        keyExp.delete_instance()

        # All good. Set da password.
        password = bcrypt.hashpw(form.password.data.encode('utf-8'), bcrypt.gensalt())
        user.password = password
        user.save()
        login_user(misc.load_user(user.uid))
        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route("/do/edit_comment", methods=['POST'])
@login_required
def edit_comment():
    """ Edits a comment """
    form = forms.EditCommentForm()
    if form.validate():
        try:
            comment = SubPostComment.get(SubPostComment.cid == form.cid.data)
        except SubPostComment.DoesNotExist:
            return jsonify(status='error', error=['Comment does not exist'])

        if comment.uid_id != current_user.uid and not current_user.is_admin():
            return jsonify(status='error', error=['Not authorized'])
            
        post = SubPost.get(SubPost.pid == comment.pid)
        sub = Sub.get(Sub.sid == post.sid)
        if current_user.is_subban(sub):
            return jsonify(status='error', error=['You are banned on this sub.'])

        if comment.status == '1':
            return jsonify(status='error',
                           error="You can't edit a deleted comment")
        
        if (datetime.datetime.utcnow() - post.posted.replace(tzinfo=None)) > datetime.timedelta(days=60):
            return jsonify(status='error', error="Post is archived")
        
        dt = datetime.datetime.utcnow()
        spm = SubPostCommentHistory.create(cid=comment.cid, content=comment.content, datetime=dt if not comment.lastedit else comment.lastedit)
        spm.save()
        comment.content = form.text.data
        comment.lastedit = dt
        comment.save()
        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)[0]})


@do.route("/do/delete_comment", methods=['POST'])
@login_required
def delete_comment():
    """ deletes a comment """
    form = forms.DeleteCommentForm()
    if form.validate():
        try:
            comment = SubPostComment.get(SubPostComment.cid == form.cid.data)
        except SubPostComment.DoesNotExist:
            return jsonify(status='error', error='Comment does not exist')
        post = SubPost.get(SubPost.pid == comment.pid)

        if comment.uid_id != current_user.uid and not (current_user.is_admin() or current_user.is_mod(post.sid)):
            return jsonify(status='error', error='Not authorized')

        if comment.uid_id != current_user.uid and (current_user.is_admin() or current_user.is_mod(post.sid)):
            misc.create_sublog(misc.LOG_TYPE_SUB_DELETE_COMMENT, current_user.uid, post.sid,
                               comment=form.reason.data, link=url_for('view_post_inbox', pid=comment.pid),
                               admin=True if (not current_user.is_mod(post.sid) and current_user.is_admin()) else False)

        comment.status = 1
        comment.save()

        q = Message.delete().where(Message.mlink == form.cid.data)
        q.execute()
        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route('/do/vote/<pid>/<value>', methods=['POST'])
def upvote(pid, value):
    """ Logs an upvote to a post. """
    form = DummyForm()
    if not form.validate():
        return json.dumps({'status': 'error', 'error': get_errors(form)}), 400
    if not current_user.is_authenticated:
        return jsonify(msg='Not authenticated'), 403

    return misc.cast_vote(current_user.uid, "post", pid, value)


@do.route('/do/votecomment/<cid>/<value>', methods=['POST'])
def upvotecomment(cid, value):
    """ Logs an upvote to a post. """
    form = DummyForm()
    if not form.validate():
        return json.dumps({'status': 'error', 'error': get_errors(form)})
    
    if not current_user.is_authenticated:
        return jsonify(msg='Not authenticated'), 403

    return misc.cast_vote(current_user.uid, "comment", cid, value)


@do.route('/do/get_children/<int:pid>/<cid>/<lim>', methods=['post'])
@do.route('/do/get_children/<int:pid>/<cid>', methods=['post'], defaults={'lim': ''})
def get_sibling(pid, cid, lim): 
    """ Gets children comments for <cid> """
    try:
        post = misc.getSinglePost(pid)
    except SubPost.DoesNotExist:
        return jsonify(status='ok', posts=[])

    if cid == 'null':
        cid = '0'
    if cid != '0':
        try:
            root = SubPostComment.get(SubPostComment.cid == cid)
            if root.pid_id != post['pid']:
                return jsonify(status='ok', posts=[])
        except SubPostComment.DoesNotExist:
            return jsonify(status='ok', posts=[])

    comments = SubPostComment.select(SubPostComment.cid, SubPostComment.parentcid).where(SubPostComment.pid == pid).order_by(SubPostComment.score.desc()).dicts()
    if not comments.count():
        return engine.get_template('sub/postcomments.html').render({'post': post, 'comments': [], 'subInfo': {}, 'highlight': ''})

    if lim:
        comment_tree = misc.get_comment_tree(comments, cid if cid != '0' else None, lim, provide_context=False, uid=current_user.uid)
    elif cid != '0':
        comment_tree = misc.get_comment_tree(comments, cid, provide_context=False, uid=current_user.uid)
    else:
        return engine.get_template('sub/postcomments.html').render({'post': post, 'comments': [], 'subInfo': {}, 'highlight': ''})

    if len(comment_tree) > 0 and cid != '0':
        comment_tree = comment_tree[0].get('children', [])
    subInfo = misc.getSubData(post['sid'])
    subMods = misc.getSubMods(post['sid'])

    return engine.get_template('sub/postcomments.html').render({'post': post, 'comments': comment_tree, 'subInfo': subInfo, 'subMods': subMods, 'highlight': ''})


@do.route('/do/preview', methods=['POST'])
@login_required
def preview():
    """ Returns parsed markdown. Used for post and comment previews. """
    form = DummyForm()
    if form.validate():
        if request.json.get('text'):
            return jsonify(status='ok', text=misc.our_markdown(request.json.get('text')))
        else:
            return jsonify(status='error', error='Missing text')
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route('/do/nsfw', methods=['POST'])
@login_required
def toggle_nsfw():
    """ Toggles NSFW tag on posts """
    form = DeletePost()

    if form.validate():
        try:
            post = SubPost.get(SubPost.pid == form.post.data)
        except SubPost.DoesNotExist:
            return json.dumps({'status': 'error', 'error': 'Post does not exist'})

        if current_user.uid == post.uid_id or current_user.is_admin() or current_user.is_mod(post.sid):
            post.nsfw = 1 if post.nsfw == 0 else 0
            post.save()
            return json.dumps({'status': 'ok', 'msg': 'NSFW set to {0}'.format(bool(post.nsfw))})
        else:
            return json.dumps({'status': 'error', 'error': 'Not authorized'})
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route('/do/toggle_ignore/<uid>', methods=['POST'])
@login_required
def ignore_user(uid):
    try:
        user = User.get(User.uid == uid)
    except User.DoesNotExist:
        return jsonify(status='error', error='User not found')

    try:
        uig = UserIgnores.get((UserIgnores.uid == current_user.uid) & (UserIgnores.target == uid))
        uig.delete_instance()
        return jsonify(status='ok', action='delete')
    except UserIgnores.DoesNotExist:
        uig = UserIgnores.create(uid=current_user.uid, target=user.uid)
        return jsonify(status='ok', action='ignore')


@do.route('/do/upload/<sub>', methods=['POST'])
@login_required
def sub_upload(sub):
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        abort(404)

    if not current_user.is_mod(sub.sid, 1) and not current_user.is_admin():
        abort(403)

    c = SubStylesheet.get(SubStylesheet.sid == sub.sid)
    form = EditSubCSSForm(css=c.source)
    # get remaining space
    remaining = 1024 * 1024 * 2  # 2M
    ufiles = SubUploads.select().where(SubUploads.sid == sub.sid)
    for uf in ufiles:
        remaining -= uf.size

    fname = request.form.get('name')
    if len(fname) > 10:
        return engine.get_template('sub/css.html').render({'sub': sub, 'form': form, 'storage': int(remaining - (1024 * 1024)),
                                                           'error': 'File name too long.', 'files': ufiles})

    if len(fname) < 3:
        return engine.get_template('sub/css.html').render({'sub': sub, 'form': form, 'storage': int(remaining - (1024 * 1024)),
                                                           'error': 'File name too short or missing.', 'files': ufiles})

    if not allowedNames.match(fname):
        return engine.get_template('sub/css.html').render({'sub': sub, 'form': form, 'storage': int(remaining - (1024 * 1024)),
                                                           'error': 'Invalid file name.', 'files': ufiles})

    ufile = request.files.getlist('files')[0]
    if ufile.filename == '':
        return engine.get_template('sub/css.html').render({'sub': sub, 'form': form, 'storage': int(remaining - (1024 * 1024)),
                                                           'error': 'Please select a file to upload.', 'files': ufiles})

    mtype = magic.from_buffer(ufile.read(1024), mime=True)

    if mtype == 'image/jpeg':
        extension = '.jpg'
    elif mtype == 'image/png':
        extension = '.png'
    elif mtype == 'image/gif':
        extension = '.gif'
    else:
        return engine.get_template('sub/css.html').render({'sub': sub, 'form': form, 'storage': int(remaining - (1024 * 1024)),
                                                           'error': 'Invalid file type. Only jpg, png and gif allowed.', 'files': ufiles})

    ufile.seek(0)
    md5 = hashlib.md5()
    while True:
        data = ufile.read(65536)
        if not data:
            break
        md5.update(data)

    f_name = str(uuid.uuid5(misc.FILE_NAMESPACE, md5.hexdigest())) + extension
    ufile.seek(0)
    lm = False
    if not os.path.isfile(os.path.join(config.storage.uploads.path, f_name)):
        lm = True
        ufile.save(os.path.join(config.storage.uploads.path, f_name))
        # remove metadata
        if mtype != 'image/gif':  # Apparently we cannot write to gif images
            md = pyexiv2.ImageMetadata(os.path.join(config.storage.uploads.path, f_name))
            md.read()
            for k in (md.exif_keys + md.iptc_keys + md.xmp_keys):
                del md[k]
            md.write()
    # sadly, we can only get file size accurately after saving it
    fsize = os.stat(os.path.join(config.storage.uploads.path, f_name)).st_size
    if fsize > remaining:
        if lm:
            os.remove(os.path.join(config.storage.uploads.path, f_name))
        return engine.get_template('sub/css.html').render({'sub': sub, 'form': form, 'storage': int(remaining - (1024 * 1024)),
                                                           'error': 'Not enough available space to upload file.', 'files': ufiles})
    # THUMBNAIL
    ufile.seek(0)
    im = Image.open(ufile).convert('RGB')
    x, y = im.size
    while y > x:
        slice_height = min(y - x, 10)
        bottom = im.crop((0, y - slice_height, x, y))
        top = im.crop((0, 0, x, slice_height))

        if misc._image_entropy(bottom) < misc._image_entropy(top):
            im = im.crop((0, 0, x, y - slice_height))
        else:
            im = im.crop((0, slice_height, x, y))

        x, y = im.size

    im.thumbnail((70, 70), Image.ANTIALIAS)

    im.seek(0)
    md5 = hashlib.md5(im.tobytes())
    filename = str(uuid.uuid5(misc.THUMB_NAMESPACE, md5.hexdigest())) + '.jpg'
    im.seek(0)
    if not os.path.isfile(os.path.join(config.storage.thumbnails.path, filename)):
        im.save(os.path.join(config.storage.thumbnails.path, filename), "JPEG", optimize=True, quality=85)
    im.close()

    SubUploads.create(sid=sub.sid, fileid=f_name, thumbnail=filename, size=fsize, name=fname)
    SubLog.create(sid=sub.sid, action=4, link=url_for('sub.view_sub', sub=sub.name), time=datetime.datetime.utcnow(),
                      desc='{0} modified the sub\'s stylesheet (uploaded file)'.format(current_user.name))
    return redirect(url_for('sub.edit_sub_css', sub=sub.name))


@do.route('/do/upload/<sub>/delete/<name>', methods=['POST'])
@login_required
def sub_upload_delete(sub, name):
    try:
        sub = Sub.get(fn.Lower(Sub.name) == sub.lower())
    except Sub.DoesNotExist:
        jsonify(status='error')  # descriptive errors where?
    form = DummyForm()
    if not form.validate():
        return redirect(url_for('sub.edit_sub_css', sub=sub.name))
    if not current_user.is_mod(sub.sid, 1) and not current_user.is_admin():
        jsonify(status='error')

    try:
        img = SubUploads.get((SubUploads.sid == sub.sid) & (SubUploads.name == name))
    except SubUploads.DoesNotExist:
        jsonify(status='error')
    fileid = img.fileid
    img.delete_instance()
    SubLog.create(sid=sub.sid, action=4, link=url_for('sub.view_sub', sub=sub.name), time=datetime.datetime.utcnow(),
                      desc='{0} modified the sub\'s stylesheet (removed upload)'.format(current_user.name))

    # We won't delete the pic if somebody else is still using it..
    try:
        UserUploads.get(UserUploads.fileid == fileid)
    except UserUploads.DoesNotExist:
        try:
            SubUploads.get(SubUploads.fileid == img.fileid)
        except SubUploads.DoesNotExist:
            os.remove(os.path.join(config.storage.uploads.path, img.fileid))

    return jsonify(status='ok')


@do.route('/do/admin/create_question', methods=['POST'])
@login_required
def create_question():
    if not current_user.is_admin():
        abort(403)

    form = SecurityQuestionForm()

    if form.validate():
        SiteMetadata.create(key='secquestion', value=form.question.data + '|' + form.answer.data)
        return jsonify(status='ok')
    return jsonify(status='error')


@do.route('/do/admin/delete_question/<xid>', methods=['POST'])
@login_required
def delete_question(xid):
    if not current_user.is_admin():
        abort(403)

    form = DummyForm()
    if not form.validate():
        return jsonify(status='error')
    try:
        th = SiteMetadata.get((SiteMetadata.key == 'secquestion') & (SiteMetadata.xid == xid))
    except SiteMetadata.DoesNotExist:
        return jsonify(status='error')
    th.delete_instance()
    return jsonify(status='ok')


@do.route('/do/admin/ban_user/<username>', methods=['POST'])
@login_required
def ban_user(username):
    if not current_user.is_admin():
        abort(403)

    form = DummyForm()
    if not form.validate():
        abort(403)

    try:
        user = User.get(fn.Lower(User.name) == username.lower())
    except User.DoesNotExist:
        abort(404)

    user.status = 5
    user.save()
    misc.create_sitelog(misc.LOG_TYPE_USER_BAN, uid=current_user.uid, comment=user.name)
    return redirect(url_for('view_user', user=username))


@do.route('/do/edit_top_bar', methods=['POST'])
@login_required
def edit_top_bar():
    form = DummyForm()
    if not form.validate():
        return jsonify(status='error', error='no CSRF')

    data = request.get_json()
    if not data.get('sids'):
        return jsonify(status='error')

    for i in data.get('sids'):
        # Check if we're being fed good UUIDs
        try:
            val = uuid.UUID(i, version=4)
        except ValueError:
            return jsonify(status='error')

    # If all the sids are good, we do the thing.
    i = 0
    for k in data.get('sids'):
        i += 1
        try:
            SubSubscriber.update(order=i).where((SubSubscriber.uid == current_user.uid) & (SubSubscriber.sid == k)).execute()
        except SubSubscriber.DoesNotExist:
            pass  # TODO: Add these as status=4 SubSubscriber (after implementing some way to delete those)

    return jsonify(status='ok')


@do.route('/do/admin/undo_votes/<uid>', methods=['POST'])
@login_required
def admin_undo_votes(uid):
    if not current_user.admin:
        abort(403)
    
    try:
        user = User.get(User.uid == uid)
    except User.DoesNotExist:
        return abort(404)

    form = DummyForm()
    if not form.validate():
        return redirect(url_for('view_user', user=user.name))
    

    post_v = SubPostVote.select().where(SubPostVote.uid == user.uid)
    comm_v = SubPostCommentVote.select().where(SubPostCommentVote.uid == user.uid)
    usr = {}

    for v in post_v:
        try:
            post = SubPost.select(SubPost.pid, SubPost.upvotes, SubPost.downvotes, SubPost.uid, SubPost.score).where(SubPost.pid == v.pid_id).get()
        except SubPost.DoesNotExist:
            # Edge case. An orphan vote.
            v.delete_instance()
            continue
        # Not removing self-votes
        if post.uid_id == user.uid:
            continue
        if not usr.get(post.uid_id):
            usr[post.uid_id] = User.select(User.uid, User.score).where(User.uid == post.uid_id).get()
        tgus = usr[post.uid_id]
        post.score -= 1 if v.positive else -1
        tgus.score -= 1 if v.positive else -1
        user.given -= 1 if v.positive else -1
        if post.upvotes is not None and post.downvotes is not None:
            if v.positive:
                post.upvotes -= 1
            else:
                post.downvotes -= 1
        post.save()
        tgus.save()
        v.delete_instance()
    for v in comm_v:
        try:
            comm = SubPostComment.select(SubPostComment.cid, SubPostComment.upvotes, SubPostComment.downvotes, SubPostComment.score, SubPostComment.uid).where(SubPostComment.cid == v.cid).get()
        except SubPostComment.DoesNotExist:
            # Edge case. An orphan vote.
            v.delete_instance()
            continue
        if not usr.get(comm.uid_id):
            usr[comm.uid_id] = User.select(User.uid, User.score).where(User.uid == comm.uid_id).get()
        tgus = usr[comm.uid_id]
        if not comm.score:
            comm.score = 0
        else:
            comm.score -= 1 if v.positive else -1
        tgus.score -= 1 if v.positive else -1
        user.given -= 1 if v.positive else -1
        if comm.upvotes is not None and comm.downvotes is not None:
            if v.positive:
                comm.upvotes -= 1
            else:
                comm.downvotes -= 1
        comm.save()
        tgus.save()
        v.delete_instance()
    user.save()
    return redirect(url_for('view_user', user=user.name))


@do.route('/do/cast_vote/<pid>/<oid>', methods=['POST'])
@login_required
def cast_vote(pid, oid):
    form = DummyForm()
    if form.validate():
        try:
            post = misc.getSinglePost(pid)
        except SubPost.DoesNotExist:
            return jsonify(status='error', error='Post does not exist')
        
        if post['ptype'] != 3:
            return jsonify(status='error', error='Post is not a poll')

        try:
            option = SubPostPollOption.get((SubPostPollOption.id == oid) & (SubPostPollOption.pid == pid))
        except SubPostPollOption.DoesNotExist:
            return jsonify(status='error', error='Poll option does not exist')

        # Check if user hasn't voted already.
        try:
            SubPostPollVote.get((SubPostPollVote.uid == current_user.uid) & (SubPostPollVote.pid == pid))
            return jsonify(status='error', error='Already voted')
        except SubPostPollVote.DoesNotExist:
            pass
        
        # Check if poll is still open...
        try:
            SubPostMetadata.get((SubPostMetadata.pid == pid) & (SubPostMetadata.key == 'poll_closed'))
            return jsonify(status='error', error='Poll is closed')
        except SubPostMetadata.DoesNotExist:
            pass

        try:
            ca = SubPostMetadata.get((SubPostMetadata.pid == pid) & (SubPostMetadata.key == 'poll_closes_time'))
            if int(ca.value) < time.time():
                return jsonify(status='error', error='Poll is closed')
        except SubPostMetadata.DoesNotExist:
            pass
        
        try:
            ca = SubPostMetadata.get((SubPostMetadata.pid == pid) & (SubPostMetadata.key == 'poll_vote_after_level'))
            if current_user.get_user_level()[0] < int(ca.value):
                return jsonify(status='error', error='Insufficient user level')
        except SubPostMetadata.DoesNotExist:
            pass

        # Everything OK. Issue vote.
        vote = SubPostPollVote.create(uid=current_user.uid, pid=pid, vid=oid)
    return jsonify(status='ok')


@do.route('/do/remove_vote/<pid>', methods=['POST'])
@login_required
def remove_vote(pid):
    form = DummyForm()
    if form.validate():
        try:
            post = misc.getSinglePost(pid)
        except SubPost.DoesNotExist:
            return jsonify(status='error', error='Post does not exist')
        
        if post['ptype'] != 3:
            return jsonify(status='error', error='Post is not a poll')

        # Check if poll is still open...
        try:
            SubPostMetadata.get((SubPostMetadata.pid == pid) & (SubPostMetadata.key == 'poll_closed'))
            return jsonify(status='error', error='Poll is closed')
        except SubPostMetadata.DoesNotExist:
            pass

        try:
            ca = SubPostMetadata.get((SubPostMetadata.pid == pid) & (SubPostMetadata.key == 'poll_closes_time'))
            if int(ca.value) < time.time():
                return jsonify(status='error', error='Poll is closed')
        except SubPostMetadata.DoesNotExist:
            pass
        
        # Check if user hasn't voted already.
        try:
            vote = SubPostPollVote.get((SubPostPollVote.uid == current_user.uid) & (SubPostPollVote.pid == pid))
            vote.delete_instance()
        except SubPostPollVote.DoesNotExist:
            pass
    return jsonify(status='ok')


@do.route('/do/close_poll', methods=['POST'])
@login_required
def close_poll():
    """ Closes a poll. """
    form = DeletePost()

    if form.validate():
        try:
            post = SubPost.get(SubPost.pid == form.post.data)
        except SubPost.DoesNotExist:
            return json.dumps({'status': 'error', 'error': 'Post does not exist'})

        if post.ptype != 3:
            abort(404)
        
        if current_user.uid == post.uid_id or current_user.is_admin() or current_user.is_mod(post.sid):
            # Check if poll's not closed already
            postmeta = misc.metadata_to_dict(SubPostMetadata.select().where(SubPostMetadata.pid == post.pid))
            if 'poll_closed' in postmeta:
                return json.dumps({'status': 'error', 'error': 'Poll already closed.'})

            if 'poll_closes_time' in postmeta:
                if int(postmeta['poll_closes_time']) < time.time():
                    return json.dumps({'status': 'error', 'error': 'Poll already closed.'})
            
            SubPostMetadata.create(pid=post.pid, key='poll_closed', value='1')
            return json.dumps({'status': 'ok'})
        else:
            abort(403)
    return json.dumps({'status': 'error', 'error': get_errors(form)})

try:
    import callbacks
    callbacks_enabled = True
except ModuleNotFoundError:
    callbacks_enabled = False

@do.route('/do/report', methods=['POST'])
@login_required
def report():
    form = DeletePost()
    if form.validate():
        try:
            post = misc.getSinglePost(form.post.data)
        except SubPost.DoesNotExist:
            return jsonify(status='error', error='Post does not exist')
        
        if post['deleted'] != 0:
            return jsonify(status='error', error='Post does not exist')
        
        # check if user already reported the post
        try:
            rep = SubPostReport.get((SubPostReport.pid == post['pid']) & (SubPostReport.uid == current_user.uid))
            return jsonify(status='error', error='You have already reported this post')
        except SubPostReport.DoesNotExist:
            pass
        
        if len(form.reason.data) < 2:
            return jsonify(status='error', error='Report reason too short.')

        # do the reporting.
        SubPostReport.create(pid=post['pid'], uid=current_user.uid, reason=form.reason.data)
        if callbacks_enabled:
            # callbacks!
            cb = getattr(callbacks, 'ON_POST_REPORT', False)
            if cb:
                cb(post, current_user, form.reason.data)
        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)})


@do.route('/do/report/comment', methods=['POST'])
@login_required
def report_comment():
    form = DeletePost()
    if form.validate():
        try:
            comm = SubPostComment.select(SubPostComment.cid, SubPostComment.content, SubPostComment.lastedit,
                                         SubPostComment.score, SubPostComment.status, SubPostComment.time, SubPostComment.pid,
                                         User.name.alias('username'), SubPostComment.uid,
                                         User.status.alias('userstatus'), SubPostComment.upvotes, SubPostComment.downvotes)
            comm = comm.join(User, on=(User.uid == SubPostComment.uid)).switch(SubPostComment)
            comm = comm.where(SubPostComment.cid == form.post.data)
            comm = comm.get()
        except SubPostComment.DoesNotExist:
            return jsonify(status='error', error='Comment does not exist')
        
        if comm.status:
            return jsonify(status='error', error='Comment does not exist')
        
        # check if user already reported the post
        try:
            rep = SubPostCommentReport.get((SubPostCommentReport.cid == comm.cid) & (SubPostCommentReport.uid == current_user.uid))
            return jsonify(status='error', error='You have already reported this post')
        except SubPostCommentReport.DoesNotExist:
            pass
        
        if len(form.reason.data) < 2:
            return jsonify(status='error', error='Report reason too short.')

        # do the reporting.
        SubPostCommentReport.create(cid=comm.cid, uid=current_user.uid, reason=form.reason.data)
        # callbacks!
        if callbacks_enabled:
            cb = getattr(callbacks, 'ON_COMMENT_REPORT', False)
            if cb:
                cb(comm, current_user, form.reason.data)
        return jsonify(status='ok')
    return json.dumps({'status': 'error', 'error': get_errors(form)})