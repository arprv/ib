import MySQLdb
from flask import request, Markup
from wand.image import Image
import datetime

from collections import namedtuple
Option = namedtuple('Option', ['success', 'value'])

import re
import os

from contextlib import contextmanager

from conf import *
import cred

def conn2db():
    conn = MySQLdb.connect(
        host        = cred.SQL_HOST,
        user        = cred.SQL_USER,
        passwd      = cred.SQL_PASS,
        db          = cred.SQL_DB,
        cursorclass = MySQLdb.cursors.DictCursor
    )
    conn.autocommit(True)
    return conn

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
    if not is_allowed(f.filename):
        return Option(False, 'Illegal file extension')


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

def fetch_file(id, cursor, thumb=False):
    if thumb:
        cursor.execute('SELECT THUMB FROM files WHERE ID = %s', (id,))
    else:
        cursor.execute('SELECT FILE FROM files WHERE ID = %s', (id,))
    t = cursor.fetchone()
    #t = t['THUMB'] if thumb else t['FILE']

    if not t:
        return Option(False, 'File does not exist.')
    else:
        return Option(True, t['THUMB'] if thumb else t['FILE'])

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
            'SELECT ID, TIME, USERNAME, TEXT, IP '
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
            'SELECT ID, TIME, USERNAME, TEXT, IP '
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

def refine_text(s):
    # Sanitize the string
    s = re.sub(r'<.*?>', '', s).strip()

    patterns = (
        '(?P<link>>>(\d+))',
        '(?P<quote>(^|[^>])(>[^>\n]+[^>\n]*))',
        '(?P<eline>(\n)\s*\n*\s*(\n))',
    )
    subs = {
        'link': lambda mo : \
            '<a class="plink" href="#p%s">%s</a>' % (mo.group(2), mo.group(1)),
        'quote': lambda mo : \
            '<span class="greentext">%s</span>' % (mo.group(3),),
        'eline': lambda mo : '%s%s' % (mo.group(7), mo.group(8)),
    }
    regex = re.compile('|'.join(patterns), re.MULTILINE)

    # Match named group to its lambda
    def reg_match(mo):
        for k,v in mo.groupdict().iteritems():
            if v:
                return subs[k](mo)

    return regex.sub(reg_match, s).replace('\n', '<br>')

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


