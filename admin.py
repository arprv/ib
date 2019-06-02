#!/bin/python3
import sys
import MySQLdb
import MySQLdb.cursors
from contextlib import closing
import util
import argparse
import ipaddress
parser = argparse.ArgumentParser(description='Administer ib instance.')
parser.add_argument(
    '-s',
    '--status',
    help='print various statistics',
    action='store_true'
)
parser.add_argument(
    '-p',
    '--purge',
    help='purge post/thread',
    nargs='+',
    type=int,
    metavar='ID'
)
parser.add_argument(
    '-l',
    '--list_banned',
    help='list banned IPs',
    action='store_true'
)
parser.add_argument('-b', '--ban', help='ban IP', nargs='+', metavar='IP')
parser.add_argument('-u', '--unban', help='unban IP', nargs='+', metavar='IP')

def main():
    args = parser.parse_args()

    with closing(util.conn2db()) as conn:
        with conn.cursor() as cursor:
            if args.status:
                posters = cursor.execute('SELECT DISTINCT IP FROM posts')
                posts = cursor.execute('SELECT * FROM posts')
                files = cursor.execute('SELECT * FROM files')
                threads = cursor.execute('SELECT * FROM threads')
                banned = cursor.execute('SELECT * FROM banned')
                print('%10s: %s' % ('threads', threads))
                print('%10s: %s' % ('posts', posts))
                print('%10s: %s' % ('files', files))
                print('%10s: %s' % ('posters', posters))
                print('%10s: %s' % ('banned', banned))

            if args.list_banned:
                cursor.execute('SELECT * FROM banned')
                for ip in cursor.fetchall():
                    print(ip['IP'])
            if args.purge:
                for id in args.purge:
                    if not util.purge_post(id, cursor):
                        print('Error: Post %d does not exist' % id)
                        sys.exit(1)
            if args.ban:
                for ip in args.ban:
                    try:
                        ipaddress.ip_address(ip)
                        cursor.execute(
                            'INSERT IGNORE INTO banned VALUES (%s)',
                            (ip, )
                        )
                    except:
                        print('Error: %s is not a valid IP address.' % ip)
                        sys.exit(1)
            if args.unban:
                for ip in args.unban:
                    try:
                        ipaddress.ip_address(ip)
                        cursor.execute(
                            'DELETE FROM banned WHERE IP = %s',
                            (ip, )
                        )
                    except:
                        print('Error: %s is not a valid IP address.' % ip)
                        sys.exit(1)


if __name__ == "__main__":
    main()
