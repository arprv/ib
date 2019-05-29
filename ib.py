import MySQLdb
from wand.image import Image
import datetime
import re
import os

from collections import namedtuple
Option = namedtuple('Option', ['success', 'value'])

from flask import Flask, render_template, url_for, request, redirect, Markup
ib = Flask(__name__)
ib.debug = True

from conf import *
import cred

def get_remote_IP():
    trusted_proxies = {'127.0.0.1'}
    route = request.access_route + [request.remote_addr]

    return next(
        (addr for addr in reversed(route) if addr not in trusted_proxies),
        request.remote_addr
    )

def store_file(f, cursor, OP=False):
    f_size = os.fstat(f.fileno()).st_size

    # Make sure the file is not too large
    if f_size > MAX_FILE_SIZE:
        return Option(
            False,
            'Filesize exceeds maximum (%dMB).' % (MAX_FILE_SIZE // pow(1024, 2))
        )

    # Create a thmbnail
    img = Image(blob=f.read())
    width = img.width
    height = img.height
    if width > height:
        img.transform(resize=str(MAX_IMG_WH if not OP else MAX_OP_IMG_WH) + 'x')
    else:
        img.transform(resize='x' + str(MAX_IMG_WH if not OP else MAX_OP_IMG_WH))

    # Add the image and thumbnailto the file table
    f.stream.seek(0,0)
    res = '%sx%s' % (width, height)
    cursor.execute(
        'INSERT INTO files (NAME, SIZE, RES, FILE, THUMB) '
        'VALUES (%s, %s, %s, %s, %s)',
        # TODO: Might have to rewidn
        (f.filename, f_size, res, f.read(), img.make_blob())
    )

    img.close()

    return Option(True, cursor.lastrowid)

def fetch_file(id, thumb=False):
    conn = MySQLdb.connect(
        host    = cred.SQL_HOST,
        user    = cred.SQL_USER,
        passwd  = cred.SQL_PASS,
        db      = cred.SQL_DB
    )
    cursor = conn.cursor()

    if thumb:
        cursor.execute('SELECT THUMB FROM files WHERE ID = %s', (id,))
    else:
        cursor.execute('SELECT FILE FROM files WHERE ID = %s', (id,))
    t = cursor.fetchone()

    ret = ''
    if not t:
        ret = render_template('error.html', message='File does not exist.')
    else:
        ret = ib.response_class(t, mimetype='application/octet-stream')

    cursor.close()
    conn.commit()
    conn.close()

    return ret

def is_allowed(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def purge_thread(thread, cursor):
    # Fetch info on files to be deleted
    cursor.execute(
        'SELECT posts.FILE_ID FROM posts '
        'INNER JOIN files ON posts.FILE_ID=files.ID '
        'WHERE posts.THREAD_ID = %s OR posts.ID = %s',
        (thread, thread)
    )

    # Purge files from the table
    for f in cursor.fetchall():
        cursor.execute('DELETE FROM files WHERE ID = %s', (f,))

    # Delete all posts in the thread
    cursor.execute(
        'DELETE FROM posts WHERE THREAD_ID = %s OR ID = %s',
        (thread, thread)
    )

    # Delete the thread
    cursor.execute('DELETE FROM threads WHERE ID = %s', (thread,))

def fetch_thread_data(threads, cursor):
    for thread in threads:
        # Fetch OP
        cursor.execute(
            'SELECT ID, TIME, USERNAME, TEXT '
            'FROM posts WHERE ID = %s',
            (thread['ID'], )
        )
        thread['OP'] = cursor.fetchone()
        cursor.execute(
            'SELECT LINKED_BY FROM post_links WHERE POST=%s',
            (thread['ID'], )
        )
        thread['OP']['LINKS'] = map(lambda d: d['LINKED_BY'], cursor.fetchall())

        # Fetch Replies
        cursor.execute(
            'SELECT ID, TIME, USERNAME, TEXT '
            'FROM posts WHERE THREAD_ID = %s',
            (thread['ID'], )
        )
        thread['POSTS'] = cursor.fetchall()

        # Fetch post links
        for post in thread['POSTS']:
            cursor.execute(
                'SELECT LINKED_BY FROM post_links WHERE POST=%s',
                (post['ID'], )
            )
            post['LINKS'] = map(lambda d: d['LINKED_BY'], cursor.fetchall())

        # Get thread statistics
        # TODO: Use COUNT?
        thread['I_COUNT'] = cursor.execute(
            'SELECT ID FROM posts WHERE FILE_ID IS NOT NULL AND THREAD_ID = %s',
            (thread['ID'], )
        ) + 1
        thread['R_COUNT'] = cursor.execute(
            'SELECT ID FROM posts WHERE THREAD_ID = %s',
            (thread['ID'], )
        )

        thread['P_COUNT'] = cursor.execute(
            'SELECT DISTINCT IP FROM posts WHERE THREAD_ID=%s',
            (thread['ID'], )
        )

        # Get file info
        cursor.execute(
            'SELECT ID, NAME, SIZE, RES FROM files '
            'WHERE ID = (SELECT FILE_ID FROM posts WHERE ID = %s)',
            (thread['OP']['ID'], )
        )
        thread['OP']['FILE'] = cursor.fetchone()
        for post in thread['POSTS']:
            cursor.execute(
                'SELECT ID, NAME, SIZE, RES FROM files '
                'WHERE ID = (SELECT FILE_ID FROM posts WHERE ID = %s)',
                (post['ID'], )
            )
            t = cursor.fetchone()
            if t:
                post['FILE'] = t

@ib.route('/')
def board():
    conn = MySQLdb.connect(
        host    = cred.SQL_HOST,
        user    = cred.SQL_USER,
        passwd  = cred.SQL_PASS,
        db      = cred.SQL_DB
    )
    cursor = conn.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute('SELECT * FROM threads ORDER BY LAST_POST DESC')
    threads = cursor.fetchall()

    fetch_thread_data(threads, cursor)

    cursor.close()
    conn.commit()
    conn.close()

    return render_template(
        'board.html',
        threads=threads
    )

@ib.route('/thread/<int:thread_id>')
def thread(thread_id):
    conn = MySQLdb.connect(
        host    = cred.SQL_HOST,
        user    = cred.SQL_USER,
        passwd  = cred.SQL_PASS,
        db      = cred.SQL_DB
    )
    cursor = conn.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute('SELECT * FROM threads WHERE ID = %s', (thread_id, ))
    thread = cursor.fetchall()

    fetch_thread_data(thread, cursor)

    cursor.close()
    conn.commit()
    conn.close()

    return render_template(
        'thread.html',
        thread=thread[0]
    )

def refine_text(s):
    # Sanitize the string
    s = re.sub(r'<.*?>', '', s)

    patterns = (
        '(?P<link>>>(\d+))',
        '(?P<quote>(^|[^>])(>[^>\s]+[^>\n]*))',
    )
    subs = {
        'link': \
            lambda mo : '<a href="#p%s">%s</a>' % (mo.group(2), mo.group(1)),
        'quote': \
            lambda mo : '<span class="greentext">%s</span>' % (mo.group(3),),
    }
    regex = re.compile('|'.join(patterns), re.MULTILINE)

    # Match named group to its lambda
    def reg_match(mo):
        for k,v in mo.groupdict().iteritems():
            if v:
                return subs[k](mo)

    return regex.sub(reg_match, s).strip().replace('\n', '<br>')

def store_post(thread_id, file_id, cursor):
    # Handle link quotes
    # TODO: filter out broken links

    text = refine_text(request.form['text']) 
    if not len(text):
        return Option(False, 'Empty body.')
    if len(text) > MAX_POST_LEN:
        return Option(False, 'Post is too long.')

    # Find post links
    quoted = re.findall(r'>>(\d+)', text, flags=re.MULTILINE)

    # Set mandatory fields
    p_fields = 'TIME, TEXT, THREAD_ID, IP'
    p_phldrs = '%s, %s, %s, %s'
    p_values = (
        datetime.datetime.now(),
        text,
        thread_id,
        Markup.escape(get_remote_IP())
    )

    # Set optional fields
    if file_id:
        p_fields += ', FILE_ID'
        p_phldrs += ', %s'
        p_values += (file_id, )
    if len(request.form['name']):
        p_fields += ', USERNAME'
        p_phldrs += ', %s'
        p_values += (Markup(request.form['name'].strip()).striptags(), )

    # Store the post in the post table
    cursor.execute(
        'INSERT INTO posts (%s) VALUES (%s)' % (p_fields, p_phldrs),
        p_values
    )

    post_id = cursor.lastrowid

    # Update posts that have been referenced 
    for quote in quoted:
        cursor.execute(
            'INSERT IGNORE INTO post_links values (%s, %s)',
            (quote, post_id)
        )

    return Option(True, post_id)

@ib.route('/post', methods=['POST'])
def post():
    # Make sure all required fileds are populated and the file is legal
    if not len(request.form['text']):
        return render_template('error.html', message='Empty body.')
    if not len(request.files['file'].filename):
        return render_template('error.html', message='No file selected.')
    elif not is_allowed(request.files['file'].filename):
        return render_template('error.html', message='Illegal file extension')

    conn = MySQLdb.connect(
        host    = cred.SQL_HOST,
        user    = cred.SQL_USER,
        passwd  = cred.SQL_PASS,
        db      = cred.SQL_DB
    )
    cursor = conn.cursor()

    # Purge the thread with the oldest last reply if already at THREAD_LIMIT
    active_threads = cursor.execute('SELECT ID FROM threads')
    if active_threads >= THREAD_LIMIT:
        cursor.execute('SELECT ID FROM threads ORDER BY LAST_POST ASC LIMIT 1')
        least_active = cursor.fetchone()
        purge_thread(least_active[0], cursor)

    # Store the image
    success, val = store_file(request.files['file'], cursor, OP=True)

    # Store the thread
    if success:
        success, val = store_post(SQL_CONST_OP, val, cursor)
        if success:
            cursor.execute(
                'INSERT INTO threads (ID, LAST_POST) '
                'VALUES (%s, (SELECT TIME FROM posts WHERE ID = %s))',
                (val, val)
            )

            # Set the subject if one was provided
            if len(request.form['subject']):
                cursor.execute(
                    'UPDATE threads SET SUBJECT = %s WHERE ID = %s',
                    (Markup(request.form['subject'].strip()).striptags(), val)
                )

    cursor.close()
    conn.commit()
    conn.close()

    if not success:
        return render_template('error.html', message=val)
    else:
        return redirect(url_for('board'))

@ib.route('/reply/<int:thread_id>', methods=['POST'])
def reply(thread_id):
    if not len(request.form['text']):
        return render_template('error.html', message='Empty body.')

    conn = MySQLdb.connect(
        host    = cred.SQL_HOST,
        user    = cred.SQL_USER,
        passwd  = cred.SQL_PASS,
        db      = cred.SQL_DB
    )
    cursor = conn.cursor()

    # Store file if attached
    success = False
    if len(request.files['file'].filename):
        success, val = store_file(request.files['file'], cursor, OP=False)
    # Store the reply
    success, val = store_post(thread_id, val if success else None, cursor)

    if success:
        # Update the time of last post for the thread unless we reached bump
        # limit
        bumps = cursor.execute(
            'SELECT ID FROM posts WHERE THREAD_ID=%s',
            (thread_id, )
        )
        if bumps < BUMP_LIMIT:
            cursor.execute(
                'UPDATE threads '
                'SET LAST_POST = (SELECT TIME FROM posts WHERE ID = %s) '
                'WHERE ID = %s',
                (val, thread_id)
            )

    cursor.close()
    conn.commit()
    conn.close()

    if not success:
        return render_template('error.html', message=val)
    else:
        return redirect(url_for('thread', thread_id=thread_id))

@ib.route('/thumbs/<int:id>', methods=['GET'])
def thumbs(id):
    return fetch_file(id, thumb=True)

@ib.route('/files/<int:id>', methods=['GET'])
def files(id):
    return fetch_file(id)

