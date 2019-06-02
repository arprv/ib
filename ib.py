import MySQLdb
import MySQLdb.cursors
import json
from contextlib import closing
from htmlmin.main import minify

from flask import Flask, render_template, url_for, request, redirect, Markup
from flask import jsonify
ib = Flask(__name__)
ib.config.from_object('conf.FlaskRestConf')
ib.jinja_env.trim_blocks = True
ib.jinja_env.lstrip_blocks = True

from flask_restful import Resource, Api
api = Api(ib)

from conf import *
import util

class ApiBoard(Resource):
    def get(self):
        with closing(util.conn2db()) as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM threads')
                threads = cursor.fetchall()
                for thread in threads:
                    cursor.execute(
                        'SELECT ID FROM posts WHERE THREAD_ID = %s',
                        (thread['ID'], )
                    )
                    thread['REPLIES'] = [x['ID'] for x in cursor.fetchall()]
                return jsonify(threads)
class ApiThread(Resource):
    def get(self, id):
        with closing(util.conn2db()) as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM threads WHERE ID=%s', (id, ))
                thread = cursor.fetchone()
                util.fetch_thread_data([thread], cursor, IPs=False)
                return thread
class ApiPost(Resource):
    def get(self, id):
        with closing(util.conn2db()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT ID, TIME, USERNAME, TEXT, FILE_ID, THREAD_ID '
                    'FROM posts WHERE ID=%s',
                    (id, )
                )
                return cursor.fetchone()
class ApiFile(Resource):
    def get(self, id):
        with closing(util.conn2db()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT ID, NAME, SIZE, RES FROM files WHERE ID = %s',
                    (id, )
                )
                return cursor.fetchone()

api.add_resource(ApiBoard,  '/api/board')
api.add_resource(ApiThread, '/api/threads/<int:id>')
api.add_resource(ApiPost,   '/api/posts/<int:id>')
api.add_resource(ApiFile,   '/api/files/<int:id>')

@ib.after_request
def minify_response(response):
    if response.content_type == 'text/html; charset=utf-8':
        response.set_data(minify(response.get_data(as_text=True)))
    return response

@ib.route('/')
def board():
    with closing(util.conn2db()) as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM threads ORDER BY LAST_POST DESC')
            threads = cursor.fetchall()

            util.fetch_thread_data(threads, cursor)

    return render_template(
        'board_page.html',
        threads = threads,
        cIP = util.get_remote_IP()
    )

@ib.route('/threads/<int:thread_id>')
def threads(thread_id):
    with closing(util.conn2db()) as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM threads WHERE ID = %s', (thread_id, ))
            thread = cursor.fetchall()

            util.fetch_thread_data(thread, cursor)

    if thread:
        return render_template(
            'thread_page.html',
            thread = thread[0],
            cIP = util.get_remote_IP()
        )
    else:
        return render_template('error.html', message='Thread does not exist.')


@ib.route('/post', methods=['POST'])
def post():
    # Make sure all required fileds are populated and the file is legal
    if not len(request.form['text']):
        return render_template('error.html', message='Empty body.')
    if not len(request.files['file'].filename):
        return render_template('error.html', message='No file selected.')

    with closing(util.conn2db()) as conn:
        with conn.cursor() as cursor:
            # Make sure the poster is not banned
            if util.is_banned(util.get_remote_IP(), cursor):
                return render_template('error.html', message='You are banned.')
            # Purge the thread with the oldest last reply if already at
            # THREAD_LIMIT
            active_threads = cursor.execute('SELECT ID FROM threads')
            if active_threads >= THREAD_LIMIT:
                cursor.execute(
                    'SELECT ID FROM threads ORDER BY LAST_POST ASC LIMIT 1'
                )
                least_active = cursor.fetchone()
                util.purge_thread(least_active['ID'], cursor)

            # Store the image
            success, val = util.store_file(
                request.files['file'],
                cursor,
                OP=True
            )

            # Store the thread
            if success:
                success, val = util.store_post(SQL_CONST_OP, val, cursor)
                if success:
                    cursor.execute(
                        'INSERT INTO threads (ID, LAST_POST) '
                        'VALUES (%s, (SELECT TIME FROM posts WHERE ID = %s))',
                        (val, val)
                    )

                    # Set the subject if one was provided
                    if len(request.form['subject']):
                        s = Markup(request.form['subject'].strip()).striptags()
                        cursor.execute(
                            'UPDATE threads SET SUBJECT = %s WHERE ID = %s',
                            (s, val)
                        )
    if not success:
        return render_template('error.html', message=val)
    else:
        return redirect(url_for('board'))

@ib.route('/reply/<int:thread_id>', methods=['POST'])
def reply(thread_id):
    if not len(request.form['text']):
        return render_template('error.html', message='Empty body.')

    with closing(util.conn2db()) as conn:
        with conn.cursor() as cursor:
            # Make sure the poster is not banned
            if util.is_banned(util.get_remote_IP(), cursor):
                return render_template('error.html', message='You are banned.')
            # Store file if attached
            attached = False
            val = None
            if len(request.files['file'].filename):
                attached = True
                success, val = util.store_file(request.files['file'], cursor)

            if not attached or (attached and success):
                # Store the reply
                success, val = util.store_post(thread_id, val, cursor)

            if success:
                # Update the time of last post for the thread unless we reached
                # bump limit
                bumps = cursor.execute(
                    'SELECT ID FROM posts WHERE THREAD_ID=%s',
                    (thread_id, )
                )
                if bumps < BUMP_LIMIT:
                    cursor.execute(
                        'UPDATE threads '
                        'SET LAST_POST = '
                        '(SELECT TIME FROM posts WHERE ID = %s) '
                        'WHERE ID = %s',
                        (val, thread_id)
                    )

    if not success:
        return render_template('error.html', message=val)
    else:
        return redirect(url_for('threads', thread_id=thread_id))

@ib.route('/thumbs/<int:id>', methods=['GET'])
def thumbs(id):
    with closing(util.conn2db()) as conn:
        with conn.cursor() as cursor:
            success, v = util.fetch_file(id, cursor, thumb=True)
            if success:
                return ib.response_class(v, mimetype='application/octet-stream')
            else:
                return render_template('error.html', message=v)

@ib.route('/files/<int:id>', methods=['GET'])
def files(id):
    with closing(util.conn2db()) as conn:
        with conn.cursor() as cursor:
            success, v = util.fetch_file(id, cursor)
            if success:
                cursor.execute('SELECT NAME FROM files WHERE ID = %s', (id,))
                fname = cursor.fetchone()['NAME']
                return ib.response_class(
                    v,
                    mimetype='application/octet-stream',
                    headers={
                        "Content-Disposition": "attachment;filename=%s" % fname
                    }
                )
            else:
                return render_template('error.html', message=v)

