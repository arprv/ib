import MySQLdb
import MySQLdb.cursors
from contextlib import closing

from flask import Flask, render_template, url_for, request, redirect, Markup
ib = Flask(__name__)
ib.debug = True
ib.jinja_env.trim_blocks = True
ib.jinja_env.lstrip_blocks = True

from conf import *
import util

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

@ib.route('/thread/<int:thread_id>')
def thread(thread_id):
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
            # Purge the thread with the oldest last reply if already at
            # THREAD_LIMIT
            active_threads = cursor.execute('SELECT ID FROM threads')
            if active_threads >= THREAD_LIMIT:
                cursor.execute(
                    'SELECT ID FROM threads ORDER BY LAST_POST ASC LIMIT 1'
                )
                least_active = cursor.fetchone()
                util.purge_thread(least_active[0]['ID'], cursor)

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
        return redirect(url_for('thread', thread_id=thread_id))

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
                return ib.response_class(v, mimetype='application/octet-stream')
            else:
                return render_template('error.html', message=v)

